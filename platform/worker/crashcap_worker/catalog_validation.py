"""Prepare verified, retained catalog input before entering a DB transaction."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from crashcap_api.frozen_inputs import canonical_bytes, normalize_identity
from crashcap_api.ids import new_ulid
from crashcap_api.services.artifact_payloads import ArtifactBlobCodec
from crashcap_api.services.symbol_catalog import FileEvidence, LocationEvidence
from crashcap_api.storage import ObjectStore, stream_sha256

from .core_runner import CoreExecutionError, CoreExecutor


@dataclass(frozen=True)
class PreparedCatalogPair:
    pe: FileEvidence
    pdb: FileEvidence
    locations: dict[str, tuple[LocationEvidence, ...]]


def _hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _copy(source: Path, destination: Path, limit: int) -> None:
    if not source.is_file() or source.stat().st_size > limit:
        raise CoreExecutionError("CATALOG_FILE_LIMIT", "Pair input is not a bounded regular file")
    total = 0
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        while block := incoming.read(1024 * 1024):
            total += len(block)
            if total > limit:
                raise CoreExecutionError("CATALOG_FILE_LIMIT", "Pair input grew beyond its limit")
            outgoing.write(block)


def _inspect_staged(
    core: CoreExecutor, paths: dict[str, Path]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    reports = {kind: core.identify_artifact(path, kind) for kind, path in paths.items()}
    for kind, report in reports.items():
        if (
            report.get("kind") != kind
            or report.get("sha256") != _hash(paths[kind])
            or report.get("size") != paths[kind].stat().st_size
            or not isinstance(report.get("is_fastlink"), bool)
        ):
            raise CoreExecutionError(
                "CATALOG_VALIDATION_OUTPUT_MISMATCH", "Validator output does not prove staged bytes"
            )
        if report["is_fastlink"] is not False or not report.get("debug_id"):
            raise CoreExecutionError(
                "CATALOG_PAIR_INVALID", "Actual pair bytes or identities are invalid"
            )
    identities = {
        kind: normalize_identity(
            {**report, "architecture": "x86_64" if kind == "pe" else "unknown"}
        )
        for kind, report in reports.items()
    }
    if (
        identities["pe"]["code_id"] is None
        or identities["pe"]["debug_id"] != identities["pdb"]["debug_id"]
    ):
        raise CoreExecutionError("CATALOG_PAIR_INVALID", "Actual PE/PDB identities disagree")
    return reports, identities


def catalog_validator_version(core: CoreExecutor) -> str:
    if core.settings.core_executor == "fake":
        raise CoreExecutionError(
            "CATALOG_REAL_VALIDATOR_REQUIRED", "Fake Core cannot validate global symbols"
        )
    if core.settings.core_executor == "local":
        binary = Path(shutil.which(core.settings.core_command) or core.settings.core_command)
        return "core-identify-v1:binary-sha256:" + _hash(binary)
    return "core-identify-v1:" + core.settings.core_image_digest


def prepare_catalog_pair(
    core: CoreExecutor,
    store: ObjectStore,
    pe: Path,
    pdb: Path,
    *,
    payload_encoding: Literal["identity", "zstd-v1"] = "identity",
) -> PreparedCatalogPair:
    if payload_encoding not in {"identity", "zstd-v1"}:
        raise ValueError("Unsupported retained catalog encoding")
    # CoreExecutor independently inspects the image ID on each Docker call.
    validator = catalog_validator_version(core)
    # Unique physical locations avoid overwriting an existing retained object
    # before validation. Global physical dedup is not an admission prerequisite.
    token = new_ulid()
    with tempfile.TemporaryDirectory(prefix="crashcap-catalog-verify-") as temporary:
        directory = Path(temporary)
        staged = {"pe": directory / "module.pe", "pdb": directory / "module.pdb"}
        _copy(pe, staged["pe"], 512 * 1024 * 1024)
        _copy(pdb, staged["pdb"], 2 * 1024 * 1024 * 1024)
        reports, identities = _inspect_staged(core, staged)
        from crashcap_api.frozen_inputs import digest

        keys = {
            kind: (
                f"catalog/files/{digest(['catalog-file-v1', kind, report['sha256']])}/"
                f"{token}/payload"
            )
            for kind, report in reports.items()
        }
        payloads: dict[str, dict[str, Any]] = {}
        for kind, path in staged.items():
            if payload_encoding == "zstd-v1":
                encoded = directory / f"{kind}.zst"
                payload = ArtifactBlobCodec().encode_file(
                    path,
                    encoded,
                    kind=kind,
                    encoding=payload_encoding,
                    expected_raw_size=reports[kind]["size"],
                    expected_raw_sha256=reports[kind]["sha256"],
                )
                payloads[kind] = {"sha256": payload.payload_sha256, "size": payload.payload_size}
                retained = encoded
            else:
                payloads[kind] = {"sha256": reports[kind]["sha256"], "size": reports[kind]["size"]}
                retained = path
            store.put_file(keys[kind], retained, "application/octet-stream")
            sha, size, _ = stream_sha256(store, keys[kind])
            if (sha, size) != (payloads[kind]["sha256"], payloads[kind]["size"]):
                raise CoreExecutionError(
                    "CATALOG_PAYLOAD_INVALID",
                    "Retained payload readback differs from validated bytes",
                )
        proof: dict[str, Any] = {
            "schema_version": "catalog-verification-v1",
            "validator_version": validator,
            "files": reports,
            "identity_payloads": keys,
        }
        if payload_encoding != "identity":
            proof["schema_version"] = "catalog-verification-v2"
            del proof["identity_payloads"]
            proof["payloads"] = {
                kind: {
                    "object_key": keys[kind],
                    "encoding": payload_encoding,
                    "payload_sha256": payloads[kind]["sha256"],
                    "payload_size": payloads[kind]["size"],
                }
                for kind in staged
            }
        receipt = canonical_bytes(proof)
        receipt_sha = hashlib.sha256(receipt).hexdigest()
        receipt_key = f"catalog/verification/{receipt_sha}.json"
        store.put_bytes(receipt_key, receipt, "application/json")
        if stream_sha256(store, receipt_key)[:2] != (receipt_sha, len(receipt)):
            raise CoreExecutionError(
                "CATALOG_RECEIPT_INVALID", "Retained verification receipt failed readback"
            )
        files = {
            kind: FileEvidence(
                kind,
                report["sha256"],
                report["size"],
                identities[kind]["code_id"],
                identities[kind]["debug_id"],
                identities[kind]["architecture"],
                validator,
                receipt_key,
                receipt_sha,
            )
            for kind, report in reports.items()
        }
        locations: dict[str, tuple[LocationEvidence, ...]] = {
            kind: (
                LocationEvidence(
                    keys[kind],
                    payload_encoding,
                    str(payloads[kind]["sha256"]),
                    int(payloads[kind]["size"]),
                    "platform_owned",
                    None,
                    receipt_key,
                    receipt_sha,
                ),
            )
            for kind, file in files.items()
        }
        return PreparedCatalogPair(files["pe"], files["pdb"], locations)


def inspect_catalog_pair(core: CoreExecutor, pe: Path, pdb: Path) -> dict[str, dict[str, object]]:
    """Read-only real validation for backfill dry-runs; no retention evidence is issued."""
    if core.settings.core_executor == "fake":
        raise CoreExecutionError(
            "CATALOG_REAL_VALIDATOR_REQUIRED", "Fake Core cannot validate global symbols"
        )
    with tempfile.TemporaryDirectory(prefix="crashcap-catalog-inspect-") as temporary:
        directory = Path(temporary)
        paths = {"pe": directory / "module.pe", "pdb": directory / "module.pdb"}
        _copy(pe, paths["pe"], 512 * 1024**2)
        _copy(pdb, paths["pdb"], 2 * 1024**3)
        reports, identities = _inspect_staged(core, paths)
        return {kind: {**report, **identities[kind]} for kind, report in reports.items()}
