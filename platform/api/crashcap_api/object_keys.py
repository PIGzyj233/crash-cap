from __future__ import annotations

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
    }:
        raise ValueError("unsupported analysis object name")
    return f"{analysis_prefix(workspace_id, occurrence_id, run_id)}/{name}"


def assert_scoped_key(key: str, workspace_id: str) -> str:
    validate_id(workspace_id, "wsp")
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or "\\" in key or "\x00" in key:
        raise ValueError("unsafe object key")
    if workspace_id not in path.parts:
        raise ValueError("object key is not scoped to the requested Workspace")
    return key
