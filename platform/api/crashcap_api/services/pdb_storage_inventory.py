from __future__ import annotations

import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobLegacyCopy,
    ArtifactBlobPair,
    ArtifactBlobPayloadLegacyCopy,
    Build,
    Upload,
)
from ..storage import ObjectStore

OBJECT_PREFIXES = ("uploads", "raw-builds", "artifact-blobs", "artifact-blobs-v2")
SYMBOLICATOR_CACHE_DIRECTORIES = {
    "downloaded": ("objects", "auxdifs", "il2cpp", "sourcefiles", "proguard"),
    "derived": (
        "object_meta",
        "symcaches",
        "cficaches",
        "ppdb_caches",
        "sourcemap_caches",
    ),
}


def collect_pdb_storage_inventory(
    session: Session,
    store: ObjectStore,
    *,
    unified_root: Path | None = None,
    symbolicator_cache_root: Path | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "pdb-storage-inventory-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "database": {
            "artifacts": _artifact_groups(session),
            "artifact_blobs": _blob_groups(session),
            "uploads": _upload_groups(session),
            "legacy_artifact_copies": _legacy_groups(session),
            "payload_rollback_copies": _payload_legacy_groups(session),
            "blob_pairs": _pair_groups(session),
        },
        "object_store": _object_store_groups(store),
        "reconciliation": {
            "upload_payloads": _upload_object_reconciliation(session, store),
        },
        "volumes": {
            "unified": _directory_inventory(unified_root),
            "symbolicator_cache": _cache_inventory(symbolicator_cache_root),
        },
        "privacy": {
            "object_keys_included": False,
            "filenames_included": False,
            "credentials_included": False,
        },
    }
    return report


def render_pdb_storage_inventory_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDB storage inventory",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "This report contains aggregate counts and bytes only; "
        "object keys and credentials are omitted.",
        "",
        "## Object store",
        "",
        "| Prefix | Workspace | Objects | Bytes |",
        "| --- | --- | ---: | ---: |",
    ]
    for row in report["object_store"]:
        lines.append(
            f"| {row['prefix']} | {row['workspace_id']} | {row['object_count']} | {row['bytes']} |"
        )
    lines.extend(["", "## Database Artifact Blobs", ""])
    lines.extend(_markdown_table(report["database"]["artifact_blobs"]))
    lines.extend(["", "## Upload payload lifecycle", ""])
    lines.extend(_markdown_table(report["database"]["uploads"]))
    lines.extend(["", "## Upload payload reconciliation", ""])
    lines.extend(_markdown_table(report["reconciliation"]["upload_payloads"]))
    lines.extend(["", "## Per-Build legacy Artifact copies", ""])
    lines.extend(_markdown_table(report["database"]["legacy_artifact_copies"]))
    lines.extend(["", "## Raw payload rollback copies", ""])
    lines.extend(_markdown_table(report["database"]["payload_rollback_copies"]))
    lines.extend(["", "## Volumes", ""])
    lines.extend(_markdown_table(_flatten_volumes(report["volumes"])))
    return "\n".join(lines) + "\n"


def _artifact_groups(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            Build.workspace_id,
            Artifact.kind,
            Artifact.verification_status,
            func.count(),
            func.coalesce(func.sum(Artifact.size), 0),
        )
        .join(Build, Build.id == Artifact.build_id)
        .group_by(Build.workspace_id, Artifact.kind, Artifact.verification_status)
        .order_by(Build.workspace_id, Artifact.kind, Artifact.verification_status)
    ).all()
    return [
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "state": state,
            "count": int(count),
            "logical_bytes": int(size),
        }
        for workspace_id, kind, state, count, size in rows
    ]


def _blob_groups(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            ArtifactBlob.verification_status,
            ArtifactBlob.payload_encoding,
            func.count(),
            func.coalesce(func.sum(ArtifactBlob.size), 0),
            func.coalesce(func.sum(ArtifactBlob.payload_size), 0),
        )
        .group_by(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            ArtifactBlob.verification_status,
            ArtifactBlob.payload_encoding,
        )
        .order_by(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            ArtifactBlob.verification_status,
            ArtifactBlob.payload_encoding,
        )
    ).all()
    return [
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "state": state,
            "encoding": encoding,
            "count": int(count),
            "logical_bytes": int(logical),
            "stored_bytes": int(stored),
        }
        for workspace_id, kind, state, encoding, count, logical, stored in rows
    ]


