from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PublisherServerState:
    address: str = ""
    inventory: list[dict[str, Any]] = field(default_factory=list)
    publications: dict[tuple[str, str], str] = field(default_factory=dict)
    accepted: set[tuple[str, str]] = field(default_factory=set)
    uploads: dict[str, tuple[str, str]] = field(default_factory=dict)
    multipart_uploads: dict[str, int] = field(default_factory=dict)
    multipart_payloads: dict[str, dict[int, bytes]] = field(default_factory=dict)
    fail_first_pdb_part: bool = True
    pdb_failure_consumed: bool = False
    put_count: int = 0
    registration_count: int = 0
    client_versions: set[str] = field(default_factory=set)

    def summary(self, body: dict[str, Any], publication_id: str) -> dict[str, Any]:
        return {
            "id": publication_id,
            "workspace_id": "wsp_native_e2e",
            "build_id": "bld_shared_content",
            "origin": body["origin"],
            "client_publication_id": body["client_publication_id"],
            "client_version": body["client_version"],
            "git_revision": body["git"]["revision"],
            "git_worktree_state": body["git"]["worktree_state"],
            "created_at": "2026-08-25T00:00:00+00:00",
            "last_seen_at": "2026-08-25T00:00:00+00:00",
        }

    def response(self, body: dict[str, Any], publication_id: str) -> dict[str, Any]:
        expectations = []
        for item in self.inventory:
            key = (item["kind"], item["logical_name"].casefold())
            verified = key in self.accepted
            expectations.append(
                {
                    "module_id": "mod_native_e2e",
                    "module_code_file": item["module_code_file"],
                    "kind": item["kind"],
                    "logical_name": item["logical_name"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "status": "verified" if verified else "missing",
                    "artifact_id": f"art_{item['kind']}" if verified else None,
                    "upload_id": None,
                    "rejection_reason": None,
                }
            )
        ready = bool(expectations) and all(item["status"] == "verified" for item in expectations)
        summaries = [
            self.summary(
                {
                    **body,
                    "origin": origin,
                    "client_publication_id": client_id,
                },
                pub_id,
            )
            for (origin, client_id), pub_id in self.publications.items()
        ]
        return {
            "publication": self.summary(body, publication_id),
            "publications": summaries,
            "build_id": "bld_shared_content",
            "identity_mode": "content_v1",
            "fingerprint_version": "build-content-v1",
            "content_fingerprint": "f" * 64,
            "status": "ready" if ready else "registered",
            "sealed_at": "2026-08-25T00:01:00+00:00" if ready else None,
            "expected_artifacts": expectations,
            "missing_artifacts": [item for item in expectations if item["status"] != "verified"],
            "rejected_artifacts": [],
            "ready": ready,
        }


class PublisherHTTPServer(ThreadingHTTPServer):
    publisher_state: PublisherServerState


class PublisherHandler(BaseHTTPRequestHandler):
    server: PublisherHTTPServer

    def log_message(self, _format: str, *args: object) -> None:
        del args

    @property
    def state(self) -> PublisherServerState:
        return self.server.publisher_state

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces":
            self.send_json(200, [{"id": "wsp_native_e2e", "name": "native-e2e"}])
            return
        if self.path == "/api/v1/artifact-producers":
            self.send_json(
                200,
                [
                    {
                        "producer": "msvc",
                        "status": "supported",
                        "publication_contracts": ["1.0"],
                        "minimum_client_version": "1.0.0",
                        "build_publications_enabled": True,
                    }
                ],
            )
            return
        if self.path.startswith("/api/v1/uploads/"):
            upload_id = self.path.rsplit("/", 1)[-1]
            status = (
                "ACCEPTED" if self.state.uploads[upload_id] in self.state.accepted else "REJECTED"
            )
            self.send_json(
                200,
                {
                    "upload_id": upload_id,
                    "status": status,
                    "verification_status": status,
                    "rejection_reason": None,
                },
            )
            return
        if self.path.startswith("/api/v1/build-publications/"):
            publication_id = self.path.rsplit("/", 1)[-1]
            key = next(
                key for key, value in self.state.publications.items() if value == publication_id
            )
            body = {
                "origin": key[0],
                "client_publication_id": key[1],
                "client_version": "crashcap/1.0.0",
                "git": {"revision": None, "worktree_state": "unknown"},
            }
            self.send_json(200, self.state.response(body, publication_id))
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces/wsp_native_e2e/build-publications":
            body = self.read_json()
            self.state.registration_count += 1
            self.state.client_versions.add(str(body["client_version"]))
            if not self.state.inventory:
                self.state.inventory = body["artifacts"]
            else:
                assert body["artifacts"] == self.state.inventory
            key = (body["origin"], body["client_publication_id"])
            publication_id = self.state.publications.setdefault(
                key, f"pub_{body['origin']}_native_e2e"
            )
            self.send_json(201, self.state.response(body, publication_id))
            return
        if self.path == "/api/v1/builds/bld_shared_content/artifacts/uploads:init":
            body = self.read_json()
            expected = next(
                item
                for item in self.state.inventory
                if item["kind"] == body["file_kind"]
                and item["logical_name"].casefold() == body["filename"].casefold()
            )
            assert body["size"] == expected["size"]
            assert body["sha256"] == expected["sha256"]
            upload_id = f"upl_{body['file_kind']}_{len(self.state.uploads)}"
            self.state.uploads[upload_id] = (body["file_kind"], body["filename"].casefold())
            multipart = None
            url = f"http://{self.state.address}/objects/{upload_id}"
            if body["file_kind"] == "pdb":
                part_size = max(1, (body["size"] + 1) // 2)
                part_count = (body["size"] + part_size - 1) // part_size
                self.state.multipart_uploads[upload_id] = part_size
                self.state.multipart_payloads[upload_id] = {}
                multipart = {
                    "upload_id": f"s3-{upload_id}",
                    "part_size": part_size,
                    "parts": [
                        {
                            "part_number": number,
                            "url": f"http://{self.state.address}/objects/{upload_id}/parts/{number}",
                        }
                        for number in range(1, part_count + 1)
                    ],
                }
                url = ""
            self.send_json(
                201,
                {
                    "upload_id": upload_id,
                    "method": "PUT",
                    "url": url,
                    "headers": {"Content-Type": "application/octet-stream"},
                    "expires_in": 900,
                    "multipart": multipart,
                },
            )
            return
        if self.path.startswith("/api/v1/uploads/") and self.path.endswith("/complete"):
            body = self.read_json()
            upload_id = self.path.split("/")[-2]
            kind, logical_name = self.state.uploads[upload_id]
            if upload_id in self.state.multipart_uploads:
                assert body["multipart_upload_id"] == f"s3-{upload_id}"
                part_numbers = [item["part_number"] for item in body["parts"]]
                assert part_numbers == list(range(1, len(part_numbers) + 1))
                payload = b"".join(
                    self.state.multipart_payloads[upload_id][number] for number in part_numbers
                )
                expected = next(
                    item
                    for item in self.state.inventory
                    if (item["kind"], item["logical_name"].casefold()) == (kind, logical_name)
                )
                assert len(payload) == expected["size"]
                assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
            self.state.accepted.add((kind, logical_name))
            self.send_json(
                200,
                {
                    "upload_id": upload_id,
                    "status": "VERIFYING",
                    "verification_status": "VERIFYING",
                    "rejection_reason": None,
                },
            )
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_PUT(self) -> None:  # noqa: N802
        segments = self.path.strip("/").split("/")
        upload_id = segments[1]
        part_number = int(segments[3]) if len(segments) == 4 else None
        expected = next(
            item
            for item in self.state.inventory
            if (item["kind"], item["logical_name"].casefold()) == self.state.uploads[upload_id]
        )
        remaining = int(self.headers["Content-Length"])
        digest = hashlib.sha256()
        payload = bytearray()
        total = 0
        while remaining:
            chunk = self.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            if part_number is not None:
                payload.extend(chunk)
            total += len(chunk)
            remaining -= len(chunk)
        if part_number is not None:
            part_size = self.state.multipart_uploads[upload_id]
            offset = (part_number - 1) * part_size
            assert total == min(part_size, expected["size"] - offset)
            if (
                expected["kind"] == "pdb"
                and self.state.fail_first_pdb_part
                and not self.state.pdb_failure_consumed
            ):
                self.state.pdb_failure_consumed = True
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.state.multipart_payloads[upload_id][part_number] = bytes(payload)
        else:
            assert total == expected["size"]
            assert digest.hexdigest() == expected["sha256"]
        self.state.put_count += 1
        self.send_response(200)
        self.send_header("ETag", f'"{upload_id}"')
        self.send_header("Content-Length", "0")
        self.end_headers()


def _publisher_binary() -> Path:
    if os.name == "nt":
        return ROOT / "tools" / "crashcap" / "windows-x86_64" / "crashcap.exe"
    return ROOT / "tools" / "crashcap" / "linux-x86_64" / "crashcap"


def test_checked_in_native_cli_publishes_replays_and_keeps_receipt_safe(tmp_path: Path) -> None:
    fixture_root = ROOT / "fixtures" / ".build" / "golden"
    code_fixture = fixture_root / "golden_target_release.exe"
    debug_fixture = fixture_root / "golden_target_release.pdb"
    if not code_fixture.is_file() or not debug_fixture.is_file():
        pytest.skip("build the Phase 0 native fixtures before the native publisher E2E gate")

    output = tmp_path / "out"
    output.mkdir()
    shutil.copy2(code_fixture, output / code_fixture.name)
    shutil.copy2(debug_fixture, output / debug_fixture.name)
    for arguments in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "native-e2e@crash-cap.invalid"],
        ["git", "config", "user.name", "Crash-Cap Native E2E"],
        ["git", "add", "out"],
        ["git", "commit", "--quiet", "-m", "native fixtures"],
    ):
        completed = subprocess.run(  # noqa: S603,S607 - isolated disposable Git repository
            arguments,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
    config = tmp_path / "crashcap.toml"
    state = PublisherServerState()
    server = PublisherHTTPServer(("127.0.0.1", 0), PublisherHandler)
    state.address = f"127.0.0.1:{server.server_port}"
    server.publisher_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt = tmp_path / "crashcap-publication.json"

    initialized = subprocess.run(  # noqa: S603 - runs the checked-in native gate binary
        [
            str(_publisher_binary()),
            "--api-url",
            f"http://{state.address}/api/v1",
            "--config",
            str(config),
            "--json",
            "init",
            "--workspace",
            "native-e2e",
            "--artifact-root",
            "out",
            "--profile",
            "release",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["module_count"] == 1
    assert config.is_file()

    def publish(
        origin: str, *, succeeds: bool = True
    ) -> dict[str, Any] | subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # noqa: S603 - runs the checked-in native gate binary
            [
                str(_publisher_binary()),
                "--api-url",
                f"http://{state.address}/api/v1",
                "--config",
                str(config),
                "--json",
                "publish",
                "--profile",
                "release",
                "--origin",
                origin,
                "--wait-seconds",
                "10",
                "--receipt",
                str(receipt),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if succeeds:
            assert completed.returncode == 0, completed.stderr
            return json.loads(completed.stdout)
        assert completed.returncode == 2
        assert "object upload part 1 failed (403)" in completed.stderr
        return completed

    try:
        publish("local", succeeds=False)
        assert len([key for key in state.publications if key[0] == "local"]) == 1
        first = publish("local")
        first_put_count = state.put_count
        replay = publish("local")
        ci = publish("ci")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert first["ready"] is replay["ready"] is ci["ready"] is True
    assert first["build_id"] == replay["build_id"] == ci["build_id"]
    assert first["publication"]["id"] == replay["publication"]["id"]
    assert first["publication"]["id"] != ci["publication"]["id"]
    assert first_put_count == 3  # one PE plus two successful PDB parts after interruption
    assert state.put_count == first_put_count
    assert state.registration_count == 4
    assert state.client_versions == {"crashcap/1.1.0"}
    assert len([key for key in state.publications if key[0] == "local"]) == 1

    receipt_text = receipt.read_text(encoding="utf-8")
    receipt_payload = json.loads(receipt_text)
    assert receipt_payload["git"]["worktree_state"] == "dirty"
    assert receipt_payload["warnings"] == ["git_worktree_dirty"]
    assert str(tmp_path) not in receipt_text
    assert "http://" not in receipt_text
    assert "presigned" not in receipt_text.casefold()
    assert "credential" not in receipt_text.casefold()


@dataclass
class DeliveryRaceState:
    address: str = ""
    lock: Any = field(default_factory=threading.RLock)
    publications: dict[str, tuple[dict[str, Any], str]] = field(default_factory=dict)
    inventories: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bindings: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)
    blobs: dict[str, str] = field(default_factory=dict)
    claims: dict[str, str] = field(default_factory=dict)
    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)
    payloads: dict[str, bytes] = field(default_factory=dict)
    wait_seen: dict[str, threading.Event] = field(default_factory=dict)
    dispositions: dict[str, list[str]] = field(default_factory=dict)

    def publication_response(self, publication_id: str) -> dict[str, Any]:
        body, build_id = self.publications[publication_id]
        expectations: list[dict[str, Any]] = []
        for index, item in enumerate(self.inventories[build_id]):
            key = (build_id, item["kind"], item["logical_name"].casefold())
            binding = self.bindings.get(key)
            expectations.append(
                {
                    "module_id": f"mod_{build_id}",
                    "module_code_file": item["module_code_file"],
                    "kind": item["kind"],
                    "logical_name": item["logical_name"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "status": "verified" if binding else "missing",
                    "artifact_id": f"art_{build_id}_{index}" if binding else None,
                    "artifact_blob_id": binding[0] if binding else None,
                    "delivery": binding[1] if binding else None,
                    "upload_id": None,
                    "rejection_reason": None,
                }
            )
        ready = bool(expectations) and all(row["status"] == "verified" for row in expectations)
        summary = {
            "id": publication_id,
            "workspace_id": "wsp_native_race",
            "build_id": build_id,
            "origin": body["origin"],
            "client_publication_id": body["client_publication_id"],
            "client_version": body["client_version"],
            "git_revision": body["git"]["revision"],
            "git_worktree_state": body["git"]["worktree_state"],
            "created_at": "2026-08-25T00:00:00+00:00",
            "last_seen_at": "2026-08-25T00:00:00+00:00",
        }
        return {
            "publication": summary,
            "publications": [summary],
            "build_id": build_id,
            "identity_mode": "content_v1",
            "fingerprint_version": "build-content-v1",
            "content_fingerprint": hashlib.sha256(build_id.encode()).hexdigest(),
            "status": "ready" if ready else "registered",
            "sealed_at": "2026-08-25T00:01:00+00:00" if ready else None,
            "expected_artifacts": expectations,
            "missing_artifacts": [row for row in expectations if row["status"] != "verified"],
            "rejected_artifacts": [],
            "ready": ready,
        }


class DeliveryRaceHTTPServer(ThreadingHTTPServer):
    delivery_state: DeliveryRaceState


class DeliveryRaceHandler(BaseHTTPRequestHandler):
    server: DeliveryRaceHTTPServer

    def log_message(self, _format: str, *args: object) -> None:
        del args

    @property
    def state(self) -> DeliveryRaceState:
        return self.server.delivery_state

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces":
            self.send_json(200, [{"id": "wsp_native_race", "name": "native-race"}])
            return
        if self.path == "/api/v1/artifact-producers":
            self.send_json(
                200,
                [
                    {
                        "producer": "msvc",
                        "status": "supported",
                        "publication_contracts": ["1.0"],
                        "minimum_client_version": "1.1.0",
                        "build_publications_enabled": True,
                        "artifact_delivery_contracts": ["artifact-delivery-v1"],
                    }
                ],
            )
            return
        if self.path.startswith("/api/v1/build-publications/"):
            publication_id = self.path.rsplit("/", 1)[-1]
            with self.state.lock:
                self.send_json(200, self.state.publication_response(publication_id))
            return
        if self.path.startswith("/api/v1/uploads/"):
            upload_id = self.path.rsplit("/", 1)[-1]
            with self.state.lock:
                upload = self.state.uploads[upload_id]
                accepted = bool(upload.get("accepted"))
                self.send_json(
                    200,
                    {
                        "upload_id": upload_id,
                        "status": "ACCEPTED" if accepted else "VERIFYING",
                        "verification_status": "ACCEPTED" if accepted else "VERIFYING",
                        "artifact_blob_id": upload.get("artifact_blob_id"),
                        "delivery": "uploaded" if accepted else None,
                    },
                )
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces/wsp_native_race/build-publications":
            body = self.read_json()
            version = str(body["manifest"]["version"])
            suffix = "a" if version == "race-a" else "b"
            build_id = f"bld_native_race_{suffix}"
            publication_id = f"pub_native_race_{suffix}"
            with self.state.lock:
                self.state.publications[publication_id] = (body, build_id)
                self.state.inventories[build_id] = body["artifacts"]
                response = self.state.publication_response(publication_id)
            self.send_json(201, response)
            return
        if self.path.endswith("/artifacts/deliveries:init"):
            body = self.read_json()
            build_id = self.path.split("/")[4]
            sha256 = str(body["sha256"])
            binding_key = (build_id, body["file_kind"], body["filename"].casefold())
            with self.state.lock:
                blob_id = self.state.blobs.get(sha256)
                if blob_id is not None:
                    self.state.bindings[binding_key] = (blob_id, "reused")
                    self.state.dispositions.setdefault(sha256, []).append("reused")
                    self.send_json(
                        201,
                        {
                            "disposition": "reused",
                            "artifact_blob_id": blob_id,
                            "artifact_id": f"art_{build_id}_{body['file_kind']}",
                            "delivery": "reused",
                        },
                    )
                    return
                owner = self.state.claims.get(sha256)
                if owner is not None:
                    self.state.dispositions.setdefault(sha256, []).append("wait")
                    self.state.wait_seen[sha256].set()
                    self.send_json(
                        201,
                        {
                            "disposition": "wait",
                            "retry_after_seconds": 1,
                            "lease_expires_at": "2099-01-01T00:00:00+00:00",
                        },
                    )
                    return
                upload_id = f"upl_native_race_{len(self.state.uploads)}"
                self.state.claims[sha256] = upload_id
                self.state.wait_seen[sha256] = threading.Event()
                self.state.dispositions.setdefault(sha256, []).append("upload")
                self.state.uploads[upload_id] = {
                    "build_id": build_id,
                    "kind": body["file_kind"],
                    "filename": body["filename"],
                    "sha256": sha256,
                    "size": body["size"],
                }
            self.send_json(
                201,
                {
                    "disposition": "upload",
                    "upload_id": upload_id,
                    "method": "PUT",
                    "url": f"http://{self.state.address}/objects/{upload_id}",
                    "headers": {"Content-Type": "application/octet-stream"},
                    "expires_in": 900,
                },
            )
            return
        if self.path.startswith("/api/v1/uploads/") and self.path.endswith("/complete"):
            self.read_json()
            upload_id = self.path.split("/")[-2]
            with self.state.lock:
                upload = self.state.uploads[upload_id]
                payload = self.state.payloads[upload_id]
                assert len(payload) == upload["size"]
                assert hashlib.sha256(payload).hexdigest() == upload["sha256"]
                blob_id = f"abl_{upload['sha256'][:26].upper()}"
                self.state.blobs[upload["sha256"]] = blob_id
                for candidate_build, inventory in self.state.inventories.items():
                    for item in inventory:
                        if item["sha256"] == upload["sha256"]:
                            key = (
                                candidate_build,
                                item["kind"],
                                item["logical_name"].casefold(),
                            )
                            delivery = (
                                "uploaded" if candidate_build == upload["build_id"] else "reused"
                            )
                            self.state.bindings[key] = (blob_id, delivery)
                upload["artifact_blob_id"] = blob_id
                upload["accepted"] = True
                self.state.claims.pop(upload["sha256"], None)
            self.send_json(
                200,
                {
                    "upload_id": upload_id,
                    "status": "VERIFYING",
                    "verification_status": "VERIFYING",
                },
            )
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_PUT(self) -> None:  # noqa: N802
        upload_id = self.path.rsplit("/", 1)[-1]
        length = int(self.headers["Content-Length"])
        payload = self.rfile.read(length)
        with self.state.lock:
            upload = self.state.uploads[upload_id]
            event = self.state.wait_seen[upload["sha256"]]
            self.state.payloads[upload_id] = payload
        # Deterministically keep the first uploader in flight until the other
        # native process has observed the exact Workspace+SHA wait disposition.
        assert event.wait(timeout=10), "second native client never observed wait"
        self.send_response(200)
        self.send_header("ETag", f'"{upload_id}"')
        self.send_header("Content-Length", "0")
        self.end_headers()


def _write_race_profile(root: Path, version: str, code: Path, debug: Path) -> Path:
    output = root / "out"
    output.mkdir(parents=True)
    shutil.copy2(code, output / code.name)
    shutil.copy2(debug, output / debug.name)
    config = root / "crashcap.toml"
    config.write_text(
        "\n".join(
            [
                "schema_version = 1",
                'workspace = "native-race"',
                'product = "native-race"',
                "",
                "[profiles.release]",
                'artifact_roots = ["out"]',
                f'version = {{ source = "literal", value = "{version}" }}',
                'channel = "local"',
                "require_clean = false",
                "",
                "[[profiles.release.modules]]",
                f'code = "{code.name}"',
                f'debug = "{debug.name}"',
                'role = "entrypoint"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def test_two_native_delivery_v1_clients_race_one_upload_one_wait_and_share_blobs(
    tmp_path: Path,
) -> None:
    fixture_root = ROOT / "fixtures" / ".build" / "golden"
    code_fixture = fixture_root / "golden_target_release.exe"
    debug_fixture = fixture_root / "golden_target_release.pdb"
    if not code_fixture.is_file() or not debug_fixture.is_file():
        pytest.skip("build the Phase 0 native fixtures before the native delivery race gate")

    roots = [tmp_path / "client-a", tmp_path / "client-b"]
    configs = [
        _write_race_profile(roots[0], "race-a", code_fixture, debug_fixture),
        _write_race_profile(roots[1], "race-b", code_fixture, debug_fixture),
    ]
    receipts = [root / "receipt.json" for root in roots]
    state = DeliveryRaceState()
    server = DeliveryRaceHTTPServer(("127.0.0.1", 0), DeliveryRaceHandler)
    state.address = f"127.0.0.1:{server.server_port}"
    server.delivery_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    processes = []
    for root, config, receipt in zip(roots, configs, receipts, strict=True):
        processes.append(
            subprocess.Popen(  # noqa: S603 - checked-in native gate binary
                [
                    str(_publisher_binary()),
                    "--api-url",
                    f"http://{state.address}/api/v1",
                    "--config",
                    str(config),
                    "--json",
                    "publish",
                    "--profile",
                    "release",
                    "--origin",
                    "local",
                    "--wait-seconds",
                    "20",
                    "--receipt",
                    str(receipt),
                ],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
        )
    completed = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            completed.append((process.returncode, stdout, stderr))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert all(code == 0 for code, _stdout, _stderr in completed), completed
    outputs = [json.loads(stdout) for _code, stdout, _stderr in completed]
    assert {row["build_id"] for row in outputs} == {"bld_native_race_a", "bld_native_race_b"}
    assert all(row["ready"] is True for row in outputs)
    with state.lock:
        assert len(state.blobs) == 2
        for sha256, history in state.dispositions.items():
            assert history.count("upload") == 1, (sha256, history)
            assert history.count("wait") >= 1, (sha256, history)
        for sha256, blob_id in state.blobs.items():
            matching = [
                binding
                for key, binding in state.bindings.items()
                if next(
                    item["sha256"]
                    for item in state.inventories[key[0]]
                    if item["kind"] == key[1] and item["logical_name"].casefold() == key[2]
                )
                == sha256
            ]
            assert len(matching) == 2
            assert {binding[0] for binding in matching} == {blob_id}

    receipt_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in receipts]
    for receipt in receipt_payloads:
        assert {row["delivery"] for row in receipt["artifacts"]} <= {"uploaded", "reused"}
        assert all(str(row["artifact_blob_id"]).startswith("abl_") for row in receipt["artifacts"])
        rendered = json.dumps(receipt)
        assert "http://" not in rendered
        assert "object_key" not in rendered
