from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from crashcap_api.contracts import load_validator

PART_SIZE = 64 * 1024 * 1024
TERMINAL_UPLOADS = {"ACCEPTED", "REJECTED", "QUARANTINED"}


class PublishError(RuntimeError):
    pass


class ApiClient:
    def __init__(self, base_url: str, *, retries: int = 4, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.retries = retries
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, *, json_body: object | None = None) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        for attempt in range(self.retries + 1):
            try:
                response = self.client.request(method, url, json=json_body)
            except httpx.TransportError as error:
                if attempt == self.retries:
                    raise PublishError(f"API transport failed after retries: {error}") from error
            else:
                if response.status_code < 500 or attempt == self.retries:
                    if response.is_error:
                        try:
                            detail = response.json().get("error", {})
                        except (ValueError, AttributeError):
                            detail = {}
                        code = detail.get("code", "HTTP_ERROR")
                        message = detail.get("message", "")
                        summary = f"API {method} {path} failed ({response.status_code})"
                        raise PublishError(f"{summary}: {code} {message}".strip())
                    return response.json()
            time.sleep(min(2**attempt, 8))
        raise PublishError("unreachable retry state")

    def put_bytes(self, url: str, payload: bytes, headers: dict[str, str]) -> str | None:
        for attempt in range(self.retries + 1):
            try:
                response = self.client.put(url, content=payload, headers=headers)
            except httpx.TransportError as error:
                if attempt == self.retries:
                    raise PublishError(f"object upload failed after retries: {error}") from error
            else:
                if response.status_code < 500 or attempt == self.retries:
                    if response.is_error:
                        raise PublishError(f"object upload failed ({response.status_code})")
                    value = response.headers.get("etag")
                    return str(value) if value is not None else None
            time.sleep(min(2**attempt, 8))
        raise PublishError("unreachable upload retry state")


def _load_manifest(path: Path, schema_root: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"cannot read Build Manifest: {error}") from error
    if not isinstance(payload, dict):
        raise PublishError("Build Manifest must be a JSON object")
    raw_version = payload.get("schema_version")
    version = raw_version if isinstance(raw_version, str) else ""
    schema_name = {
        "1.0": "build-manifest-v1.schema.json",
        "2.0": "build-manifest-v2.schema.json",
    }.get(version)
    if schema_name is None:
        raise PublishError("Build Manifest schema_version must be 1.0 or 2.0")
    validator = load_validator(str((schema_root / schema_name).resolve()))
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        validation_error = errors[0]
        location = "/" + "/".join(map(str, validation_error.absolute_path))
        raise PublishError(
            f"Build Manifest validation failed at {location}: {validation_error.message}"
        )
    return payload


