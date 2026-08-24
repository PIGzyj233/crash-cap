from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from crashcap_api.config import Settings
from crashcap_api.ids import validate_id


class SymbolIngestError(RuntimeError):
    pass


class SymbolIngestor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def publish_pair(self, workspace_id: str, pe_path: Path, pdb_path: Path, debug_id: str) -> None:
        validate_id(workspace_id, "wsp")
        normalized_debug_id = debug_id.lower()
        if len(normalized_debug_id) <= 2 or any(
            character not in "0123456789abcdef" for character in normalized_debug_id
        ):
            raise SymbolIngestError("debug_id must be a non-empty hexadecimal Unified identity")
        if self.settings.symbol_ingest_mode == "fake":
            return
        root = self.settings.unified_symbol_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = (root / workspace_id).resolve()
        if root not in destination.parents:
            raise SymbolIngestError("Workspace symbol path escaped the Unified root")
        with tempfile.TemporaryDirectory(prefix=f".{workspace_id}-", dir=root) as raw_staging:
            staging = Path(raw_staging)
            try:
                result = subprocess.run(  # noqa: S603 - fixed argv, never a shell
                    [
                        self.settings.symsorter_command,
                        "--output",
                        str(staging),
                        str(pe_path),
                        str(pdb_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=900,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise SymbolIngestError(f"symsorter could not complete: {error}") from error
            if result.returncode != 0:
                raise SymbolIngestError(
                    f"symsorter exited {result.returncode}: {result.stderr[-2000:]}"
                )

            staged_identity = staging / normalized_debug_id[:2] / normalized_debug_id[2:]
            expected_hashes = _validate_staged_pair(staged_identity, pe_path, pdb_path)
            target = destination / normalized_debug_id[:2] / normalized_debug_id[2:]
            if _published_pair_matches(target, expected_hashes):
                return
            _atomic_replace_identity(staged_identity, target)


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _validate_staged_pair(identity: Path, pe_path: Path, pdb_path: Path) -> dict[str, str]:
    required = {
        "executable": identity / "executable",
        "executable.meta": identity / "executable.meta",
        "debuginfo": identity / "debuginfo",
        "debuginfo.meta": identity / "debuginfo.meta",
    }
    invalid = [
        name
        for name, path in required.items()
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0
    ]
    if invalid:
        raise SymbolIngestError(
            f"symsorter staging is incomplete for the expected debug_id: {', '.join(invalid)}"
        )
    expected = {"executable": _sha256(pe_path), "debuginfo": _sha256(pdb_path)}
    observed = {name: _sha256(required[name]) for name in expected}
    if observed != expected:
        raise SymbolIngestError("symsorter staging hashes do not match the verified PE/PDB pair")
    return expected


def _published_pair_matches(identity: Path, expected: dict[str, str]) -> bool:
    required = [identity / "executable.meta", identity / "debuginfo.meta"]
    if any(
        not path.is_file() or path.is_symlink() or path.stat().st_size == 0 for path in required
    ):
        return False
    for name, digest in expected.items():
        path = identity / name
        if not path.is_file() or path.is_symlink() or _sha256(path) != digest:
            return False
    return True


def _atomic_replace_identity(staged_identity: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
    moved_existing = False
    try:
        if target.exists() or target.is_symlink():
            os.replace(target, backup)
            moved_existing = True
        os.replace(staged_identity, target)
    except OSError as error:
        if moved_existing and not target.exists() and backup.exists():
            try:
                os.replace(backup, target)
            except OSError as restore_error:
                message = (
                    "Unified publish failed and the prior identity could not be restored: "
                    f"{restore_error}"
                )
                raise SymbolIngestError(message) from error
        raise SymbolIngestError(f"Unified identity replacement failed: {error}") from error
    if moved_existing and backup.exists():
        if backup.is_dir() and not backup.is_symlink():
            shutil.rmtree(backup, ignore_errors=True)
        else:
            backup.unlink(missing_ok=True)
