"""Validate one file and retain a single content-addressed copy before admission."""

from __future__ import annotations

import hashlib
from pathlib import Path

from crashcap_api.frozen_inputs import canonical_bytes, digest, normalize_identity
from crashcap_api.services.symbol_catalog import FileEvidence, LocationEvidence
from crashcap_api.storage import ObjectNotFoundError, ObjectStore, stream_sha256

from .catalog_validation import catalog_validator_version
from .core_runner import CoreExecutionError, CoreExecutor


def prepare_file(
    core: CoreExecutor,
    store: ObjectStore,
    path: Path,
    kind: str,
    expected_sha256: str,
    expected_size: int,
) -> tuple[FileEvidence, LocationEvidence]:
    validator = catalog_validator_version(core)
    report = core.identify_artifact(path, kind)
    if (report.get("kind"), report.get("sha256"), report.get("size")) != (
        kind,
        expected_sha256,
        expected_size,
    ):
        raise CoreExecutionError("FILE_IDENTITY_INVALID", "Identity does not match received bytes")
    if report.get("is_fastlink") is not False or (kind == "pdb" and not report.get("debug_id")):
        raise CoreExecutionError("FILE_IDENTITY_INVALID", "Unsupported or incomplete debug format")
    identity = normalize_identity(
        {
            **report,
            "architecture": "x86_64" if kind == "pe" else "unknown",
        }
    )
    file_id = digest(["catalog-file-v1", kind, expected_sha256])
    key = f"catalog/files/{file_id}/raw"
    try:
        found = stream_sha256(store, key)
    except ObjectNotFoundError:
        store.put_file(key, path, "application/octet-stream")
        found = stream_sha256(store, key)
    if found[:2] != (expected_sha256, expected_size):
        raise CoreExecutionError("CATALOG_PAYLOAD_INVALID", "Retained content failed readback")
    proof = canonical_bytes(
        {
            "schema_version": "file-verification-v1",
            "validator_version": validator,
            "file": report,
        }
    )
    proof_sha = hashlib.sha256(proof).hexdigest()
    proof_key = f"catalog/verification/{proof_sha}.json"
    store.put_bytes(proof_key, proof, "application/json")
    if stream_sha256(store, proof_key)[:2] != (proof_sha, len(proof)):
        raise CoreExecutionError("CATALOG_RECEIPT_INVALID", "Verification receipt failed readback")
    return (
        FileEvidence(
            kind,
            expected_sha256,
            expected_size,
            identity["code_id"],
            identity["debug_id"],
            identity["architecture"],
            validator,
            proof_key,
            proof_sha,
        ),
        LocationEvidence(
            key, "identity", expected_sha256, expected_size, "platform_owned", proof_key, proof_sha
        ),
    )
