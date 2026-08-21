#!/usr/bin/env python3
"""Fetch a pinned symsorter and populate a workspace-scoped Unified layout.

The release URL, version and SHA-256 are constants in this file. Downloads are
written through a temporary file and atomically renamed only after the digest
matches. The helper is intentionally Windows-oriented because the pinned
release asset is `symsorter-Windows-x86_64.exe`; the surrounding metadata and
verification remain standard-library Python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.fixtures.extract_pe_metadata import parse_pe  # noqa: E402


VERSION = "26.7.2"
ASSET_NAME = "symsorter-Windows-x86_64.exe"
DOWNLOAD_URL = (
    "https://github.com/getsentry/symbolicator/releases/download/"
    f"{VERSION}/{ASSET_NAME}"
)
EXPECTED_SHA256 = "b13e3b176ab8a5c1bacbf4743061496c27240bba56220f6b73318804944a3ccd"
ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "scripts" / "symbolicator" / ".tools" / "symsorter" / VERSION
TOOL_PATH = TOOLS_DIR / ASSET_NAME
DEFAULT_PE = ROOT / "fixtures" / "p0-b01-null-read" / "generated" / "null_read_target.exe"
DEFAULT_PDB = ROOT / "fixtures" / "p0-b01-null-read" / "generated" / "null_read_target.pdb"
DEFAULT_OUTPUT = ROOT / "deploy" / "symbolicator" / "symbols" / "p0-test"
DEFAULT_EVIDENCE = ROOT / "docs" / "evidence" / "symsorter-p0-test.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pinned(force: bool = False) -> tuple[Path, str, str]:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if force and TOOL_PATH.exists():
        TOOL_PATH.unlink()
    if not TOOL_PATH.exists():
        fd, temporary_name = tempfile.mkstemp(prefix=f"{ASSET_NAME}.", dir=TOOLS_DIR)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            request = urllib.request.Request(
                DOWNLOAD_URL,
                headers={"User-Agent": "crash-cap-phase0-symsorter/1"},
            )
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
                shutil.copyfileobj(response, target, length=1024 * 1024)
            observed = sha256(temporary)
            if observed != EXPECTED_SHA256:
                raise RuntimeError(
                    f"SHA-256 mismatch for {DOWNLOAD_URL}: expected {EXPECTED_SHA256}, observed {observed}"
                )
            os.replace(temporary, TOOL_PATH)
        finally:
            temporary.unlink(missing_ok=True)
    observed = sha256(TOOL_PATH)
    if observed != EXPECTED_SHA256:
        raise RuntimeError(
            f"cached symsorter hash mismatch: expected {EXPECTED_SHA256}, observed {observed}; remove {TOOL_PATH} and retry"
        )
    if os.name == "nt":
        TOOL_PATH.chmod(0o755)
    return TOOL_PATH, EXPECTED_SHA256, observed


def run_tool(tool: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [str(tool), *args]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if check and completed.returncode:
        raise RuntimeError(
            f"symsorter failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def find_unified_artifacts(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def validate_layout(output: Path, debug_id: str | None, code_id: str | None) -> dict[str, Any]:
    files = find_unified_artifacts(output)
    normalized_debug_id = (debug_id or "").lower()
    # Unified layout is <first-two>/<remaining>/debuginfo|executable. Verify
    # the two path components rather than searching for a contiguous ID.
    unified_prefix = (
        f"{normalized_debug_id[:2]}/{normalized_debug_id[2:]}"
        if len(normalized_debug_id) > 2
        else ""
    )
    matching = [
        path
        for path in files
        if unified_prefix and path.lower().startswith(unified_prefix + "/")
    ]
    has_debuginfo = any(path.lower().endswith("/debuginfo") for path in files)
    has_executable = any(path.lower().endswith("/executable") for path in files)
    executable_identity_matches = False
    executable_identities: list[dict[str, Any]] = []
    for relative in files:
        if not relative.lower().endswith("/executable"):
            continue
        try:
            identity = parse_pe(output / relative)
        except (OSError, ValueError, struct.error):
            continue
        executable_identities.append(
            {"path": relative, "code_id": identity.get("code_id"), "debug_id": identity.get("debug_id")}
        )
        if identity.get("code_id") == code_id and identity.get("debug_id") == debug_id:
            executable_identity_matches = True
    return {
        "output_root": str(output),
        "file_count": len(files),
        "files": files,
        "debug_id": debug_id,
        "code_id": code_id,
        "debug_id_in_paths": matching,
        "has_debuginfo": has_debuginfo,
        "has_executable": has_executable,
        "executable_identities": executable_identities,
        "executable_identity_matches": executable_identity_matches,
        "ready_for_symbolicator": bool(
            matching and has_debuginfo and has_executable and executable_identity_matches
        ),
    }


def default_sort_args(tool: Path, pe: Path, pdb: Path, output: Path) -> list[str]:
    # The pinned 26.7.2 release accepts PE/PDB files as positional inputs and
    # writes the unified tree below --output. Do not add --prefix here: the
    # caller's output directory is already the explicit workspace scope
    # (`.../symbols/p0-test`).
    return ["--output", str(output), str(pe), str(pdb)]


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument(
        "--clean-debug-id",
        action="store_true",
        help="remove only this input debug_id directory under --output before sorting",
    )
    parser.add_argument("--help-tool", action="store_true", help="print the pinned binary's help and stop")
    parser.add_argument("--pe", type=Path, default=DEFAULT_PE)
    parser.add_argument("--pdb", type=Path, default=DEFAULT_PDB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--symsorter-args",
        nargs=argparse.REMAINDER,
        help="optional: arguments after --symsorter-args are passed verbatim; otherwise the pinned PE/PDB command is used",
    )
    args = parser.parse_args()

    tool, expected_hash, observed_hash = download_pinned(force=args.force_download)
    help_result = run_tool(tool, "--help", check=False)
    if args.help_tool:
        sys.stdout.write(help_result.stdout)
        sys.stderr.write(help_result.stderr)
        return help_result.returncode

    if not args.pe.is_file() or not args.pdb.is_file():
        raise SystemExit(f"matching PE/PDB not found: {args.pe} / {args.pdb}")

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    metadata = parse_pe(args.pe)
    debug_id = metadata.get("debug_id")
    code_id = metadata.get("code_id")
    if args.clean_debug_id and debug_id:
        debug_directory = output / str(debug_id)[:2] / str(debug_id)[2:]
        if debug_directory.is_dir():
            # The target is derived from the PE's exact debug_id and remains
            # below the explicitly supplied workspace output directory.
            shutil.rmtree(debug_directory)
    sort_args = args.symsorter_args or default_sort_args(tool, args.pe, args.pdb, output)
    command_result = run_tool(tool, *sort_args)
    layout = validate_layout(output, str(debug_id) if debug_id else None, str(code_id) if code_id else None)
    evidence = {
        "schema_version": "symsorter-evidence-v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "asset": ASSET_NAME,
        "download_url": DOWNLOAD_URL,
        "expected_sha256": expected_hash,
        "observed_sha256": observed_hash,
        "tool_path": str(tool),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "inputs": {"pe": str(args.pe), "pdb": str(args.pdb)},
        "clean_debug_id_before_sort": args.clean_debug_id,
        "output": layout,
        "command": [str(tool), *sort_args],
        "stdout": command_result.stdout,
        "stderr": command_result.stderr,
        "returncode": command_result.returncode,
        "help_probe": {
            "returncode": help_result.returncode,
            "stdout": help_result.stdout,
            "stderr": help_result.stderr,
        },
    }
    write_evidence(args.evidence if args.evidence.is_absolute() else ROOT / args.evidence, evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if layout["ready_for_symbolicator"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
