#!/usr/bin/env python3
"""Import one licensed real-origin upstream DMP into private local RustFS.

The raw DMP is downloaded from an immutable upstream commit, verified before
use, kept only in ignored local evidence, and uploaded with SSE-S3. Generated
evidence contains provenance, hashes and sanitized inspection facts, never the
dump bytes or credentials.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from qualification.s3.adapter import S3Adapter, http_request, stream_sha256


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM_COMMIT = "4bc091396bdb88a6810ecb3746edd0f97d949e67"
UPSTREAM_REPOSITORY = "https://github.com/rust-minidump/rust-minidump"
UPSTREAM_PATH = "testdata/invalid-parameter.dmp"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/rust-minidump/rust-minidump/"
    f"{UPSTREAM_COMMIT}/{UPSTREAM_PATH}"
)
UPSTREAM_README = (
    "https://github.com/rust-minidump/rust-minidump/blob/"
    f"{UPSTREAM_COMMIT}/testdata/README.md"
)
LICENSE_URL = (
    "https://github.com/rust-minidump/rust-minidump/blob/"
    f"{UPSTREAM_COMMIT}/LICENSE"
)
EXPECTED_SHA256 = "5edaec6b6d8e360c8f26c5907d3ccb29d79cfd4c66d617b23005a2f1396aff9b"
EXPECTED_SIZE = 44_629
BUCKET = "crash-cap-authorized-fixtures"
KEY = f"golden/rust-minidump/{UPSTREAM_COMMIT}/invalid-parameter.dmp"
FIXTURE_ROOT = ROOT / "fixtures" / "p0-d07-upstream-invalid-parameter"
LOCAL_DUMP = (
    FIXTURE_ROOT / "generated" / "invalid-parameter.dmp"
)
EVIDENCE_JSON = ROOT / "docs" / "evidence" / "authorized-real-sample.json"
EVIDENCE_MD = ROOT / "docs" / "evidence" / "authorized-real-sample.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def download_verified() -> Path:
    LOCAL_DUMP.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="invalid-parameter.", suffix=".dmp", dir=LOCAL_DUMP.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        request = urllib.request.Request(
            UPSTREAM_URL, headers={"User-Agent": "crash-cap-phase0-fixture/1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            while chunk := response.read(64 * 1024):
                temporary.write(chunk)
    try:
        digest, size = sha256_file(temporary_path)
        if digest != EXPECTED_SHA256 or size != EXPECTED_SIZE:
            raise RuntimeError(
                f"upstream sample identity mismatch: sha256={digest}, size={size}"
            )
        with temporary_path.open("rb") as source:
            if source.read(4) != b"MDMP":
                raise RuntimeError("verified download has no MDMP signature")
        os.replace(temporary_path, LOCAL_DUMP)
    finally:
        temporary_path.unlink(missing_ok=True)
    return LOCAL_DUMP


def wait_for_s3(adapter: S3Adapter) -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            adapter.client.list_buckets()
            return
        except Exception as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("private RustFS did not become ready") from error
            time.sleep(1)


def ensure_bucket(adapter: S3Adapter) -> None:
    try:
        adapter.create_bucket(BUCKET)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise
    adapter.put_bucket_encryption(bucket=BUCKET, algorithm="AES256")


def find_core() -> Path:
    candidates = [
        ROOT / "target" / "release" / "dmp-core.exe",
        ROOT / "target" / "release" / "dmp-core",
        ROOT / "target" / "debug" / "dmp-core.exe",
        ROOT / "target" / "debug" / "dmp-core",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("dmp-core executable is required for the sanitized provenance summary")


def sanitized_inspection(dump: Path) -> dict[str, Any]:
    core = find_core()
    with tempfile.TemporaryDirectory(prefix="crash-cap-authorized-inspect-") as directory:
        output = Path(directory) / "inspect.json"
        completed = subprocess.run(
            [str(core), "inspect", "--dump", str(dump), "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if completed.returncode:
            raise RuntimeError(f"dmp-core inspect rejected authorized sample: exit {completed.returncode}")
        report = json.loads(output.read_text(encoding="utf-8"))
    module_paths = [str(module.get("code_file", "")) for module in report.get("modules", [])]
    suspicious = [
        path
        for path in module_paths
        if "\\users\\" in path.lower()
        or "\\documents\\" in path.lower()
        or "\\appdata\\" in path.lower()
    ]
    exception = report.get("exception") or {}
    return {
        "architecture": report.get("process", {}).get("architecture"),
        "os": report.get("process", {}).get("os"),
        "os_version": report.get("process", {}).get("os_version"),
        "exception_code": exception.get("code"),
        "exception_name": exception.get("name"),
        "crash_thread_id": report.get("crash_thread_id"),
        "thread_count": len(report.get("threads", [])),
        "module_count": len(module_paths),
        "module_basenames": sorted({Path(path.replace("\\", "/")).name for path in module_paths}),
        "user_specific_module_paths_detected": bool(suspicious),
    }


def render_markdown(evidence: dict[str, Any]) -> str:
    inspection = evidence["sanitized_inspection"]
    storage = evidence["private_storage"]
    return "\n".join(
        [
            "# Authorized real-origin Golden sample",
            "",
            f"- Imported: `{evidence['imported_at_utc']}`",
            f"- Upstream commit: `{UPSTREAM_COMMIT}`",
            f"- SHA-256: `{EXPECTED_SHA256}`",
            f"- Size: `{EXPECTED_SIZE}` bytes",
            "- License: MIT (upstream repository license at the pinned commit)",
            "- Provenance: upstream testdata README describes these non-pipeline dumps as artifacts generated by contributors on their machines.",
            f"- Private object: `{storage['uri']}`",
            f"- Anonymous GET status: `{storage['anonymous_get_status']}`",
            f"- SSE: `{storage['server_side_encryption']}`",
            "",
            "## Sanitized inspection",
            "",
            f"- Platform: `{inspection['os']} / {inspection['architecture']}`",
            f"- Exception: `{inspection['exception_code']}`",
            f"- Crash thread: `{inspection['crash_thread_id']}`",
            f"- Threads/modules: `{inspection['thread_count']} / {inspection['module_count']}`",
            f"- User-specific module paths detected: `{inspection['user_specific_module_paths_detected']}`",
            "",
            "The raw dump is excluded by `fixtures/.gitignore`. The committed record contains only provenance, hashes, object-store verification and sanitized derived facts. This is a public upstream real-origin test artifact, not a claim that it is a Crash-Cap production incident.",
            "",
        ]
    )


def write_fixture_runtime_evidence(evidence: dict[str, Any]) -> None:
    """Write ignored, reproducible runtime records consumed by the Golden harness."""
    generated = FIXTURE_ROOT / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    inspection = evidence["sanitized_inspection"]
    storage = evidence["private_storage"]
    generated_at = evidence["imported_at_utc"]
    manifest = {
        "schema_version": "fixture-artifact-manifest-v0.2",
        "fixture_id": FIXTURE_ROOT.name,
        "generated_at_utc": generated_at,
        "generator": {
            "script": "scripts/authorized_samples/import_rust_minidump.py",
            "source_repository": UPSTREAM_REPOSITORY,
            "source_commit": UPSTREAM_COMMIT,
            "license": "MIT",
            "process_model": "upstream contributor generated; Crash-Cap did not capture this dump",
        },
        "target": {
            "architecture": inspection["architecture"],
            "module": "CrashTest.exe",
            "artifacts_available": False,
            "identity_source": "dump module list only; no matching upstream PE/PDB is supplied",
        },
        "dump": {
            "path": "generated/invalid-parameter.dmp",
            "sha256": EXPECTED_SHA256,
            "size": EXPECTED_SIZE,
            "object_uri": storage["uri"],
            "validation": "generated/validation.json",
            "no_exception": False,
            "treatment": "authorized_real_no_local_artifacts",
        },
    }
    validation = {
        "schema_version": "fixture-validation-v0.2",
        "fixture_id": FIXTURE_ROOT.name,
        "status": "verified_local",
        "validated_at_utc": generated_at,
        "dump": {
            "sha256": EXPECTED_SHA256,
            "size": EXPECTED_SIZE,
            "magic_ascii": storage["range_0_3"],
            "private_object_sha256": storage["stream_sha256"],
        },
        "artifacts": {"pe_present": False, "pdb_present": False},
        "private_storage": {
            "uri": storage["uri"],
            "anonymous_get_status": storage["anonymous_get_status"],
            "server_side_encryption": storage["server_side_encryption"],
        },
    }
    verifier = {
        "schema_version": "fixture-verifier-result-v0.2",
        "fixture_id": FIXTURE_ROOT.name,
        "result": {
            "valid_dump": True,
            "has_exception": True,
            "architecture": inspection["architecture"],
            "exception": {"code": inspection["exception_code"]},
            "crash_thread_id": inspection["crash_thread_id"],
            "thread_count": inspection["thread_count"],
            "module_count": inspection["module_count"],
        },
    }
    for name, payload in (
        ("manifest.json", manifest),
        ("validation.json", validation),
        ("verifier-result.json", verifier),
    ):
        (generated / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> int:
    endpoint = os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9002").rstrip("/")
    access_key = os.environ.get("RUSTFS_ACCESS_KEY", "")
    secret_key = os.environ.get("RUSTFS_SECRET_KEY", "")
    if not access_key or not secret_key:
        raise SystemExit("RUSTFS_ACCESS_KEY and RUSTFS_SECRET_KEY are required")

    dump = download_verified()
    local_digest, local_size = sha256_file(dump)
    adapter = S3Adapter(
        endpoint_url=endpoint, access_key=access_key, secret_key=secret_key
    )
    wait_for_s3(adapter)
    ensure_bucket(adapter)
    with dump.open("rb") as body:
        adapter.put_object(
            bucket=BUCKET,
            key=KEY,
            body=body,
            ServerSideEncryption="AES256",
            Metadata={
                "sha256": EXPECTED_SHA256,
                "upstream-commit": UPSTREAM_COMMIT,
                "license": "MIT",
            },
        )
    head = adapter.head_object(bucket=BUCKET, key=KEY)
    streamed = adapter.get_object(bucket=BUCKET, key=KEY)
    object_digest, object_size, max_chunk = stream_sha256(streamed["Body"])
    ranged = adapter.get_object(bucket=BUCKET, key=KEY, Range="bytes=0-3")["Body"].read()
    anonymous = http_request(f"{endpoint}/{BUCKET}/{KEY}", method="GET")
    if object_digest != EXPECTED_SHA256 or object_size != EXPECTED_SIZE:
        raise RuntimeError("private object digest/size does not match the pinned source")
    if ranged != b"MDMP":
        raise RuntimeError("private object Range GET did not return MDMP")
    if anonymous.status not in {401, 403, 404}:
        raise RuntimeError(f"private object anonymous GET unexpectedly returned {anonymous.status}")

    evidence = {
        "schema_version": "authorized-real-sample-v0.1",
        "imported_at_utc": utc_now(),
        "classification": "public-upstream-real-origin-test-artifact",
        "not_claimed_as": "Crash-Cap production incident",
        "source": {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
            "path": UPSTREAM_PATH,
            "download_url": UPSTREAM_URL,
            "testdata_readme": UPSTREAM_README,
            "license": "MIT",
            "license_url": LICENSE_URL,
            "sha256": local_digest,
            "size": local_size,
        },
        "private_storage": {
            "uri": f"s3://{BUCKET}/{KEY}",
            "endpoint_scope": "loopback-only local RustFS",
            "bucket": BUCKET,
            "key": KEY,
            "content_length": head.get("ContentLength"),
            "metadata_sha256": head.get("Metadata", {}).get("sha256"),
            "server_side_encryption": head.get("ServerSideEncryption"),
            "stream_sha256": object_digest,
            "streamed_bytes": object_size,
            "maximum_hash_chunk_bytes": max_chunk,
            "range_0_3": ranged.decode("ascii"),
            "anonymous_get_status": anonymous.status,
        },
        "sanitized_inspection": sanitized_inspection(dump),
        "repository_binary_policy": {
            "raw_dump_ignored": True,
            "local_generated_path": str(dump.relative_to(ROOT)).replace("\\", "/"),
            "committed_binary": False,
        },
    }
    EVIDENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_JSON.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    EVIDENCE_MD.write_text(render_markdown(evidence), encoding="utf-8")
    write_fixture_runtime_evidence(evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