def _upload_groups(session: Session) -> list[dict[str, Any]]:
    payload_state = case(
        (Upload.payload_deleted_at.is_not(None), "deleted"), else_="retained"
    ).label("payload_state")
    rows = session.execute(
        select(
            Upload.workspace_id,
            Upload.file_kind,
            Upload.verification_status,
            payload_state,
            func.count(),
            func.coalesce(
                func.sum(
                    func.coalesce(
                        Upload.verified_wire_length,
                        Upload.wire_declared_length,
                        Upload.declared_length,
                    )
                ),
                0,
            ),
        )
        .group_by(
            Upload.workspace_id,
            Upload.file_kind,
            Upload.verification_status,
            payload_state,
        )
        .order_by(Upload.workspace_id, Upload.file_kind, Upload.verification_status)
    ).all()
    return [
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "state": state,
            "payload_state": payload_state,
            "count": int(count),
            "payload_bytes": int(size),
        }
        for workspace_id, kind, state, payload_state, count, size in rows
    ]


def _legacy_groups(session: Session) -> list[dict[str, Any]]:
    copy_state = case(
        (ArtifactBlobLegacyCopy.deleted_at.is_not(None), "deleted"), else_="retained"
    ).label("copy_state")
    rows = session.execute(
        select(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            copy_state,
            func.count(),
            func.coalesce(func.sum(ArtifactBlob.size), 0),
        )
        .join(ArtifactBlob, ArtifactBlob.id == ArtifactBlobLegacyCopy.artifact_blob_id)
        .group_by(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            copy_state,
        )
        .order_by(ArtifactBlob.workspace_id, ArtifactBlob.kind)
    ).all()
    return [
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "state": state,
            "count": int(count),
            "logical_bytes": int(size),
        }
        for workspace_id, kind, state, count, size in rows
    ]


def _payload_legacy_groups(session: Session) -> list[dict[str, Any]]:
    copy_state = case(
        (ArtifactBlobPayloadLegacyCopy.deleted_at.is_not(None), "deleted"),
        else_="retained",
    ).label("copy_state")
    rows = session.execute(
        select(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            copy_state,
            func.count(),
            func.coalesce(func.sum(ArtifactBlobPayloadLegacyCopy.size), 0),
        )
        .join(
            ArtifactBlob,
            ArtifactBlob.id == ArtifactBlobPayloadLegacyCopy.artifact_blob_id,
        )
        .group_by(
            ArtifactBlob.workspace_id,
            ArtifactBlob.kind,
            copy_state,
        )
        .order_by(ArtifactBlob.workspace_id, ArtifactBlob.kind)
    ).all()
    return [
        {
            "workspace_id": workspace_id,
            "kind": kind,
            "state": state,
            "count": int(count),
            "stored_bytes": int(size),
        }
        for workspace_id, kind, state, count, size in rows
    ]


def _pair_groups(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ArtifactBlobPair.workspace_id, ArtifactBlobPair.state, func.count())
        .group_by(ArtifactBlobPair.workspace_id, ArtifactBlobPair.state)
        .order_by(ArtifactBlobPair.workspace_id, ArtifactBlobPair.state)
    ).all()
    return [
        {"workspace_id": workspace_id, "state": state, "count": int(count)}
        for workspace_id, state, count in rows
    ]


def _object_store_groups(store: ObjectStore) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for prefix in OBJECT_PREFIXES:
        for item in store.iter_objects(prefix):
            parts = item.key.split("/")
            workspace_id = parts[1] if len(parts) > 1 and parts[1].startswith("wsp_") else "unknown"
            value = groups[(prefix, workspace_id)]
            value[0] += 1
            value[1] += item.size
    return [
        {
            "prefix": prefix,
            "workspace_id": workspace_id,
            "object_count": values[0],
            "bytes": values[1],
        }
        for (prefix, workspace_id), values in sorted(groups.items())
    ]


