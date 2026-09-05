"""Prepare verified, retained catalog input before entering a DB transaction."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from crashcap_api.frozen_inputs import normalize_identity

from .core_runner import CoreExecutionError, CoreExecutor


def _hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def catalog_validator_version(core: CoreExecutor) -> str:
    if core.settings.core_executor == "fake":
        raise CoreExecutionError(
            "CATALOG_REAL_VALIDATOR_REQUIRED", "Fake Core cannot validate global symbols"
        )
    if core.settings.core_executor == "local":
        binary = Path(shutil.which(core.settings.core_command) or core.settings.core_command)
        return "core-identify-v1:binary-sha256:" + _hash(binary)
    return "core-identify-v1:" + core.settings.core_image_digest


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