def _files_by_basename(root: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            result.setdefault(path.name.casefold(), []).append(path)
    return result


def _required_artifacts(manifest: dict[str, Any], artifact_root: Path) -> list[tuple[str, Path]]:
    available = _files_by_basename(artifact_root)
    required: list[tuple[str, Path]] = []
    for module in manifest["modules"]:
        for kind, field in (("pe", "code_file"), ("pdb", "debug_file")):
            logical_name = str(module[field])
            matches = available.get(logical_name.casefold(), [])
            if len(matches) != 1:
                raise PublishError(
                    f"CI artifact {logical_name} must resolve to exactly one file; "
                    f"found {len(matches)}"
                )
            required.append((kind, matches[0]))
    source = manifest.get("source_bundle")
    if source:
        logical_name = str(source["archive"])
        matches = available.get(logical_name.casefold(), [])
        if len(matches) != 1:
            raise PublishError(
                f"source bundle {logical_name} must resolve to exactly one file; "
                f"found {len(matches)}"
            )
        required.append(("source_bundle", matches[0]))
    return required


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class Publisher:
    def __init__(self, api: ApiClient, schema_root: Path) -> None:
        self.api = api
        self.schema_root = schema_root

    def publish(
        self,
        *,
        workspace: str,
        manifest_path: Path,
        artifact_root: Path,
        producer: str,
        producer_build_id: str,
        allow_experimental: bool,
        wait_seconds: int,
    ) -> dict[str, Any]:
        manifest = _load_manifest(manifest_path, self.schema_root)
        artifacts = _required_artifacts(manifest, artifact_root)
        workspace_id = self._workspace_id(workspace)
        producer_rows = self.api.request("GET", "/ci/producers")
        producer_row = next((row for row in producer_rows if row["producer"] == producer), None)
        if producer_row is None:
            raise PublishError(f"unknown CI producer: {producer}")
        if producer_row["status"] != "supported" and not allow_experimental:
            raise PublishError(
                f"producer {producer} is {producer_row['status']}; "
                "use --allow-experimental only for qualification"
            )
        build = self.api.request(
            "POST",
            f"/workspaces/{workspace_id}/builds",
            json_body={
                "version": manifest["version"],
                "build_number": manifest.get("build_number"),
                "commit_sha": manifest.get("commit"),
                "channel": manifest.get("channel"),
                "architecture": manifest["architecture"],
                "toolchain": manifest.get("toolchain"),
                "producer": producer,
                "producer_build_id": producer_build_id,
            },
        )
        build = self.api.request("PUT", f"/builds/{build['id']}/manifest", json_body=manifest)
        uploaded: list[dict[str, str]] = []
        for kind, path in artifacts:
            digest = _sha256(path)
            existing = next(
                (
                    item
                    for item in build.get("artifacts", [])
                    if item["kind"] == kind
                    and item["logical_name"].casefold() == path.name.casefold()
                    and item["sha256"].casefold() == digest
                    and item["verification_status"] == "verified"
                ),
                None,
            )
            if existing:
                uploaded.append({"kind": kind, "path": str(path), "status": "already_verified"})
                continue
            self._upload(build["id"], kind, path, digest, wait_seconds)
            uploaded.append({"kind": kind, "path": str(path), "status": "uploaded"})
        deadline = time.monotonic() + wait_seconds
        while True:
            status = self.api.request("GET", f"/builds/{build['id']}/ci-status")
            if status["ready"]:
                break
            if status["rejected_artifacts"]:
                raise PublishError(
                    "Build verification rejected artifacts: "
                    + json.dumps(status["rejected_artifacts"])
                )
            if time.monotonic() >= deadline:
                raise PublishError("timed out waiting for complete CI Build verification")
            time.sleep(1)
        return {
            "workspace_id": workspace_id,
            "build_id": build["id"],
            "ci_status": status,
            "artifacts": uploaded,
        }

    def _workspace_id(self, value: str) -> str:
        rows = self.api.request("GET", "/workspaces")
        matches = [row for row in rows if row["id"] == value or row["name"] == value]
        if len(matches) != 1:
            raise PublishError(f"Workspace {value!r} must resolve uniquely; found {len(matches)}")
        return str(matches[0]["id"])

    def _upload(self, build_id: str, kind: str, path: Path, digest: str, wait_seconds: int) -> None:
        initialized = self.api.request(
            "POST",
            f"/builds/{build_id}/artifacts/uploads:init",
            json_body={
                "file_kind": kind,
                "filename": path.name,
                "size": path.stat().st_size,
                "sha256": digest,
            },
        )
        parts: list[dict[str, Any]] = []
        multipart = initialized.get("multipart")
        with path.open("rb") as handle:
            if multipart:
                for part in multipart["parts"]:
                    payload = handle.read(PART_SIZE)
                    etag = self.api.put_bytes(part["url"], payload, initialized["headers"])
                    if not etag:
                        raise PublishError(
                            f"multipart upload part {part['part_number']} returned no ETag"
                        )
                    parts.append({"part_number": part["part_number"], "etag": etag})
            else:
                self.api.put_bytes(initialized["url"], handle.read(), initialized["headers"])
        completion = {
            "multipart_upload_id": multipart["upload_id"] if multipart else None,
            "parts": parts,
        }
        self.api.request(
            "POST", f"/uploads/{initialized['upload_id']}/complete", json_body=completion
        )
        deadline = time.monotonic() + wait_seconds
        while True:
            upload = self.api.request("GET", f"/uploads/{initialized['upload_id']}")
            status = str(upload["verification_status"]).upper()
            if status in TERMINAL_UPLOADS:
                if status != "ACCEPTED":
                    raise PublishError(f"artifact upload ended in {status}")
                return
            if time.monotonic() >= deadline:
                raise PublishError(f"timed out waiting for upload {initialized['upload_id']}")
            time.sleep(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crashcap-ci", description="Idempotently publish one Crash-Cap CI Build"
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("CRASHCAP_API_URL"),
        required=not bool(os.environ.get("CRASHCAP_API_URL")),
    )
    parser.add_argument("--workspace", required=True, help="Workspace id or exact name")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--producer", choices=["msvc", "clang-cl", "crashpad"], default="msvc")
    parser.add_argument(
        "--producer-build-id",
        default=os.environ.get("GITHUB_RUN_ID") or os.environ.get("BUILD_BUILDID"),
        required=not bool(os.environ.get("GITHUB_RUN_ID") or os.environ.get("BUILD_BUILDID")),
    )
    parser.add_argument("--allow-experimental", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    schema_root = Path(__file__).resolve().parents[3] / "contracts"
    api = ApiClient(args.api_url)
    try:
        result = Publisher(api, schema_root).publish(
            workspace=args.workspace,
            manifest_path=args.manifest,
            artifact_root=args.artifact_root,
            producer=args.producer,
            producer_build_id=args.producer_build_id,
            allow_experimental=args.allow_experimental,
            wait_seconds=max(1, args.wait_seconds),
        )
    except PublishError as error:
        print(f"crashcap-ci: {error}", file=sys.stderr)
        return 2
    finally:
        api.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
