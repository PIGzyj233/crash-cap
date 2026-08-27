#!/usr/bin/env python3
"""Seed or corrupt the isolated zstd-only Artifact Blob symbol-source corpus."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tarfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import ArtifactBlob, ArtifactBlobPair, Workspace
from crashcap_api.services.artifact_payloads import (
    ZSTD_ENCODING,
    ArtifactBlobCodec,
    configure_zstd_payload,
)
from crashcap_api.storage import LocalObjectStore, create_object_store
from sqlalchemy import select

WORKSPACE_ID = "wsp_01M0VEVHHMTZH6GQB6KTF07XTK"
INVENTORY = 1
FIXTURE_ROOT = Path("/fixture")
BACKUP_FORMAT = "artifact-blob-object-backup-v1"
BACKUP_ROOT = Path("/evidence")
MAX_BACKUP_OBJECTS = 10_000
MAX_BACKUP_BYTES = 64 * 1024 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require_local_store(settings: Settings) -> LocalObjectStore:
    store = create_object_store(settings)
    if not isinstance(store, LocalObjectStore):
        raise TypeError("the isolated UAT seeder requires the local object-store backend")
    return store


def safe_archive_path(value: Path) -> Path:
    resolved = value.resolve()
    if resolved.parent != BACKUP_ROOT.resolve() or resolved.suffix != ".tar":
        raise ValueError("backup archive must be one direct .tar child of /evidence")
    return resolved


def safe_object_key(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or not path.parts
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError("backup manifest contains an unsafe object path")
    return value


def backup_objects(settings: Settings, archive_value: Path) -> dict[str, Any]:
    store = require_local_store(settings)
    archive = safe_archive_path(archive_value)
    if archive.exists():
        raise FileExistsError("backup archive already exists")
    candidates = sorted(store.root.rglob("*"))
    if any(path.is_symlink() for path in candidates):
        raise RuntimeError("object backup refuses symbolic links")
    files = [path for path in candidates if path.is_file()]
    if not files or len(files) > MAX_BACKUP_OBJECTS:
        raise RuntimeError("object backup file count is outside its bounded range")
    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for path in files:
        relative = safe_object_key(path.relative_to(store.root).as_posix())
        size = path.stat().st_size
        total_bytes += size
        if size <= 0 or total_bytes > MAX_BACKUP_BYTES:
            raise RuntimeError("object backup byte count is outside its bounded range")
        entries.append({"path": relative, "size": size, "sha256": sha256_file(path)})
    manifest = {
        "format": BACKUP_FORMAT,
        "object_count": len(entries),
        "total_bytes": total_bytes,
        "objects": entries,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    partial = archive.with_name(f".{archive.name}.{os.getpid()}.partial")
    partial.unlink(missing_ok=True)
    try:
        with tarfile.open(partial, "w", format=tarfile.PAX_FORMAT) as bundle:
            manifest_info = tarfile.TarInfo("manifest.json")
            manifest_info.size = len(manifest_bytes)
            manifest_info.mode = 0o444
            manifest_info.mtime = 0
            bundle.addfile(manifest_info, io.BytesIO(manifest_bytes))
            for path, entry in zip(files, entries, strict=True):
                info = tarfile.TarInfo(f"objects/{entry['path']}")
                info.size = int(entry["size"])
                info.mode = 0o444
                info.mtime = 0
                with path.open("rb") as handle:
                    bundle.addfile(info, handle)
        os.replace(partial, archive)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        "action": "backup",
        "format": BACKUP_FORMAT,
        "object_count": len(entries),
        "total_bytes": total_bytes,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
    }


def restore_objects(settings: Settings, archive_value: Path) -> dict[str, Any]:
    store = require_local_store(settings)
    archive = safe_archive_path(archive_value)
    if not archive.is_file():
        raise FileNotFoundError("object backup archive does not exist")
    if any(store.root.iterdir()):
        raise RuntimeError("object restore requires an empty destination root")
    written: list[Path] = []
    partials: list[Path] = []
    try:
        with tarfile.open(archive, "r:") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_BACKUP_OBJECTS + 1:
                raise RuntimeError("object backup member count exceeds its hard limit")
            if any(not member.isfile() for member in members):
                raise RuntimeError("object backup may contain regular files only")
            by_name = {member.name: member for member in members}
            if len(by_name) != len(members) or "manifest.json" not in by_name:
                raise RuntimeError("object backup has duplicate members or no manifest")
            manifest_member = by_name["manifest.json"]
            if manifest_member.size <= 0 or manifest_member.size > 1024 * 1024:
                raise RuntimeError("object backup manifest size is invalid")
            manifest_handle = bundle.extractfile(manifest_member)
            if manifest_handle is None:
                raise RuntimeError("object backup manifest cannot be read")
            manifest_bytes = manifest_handle.read(1024 * 1024 + 1)
            manifest = json.loads(manifest_bytes)
            if not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT:
                raise RuntimeError("object backup manifest format is invalid")
            entries = manifest.get("objects")
            if not isinstance(entries, list) or not entries or len(entries) > MAX_BACKUP_OBJECTS:
                raise RuntimeError("object backup manifest object count is invalid")
            expected_members = {"manifest.json"}
            total_bytes = 0
            normalized: list[tuple[str, int, str, tarfile.TarInfo]] = []
            seen_paths: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise TypeError("object backup manifest entry is invalid")
                object_key = safe_object_key(str(entry.get("path") or ""))
                size = int(entry.get("size") or 0)
                digest = str(entry.get("sha256") or "")
                member_name = f"objects/{object_key}"
                if (
                    object_key in seen_paths
                    or size <= 0
                    or not SHA256_RE.fullmatch(digest)
                    or member_name not in by_name
                    or by_name[member_name].size != size
                ):
                    raise RuntimeError("object backup manifest identity is invalid")
                seen_paths.add(object_key)
                expected_members.add(member_name)
                total_bytes += size
                if total_bytes > MAX_BACKUP_BYTES:
                    raise RuntimeError("object backup exceeds its byte limit")
                normalized.append((object_key, size, digest, by_name[member_name]))
            if set(by_name) != expected_members:
                raise RuntimeError("object backup contains unlisted members")
            if manifest.get("object_count") != len(normalized) or manifest.get(
                "total_bytes"
            ) != total_bytes:
                raise RuntimeError("object backup manifest totals are inconsistent")

            for object_key, expected_size, expected_sha256, member in normalized:
                source = bundle.extractfile(member)
                if source is None:
                    raise RuntimeError("object backup member cannot be read")
                destination = store.path_for(object_key)
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = destination.with_name(f".{destination.name}.restore.partial")
                partials.append(partial)
                observed_size = 0
                digest = hashlib.sha256()
                with partial.open("wb") as handle:
                    while chunk := source.read(1024 * 1024):
                        observed_size += len(chunk)
                        if observed_size > expected_size:
                            raise RuntimeError("object backup member exceeds its declared size")
                        digest.update(chunk)
                        handle.write(chunk)
                if observed_size != expected_size or digest.hexdigest() != expected_sha256:
                    raise RuntimeError("object backup member failed SHA-256 verification")
                os.replace(partial, destination)
                partials.remove(partial)
                written.append(destination)
    except Exception:
        for path in partials:
            path.unlink(missing_ok=True)
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {
        "action": "restore",
        "format": BACKUP_FORMAT,
        "object_count": len(written),
        "total_bytes": sum(path.stat().st_size for path in written),
        "archive_size": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
    }


def seed(settings: Settings) -> dict[str, Any]:
    database = Database(settings)
    store = require_local_store(settings)
    metadata = json.loads(
        (FIXTURE_ROOT / "generated" / "pe-metadata.json").read_text(encoding="utf-8")
    )
    debug_id = str(metadata["debug_id"]).lower()
    code_id = str(metadata["code_id"])
    now = datetime.now(UTC)
    codec = ArtifactBlobCodec()
    blobs: dict[str, ArtifactBlob] = {}
    rows: list[dict[str, Any]] = []

    with database.sessions() as session:
        existing = session.get(Workspace, WORKSPACE_ID)
        if existing is not None:
            raise RuntimeError("isolated UAT database was not empty before seed")
        session.add(
            Workspace(
                id=WORKSPACE_ID,
                name="pdb-storage-real-dmp-uat",
                display_name="PDB storage real DMP UAT",
                symbol_inventory_version=INVENTORY,
            )
        )
        session.flush()

        for kind, filename in (
            ("pe", "null_read_target.exe"),
            ("pdb", "null_read_target.pdb"),
        ):
            source = FIXTURE_ROOT / "generated" / filename
            raw_sha256 = sha256_file(source)
            payload_key = (
                f"artifact-blob-payloads/{WORKSPACE_ID}/{raw_sha256[:2]}/"
                f"{raw_sha256}/payload.zst"
            )
            encoded = Path("/tmp") / f"{kind}-{raw_sha256}.zst"  # noqa: S108
            digest = codec.encode_file(
                source,
                encoded,
                kind=kind,
                encoding=ZSTD_ENCODING,
                expected_raw_size=source.stat().st_size,
                expected_raw_sha256=raw_sha256,
            )
            store.put_file(payload_key, encoded, "application/zstd")
            encoded.unlink(missing_ok=True)
            blob = ArtifactBlob(
                id=f"abl_real_dmp_{kind}",
                workspace_id=WORKSPACE_ID,
                sha256=raw_sha256,
                kind=kind,
                size=source.stat().st_size,
                object_key=(
                    f"intentionally-absent-raw/{WORKSPACE_ID}/{raw_sha256}/{filename}"
                ),
                payload_encoding=ZSTD_ENCODING,
                payload_size=digest.payload_size,
                payload_sha256=digest.payload_sha256,
                payload_object_key=payload_key,
                code_id=code_id if kind == "pe" else None,
                debug_id=debug_id,
                verification_status="verified",
                verification_reason=None,
                verified_at=now,
                payload_verified_at=now,
            )
            configure_zstd_payload(blob, object_key=payload_key, payload=digest, verified_at=now)
            session.add(blob)
            blobs[kind] = blob
            rows.append(
                {
                    "kind": kind,
                    "raw_size": digest.raw_size,
                    "raw_sha256": digest.raw_sha256,
                    "payload_size": digest.payload_size,
                    "payload_sha256": digest.payload_sha256,
                    "ratio": digest.payload_size / digest.raw_size,
                    "payload_encoding": digest.encoding,
                    "raw_object_present": store.path_for(blob.object_key).exists(),
                }
            )
        session.flush()
        session.add(
            ArtifactBlobPair(
                id="abp_real_dmp_pair",
                workspace_id=WORKSPACE_ID,
                pe_blob_id=blobs["pe"].id,
                pdb_blob_id=blobs["pdb"].id,
                state="published",
                published_at=now,
            )
        )
        session.commit()

    object_files = sorted(
        path.relative_to(store.root).as_posix()
        for path in store.root.rglob("*")
        if path.is_file()
    )
    if len(object_files) != 2 or any(not path.endswith("payload.zst") for path in object_files):
        raise RuntimeError(f"zstd-only object-store invariant failed: {object_files!r}")
    if any(not row["payload_encoding"] == ZSTD_ENCODING for row in rows):
        raise RuntimeError("seeded Artifact Blob was not zstd-v1")
    if any(row["raw_object_present"] for row in rows):
        raise RuntimeError("raw canonical object unexpectedly exists")
    return {
        "action": "seed",
        "workspace_id": WORKSPACE_ID,
        "inventory": INVENTORY,
        "debug_id": debug_id,
        "code_id": code_id,
        "blobs": rows,
        "physical_object_count": len(object_files),
        "physical_objects_are_zstd_only": True,
    }


def corrupt(settings: Settings, kind: str) -> dict[str, Any]:
    database = Database(settings)
    store = require_local_store(settings)
    with database.sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == WORKSPACE_ID,
                ArtifactBlob.kind == kind,
            )
        )
        if blob is None:
            raise RuntimeError(f"cannot corrupt absent {kind} Artifact Blob")
        path = store.path_for(blob.payload_object_key)
        expected_sha256 = blob.payload_sha256
    payload = bytearray(path.read_bytes())
    if len(payload) < 16:
        raise RuntimeError("payload is too small for deterministic corruption injection")
    offset = len(payload) // 2
    payload[offset] ^= 0x01
    path.write_bytes(payload)
    observed_sha256 = sha256_file(path)
    if observed_sha256 == expected_sha256:
        raise RuntimeError("corruption injection did not alter payload SHA-256")
    return {
        "action": "corrupt",
        "workspace_id": WORKSPACE_ID,
        "kind": kind,
        "offset": offset,
        "size_preserved": path.stat().st_size == len(payload),
        "expected_payload_sha256": expected_sha256,
        "observed_payload_sha256": observed_sha256,
    }


def inspect_seed(settings: Settings) -> dict[str, Any]:
    database = Database(settings)
    store = require_local_store(settings)
    rows: list[dict[str, Any]] = []
    with database.sessions() as session:
        workspace = session.get(Workspace, WORKSPACE_ID)
        blobs = session.scalars(
            select(ArtifactBlob)
            .where(ArtifactBlob.workspace_id == WORKSPACE_ID)
            .order_by(ArtifactBlob.kind)
        ).all()
        pair = session.get(ArtifactBlobPair, "abp_real_dmp_pair")
        for blob in blobs:
            payload_path = store.path_for(blob.payload_object_key)
            rows.append(
                {
                    "kind": blob.kind,
                    "logical_size": blob.size,
                    "logical_sha256": blob.sha256,
                    "payload_encoding": blob.payload_encoding,
                    "payload_size": blob.payload_size,
                    "payload_sha256": blob.payload_sha256,
                    "payload_present": payload_path.is_file(),
                    "payload_observed_sha256": (
                        sha256_file(payload_path) if payload_path.is_file() else None
                    ),
                    "raw_object_present": store.path_for(blob.object_key).exists(),
                    "verification_status": blob.verification_status,
                    "payload_verified": blob.payload_verified_at is not None,
                }
            )
    object_files = [path for path in store.root.rglob("*") if path.is_file()]
    return {
        "action": "inspect",
        "workspace_id": WORKSPACE_ID,
        "inventory": workspace.symbol_inventory_version if workspace else None,
        "pair_state": pair.state if pair else None,
        "blobs": rows,
        "physical_object_count": len(object_files),
        "physical_objects_are_zstd_only": bool(object_files)
        and all(path.name == "payload.zst" for path in object_files),
    }


def probe(settings: Settings, kind: str) -> dict[str, Any]:
    database = Database(settings)
    with database.sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == WORKSPACE_ID,
                ArtifactBlob.kind == kind,
            )
        )
        if blob is None or blob.debug_id is None:
            raise RuntimeError(f"cannot probe absent {kind} Artifact Blob")
        debug_id = blob.debug_id.lower()
        expected_size = blob.size
        expected_sha256 = blob.sha256
    leaf = "executable" if kind == "pe" else "debuginfo"
    url = (
        "http://symbol-source:8081/v1/workspaces/"
        f"{WORKSPACE_ID}/inventories/{INVENTORY}/{debug_id[:2]}/{debug_id[2:]}/{leaf}"
    )
    request = urllib.request.Request(url, method="GET")  # noqa: S310 - fixed internal HTTP URL
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            digest = hashlib.sha256()
            observed_size = 0
            while chunk := response.read(1024 * 1024):
                observed_size += len(chunk)
                digest.update(chunk)
            return {
                "action": "probe",
                "kind": kind,
                "http_status": response.status,
                "observed_size": observed_size,
                "observed_sha256": digest.hexdigest(),
                "matches_logical_identity": (
                    observed_size == expected_size and digest.hexdigest() == expected_sha256
                ),
            }
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            detail: Any = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = body.decode("utf-8", "replace")[-1000:]
        return {
            "action": "probe",
            "kind": kind,
            "http_status": error.code,
            "error": detail,
            "matches_logical_identity": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("seed", "inspect", "probe", "corrupt", "backup", "restore")
    )
    parser.add_argument("--kind", choices=("pe", "pdb"), default="pdb")
    parser.add_argument("--archive", type=Path, default=BACKUP_ROOT / "blob-objects.tar")
    args = parser.parse_args()
    settings = Settings()
    actions = {
        "seed": lambda: seed(settings),
        "inspect": lambda: inspect_seed(settings),
        "probe": lambda: probe(settings, args.kind),
        "corrupt": lambda: corrupt(settings, args.kind),
        "backup": lambda: backup_objects(settings, args.archive),
        "restore": lambda: restore_objects(settings, args.archive),
    }
    result = actions[args.action]()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