def _upload_object_reconciliation(session: Session, store: ObjectStore) -> list[dict[str, Any]]:
    database_rows = session.execute(
        select(
            Upload.object_key,
            Upload.workspace_id,
            Upload.payload_deleted_at,
            func.coalesce(
                Upload.verified_wire_length,
                Upload.wire_declared_length,
                Upload.declared_length,
            ),
        )
    ).all()
    database = {
        object_key: {
            "workspace_id": workspace_id,
            "deleted": payload_deleted_at is not None,
            "bytes": int(byte_count),
        }
        for object_key, workspace_id, payload_deleted_at, byte_count in database_rows
    }
    objects = {item.key: item.size for item in store.iter_objects("uploads")}
    counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for object_key, size in objects.items():
        durable = database.get(object_key)
        if durable is None:
            parts = object_key.split("/")
            workspace_id = parts[1] if len(parts) > 1 and parts[1].startswith("wsp_") else "unknown"
            counters[workspace_id]["orphan_objects"] += 1
            counters[workspace_id]["orphan_bytes"] += int(size)
            continue
        workspace_id = str(durable["workspace_id"])
        if bool(durable["deleted"]):
            counters[workspace_id]["deleted_marker_but_present_objects"] += 1
            counters[workspace_id]["deleted_marker_but_present_bytes"] += int(size)
        elif int(durable["bytes"]) != int(size):
            counters[workspace_id]["size_mismatch_objects"] += 1
            counters[workspace_id]["size_mismatch_bytes"] += abs(int(durable["bytes"]) - int(size))

    for object_key, durable in database.items():
        if not bool(durable["deleted"]) and object_key not in objects:
            workspace_id = str(durable["workspace_id"])
            counters[workspace_id]["missing_retained_objects"] += 1
            counters[workspace_id]["missing_retained_bytes"] += int(durable["bytes"])

    fields = (
        "orphan_objects",
        "orphan_bytes",
        "missing_retained_objects",
        "missing_retained_bytes",
        "deleted_marker_but_present_objects",
        "deleted_marker_but_present_bytes",
        "size_mismatch_objects",
        "size_mismatch_bytes",
    )
    workspace_ids = sorted({str(row["workspace_id"]) for row in database.values()} | set(counters))
    return [
        {"workspace_id": workspace_id, **{field: counters[workspace_id][field] for field in fields}}
        for workspace_id in workspace_ids
    ]


def _directory_inventory(root: Path | None) -> list[dict[str, Any]]:
    if root is None or not root.is_dir():
        return [{"scope": "all", "status": "unavailable", "file_count": 0, "bytes": 0}]
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        scope = (
            relative.parts[0]
            if relative.parts and relative.parts[0].startswith("wsp_")
            else "shared"
        )
        groups[scope][0] += 1
        groups[scope][1] += path.stat().st_size
    return [
        {"scope": scope, "status": "available", "file_count": value[0], "bytes": value[1]}
        for scope, value in sorted(groups.items())
    ]


def _cache_inventory(root: Path | None) -> list[dict[str, Any]]:
    if root is None:
        return [
            {
                "scope": cache_kind,
                "status": "unavailable",
                "file_count": 0,
                "bytes": 0,
                "oldest_age_seconds": None,
            }
            for cache_kind in SYMBOLICATOR_CACHE_DIRECTORIES
        ]
    try:
        with os.scandir(root) as root_entries:
            children = {entry.name: entry for entry in root_entries}
    except OSError:
        return [
            {
                "scope": cache_kind,
                "status": "unavailable",
                "file_count": 0,
                "bytes": 0,
                "oldest_age_seconds": None,
            }
            for cache_kind in SYMBOLICATOR_CACHE_DIRECTORIES
        ]
    now = datetime.now(UTC).timestamp()
    result: list[dict[str, Any]] = []
    for cache_kind, directory_names in SYMBOLICATOR_CACHE_DIRECTORIES.items():
        file_count = 0
        byte_count = 0
        oldest_mtime: float | None = None
        available = True
        pending: list[Path] = []
        try:
            for directory_name in directory_names:
                entry = children.get(directory_name)
                if entry is None:
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    raise OSError("Symbolicator cache path is not a regular directory")
                pending.append(Path(entry.path))
            while pending:
                current = pending.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stats = entry.stat(follow_symlinks=False)
                            file_count += 1
                            byte_count += int(stats.st_size)
                            oldest_mtime = (
                                stats.st_mtime
                                if oldest_mtime is None
                                else min(oldest_mtime, stats.st_mtime)
                            )
        except OSError:
            available = False
        result.append(
            {
                "scope": cache_kind,
                "status": "available" if available else "unavailable",
                "file_count": file_count if available else 0,
                "bytes": byte_count if available else 0,
                "oldest_age_seconds": (
                    max(0, int(now - oldest_mtime))
                    if available and oldest_mtime is not None
                    else 0
                    if available
                    else None
                ),
            }
        )
    return result


def _flatten_volumes(volumes: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"volume": name, **row} for name, rows in volumes.items() for row in rows]


def _markdown_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["No rows."]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    rendered = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    rendered.extend(
        "| " + " | ".join(str(row.get(key, "")) for key in columns) + " |" for row in rows
    )
    return rendered
