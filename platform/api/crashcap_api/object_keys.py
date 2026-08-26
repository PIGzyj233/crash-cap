from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath, PureWindowsPath

from .ids import validate_id

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def safe_filename(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("filename must not be empty")
    if PurePosixPath(value).name != value or PureWindowsPath(value).name != value:
        raise ValueError("filename must be a basename without path components")
    if "\x00" in value or "/" in value or "\\" in value:
        raise ValueError("filename contains a forbidden path separator")
    return value


def _sha(value: str) -> str:
    normalized = value.lower()
    if not SHA256_RE.fullmatch(normalized):
        raise ValueError("sha256 must contain exactly 64 lowercase hex characters")
    return normalized


def upload_key(workspace_id: str, upload_id: str) -> str:
    return f"uploads/{validate_id(workspace_id, 'wsp')}/{validate_id(upload_id, 'upl')}/blob"


def manifest_key(workspace_id: str, build_id: str) -> str:
    workspace = validate_id(workspace_id, "wsp")
    build = validate_id(build_id, "bld")
    return f"raw-builds/{workspace}/{build}/manifest.json"


def raw_build_key(workspace_id: str, build_id: str, sha256: str) -> str:
    return (
        f"raw-builds/{validate_id(workspace_id, 'wsp')}/"
        f"{validate_id(build_id, 'bld')}/files/{_sha(sha256)}"
    )


def artifact_blob_key(workspace_id: str, sha256: str) -> str:
    workspace = validate_id(workspace_id, "wsp")
    digest = _sha(sha256)
    return f"artifact-blobs/{workspace}/{digest[:2]}/{digest}"


def dump_blob_key(workspace_id: str, blob_id: str) -> str:
    return (
        f"dump-blobs/{validate_id(workspace_id, 'wsp')}/{validate_id(blob_id, 'blob')}/original.dmp"
    )


def analysis_prefix(workspace_id: str, occurrence_id: str, run_id: str) -> str:
    return (
        f"analysis/{validate_id(workspace_id, 'wsp')}/"
        f"{validate_id(occurrence_id, 'occ')}/{validate_id(run_id, 'run')}"
    )


def analysis_key(workspace_id: str, occurrence_id: str, run_id: str, name: str) -> str:
    if name not in {
        "canonical.json",
        "raw/minidump.json",
        "raw/symbolicator.json",
        "raw/inspect.json",
        "raw/match.json",
        "raw/legacy-canonical.json",
        "raw/core-final-shadow.json",
    }:
        raise ValueError("unsupported analysis object name")
    return f"{analysis_prefix(workspace_id, occurrence_id, run_id)}/{name}"


def analysis_generation_prefix(
    workspace_id: str,
    occurrence_id: str,
    run_id: str,
    attempt_id: str,
    generation: int,
) -> str:
    if not attempt_id:
        raise ValueError("attempt_id must not be empty")
    if generation <= 0:
        raise ValueError("generation must be positive")
    attempt_hash = hashlib.sha256(attempt_id.encode()).hexdigest()[:12]
    return f"{analysis_prefix(workspace_id, occurrence_id, run_id)}/g/{generation}-{attempt_hash}"


def analysis_generation_key(
    workspace_id: str,
    occurrence_id: str,
    run_id: str,
    attempt_id: str,
    generation: int,
    name: str,
) -> str:
    if name not in {
        "canonical.json",
        "checkpoints/inspect.json",
        "checkpoints/artifact-selection.json",
        "checkpoints/match.json",
        "raw/minidump.json",
        "raw/symbolicator.json",
        "raw/inspect.json",
        "raw/match.json",
        "raw/legacy-canonical.json",
        "raw/core-final-shadow.json",
    }:
        raise ValueError("unsupported generation-scoped analysis object name")
    prefix = analysis_generation_prefix(workspace_id, occurrence_id, run_id, attempt_id, generation)
    compact_name = {
        "checkpoints/inspect.json": "inspect.json",
        "checkpoints/artifact-selection.json": "artifact-selection.json",
        "checkpoints/match.json": "match.json",
    }.get(name, name)
    return f"{prefix}/{compact_name}"


def assert_scoped_key(key: str, workspace_id: str) -> str:
    validate_id(workspace_id, "wsp")
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or "\\" in key or "\x00" in key:
        raise ValueError("unsafe object key")
    if workspace_id not in path.parts:
        raise ValueError("object key is not scoped to the requested Workspace")
    return key
