"""Bounded, restartable admission of all historical complete symbol pairs."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from crashcap_worker.catalog_validation import inspect_catalog_pair, prepare_catalog_pair
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from sqlalchemy import and_, exists, func, literal, select, tuple_, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased, sessionmaker

from ..frozen_inputs import FrozenInputError, canonical_bytes, digest, normalize_identity
from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPair,
    Build,
    BuildModule,
    SymbolCatalogBackfill,
    utcnow,
)
from ..storage import ObjectNotFoundError, ObjectStore
from .artifact_payloads import ArtifactPayloadError, BlobMaterializer, artifact_blob_from_snapshot
from .symbol_catalog import CatalogError, OriginEvidence, admit_pair


def _cursor(after: str | None, retry_gaps: bool) -> dict[str, Any]:
    mode = "gaps" if retry_gaps else "scan"
    if after is None:
        return {"version": 1, "mode": mode, "before": utcnow().isoformat(), "after": None}
    try:
        if len(after) > 4096:
            raise ValueError("oversized cursor")
        value = json.loads(base64.urlsafe_b64decode(after.encode("ascii")))
        if (
            set(value) != {"version", "mode", "before", "after"}
            or value["version"] != 1
            or value["mode"] != mode
        ):
            raise ValueError("wrong cursor version or mode")
        before = datetime.fromisoformat(value["before"])
        if before.tzinfo is None:
            raise ValueError("cursor requires an aware cutoff")
        marker = value["after"]
        if marker is not None and (
            (mode == "gaps" and not isinstance(marker, str))
            or (
                mode == "scan"
                and (
                    not isinstance(marker, list)
                    or len(marker) != 3
                    or not all(isinstance(part, str) for part in marker)
                )
            )
        ):
            raise ValueError("invalid keyset marker")
        return dict(value)
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise ValueError("Invalid catalog backfill cursor") from error


def _encode_cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(canonical_bytes(value)).decode("ascii")


def _locators(session: Session, cursor: dict[str, Any], limit: int) -> list[tuple[list[str], Any]]:
    if cursor["mode"] == "gaps":
        query = select(SymbolCatalogBackfill).where(SymbolCatalogBackfill.outcome != "admitted")
        if cursor["after"]:
            query = query.where(SymbolCatalogBackfill.id > cursor["after"])
        return [
            (row.locator, row.id)
            for row in session.scalars(query.order_by(SymbolCatalogBackfill.id).limit(limit))
        ]
    before = datetime.fromisoformat(cursor["before"])
    pe, pdb = aliased(Artifact), aliased(Artifact)
    match = and_(
        pe.module_id.is_not(None),
        pe.build_id == pdb.build_id,
        pe.module_id == pdb.module_id,
        pdb.kind == "pdb",
        pdb.created_at <= before,
    )
    pair_rows = (
        select(
            literal("artifact").label("source"),
            pe.id.label("left_id"),
            func.coalesce(pdb.id, "").label("right_id"),
        )
        .select_from(pe)
        .outerjoin(pdb, match)
        .where(pe.kind == "pe", pe.created_at <= before)
    )
    orphan_pdbs = select(literal("artifact"), literal(""), pdb.id).where(
        pdb.kind == "pdb",
        pdb.created_at <= before,
        ~exists(
            select(pe.id).where(
                pe.kind == "pe",
                pe.created_at <= before,
                pe.module_id.is_not(None),
                pe.module_id == pdb.module_id,
                pe.build_id == pdb.build_id,
            )
        ),
    )
    publications = select(literal("publication"), ArtifactBlobPair.id, literal("")).where(
        ArtifactBlobPair.created_at <= before
    )
    inventory = union_all(pair_rows, orphan_pdbs, publications).subquery()
    query = select(inventory).order_by(
        inventory.c.source, inventory.c.left_id, inventory.c.right_id
    )
    if cursor["after"]:
        query = query.where(
            tuple_(inventory.c.source, inventory.c.left_id, inventory.c.right_id)
            > tuple(cursor["after"])
        )
    return [(list(row), list(row)) for row in session.execute(query.limit(limit))]


def _blob(blob: ArtifactBlob) -> dict[str, Any]:
    return {
        name: getattr(blob, name)
        for name in (
            "id",
            "workspace_id",
            "kind",
            "sha256",
            "size",
            "object_key",
            "code_id",
            "debug_id",
            "verification_status",
            "payload_object_key",
            "payload_encoding",
            "payload_sha256",
            "payload_size",
            "payload_format_version",
        )
    }


def _snapshot(session: Session, locator: list[str], *, lock: bool = False) -> dict[str, Any]:
    source, left, right = locator
    result: dict[str, Any] = {
        "locator": locator,
        "files": {},
        "reason": None,
        "workspace_id": None,
        "build_id": None,
        "module_id": None,
    }
    if source == "artifact":
        artifacts = session.scalars(
            select(Artifact).where(Artifact.id.in_([left, right])).order_by(Artifact.id)
        ).all()
        build = session.get(Build, artifacts[0].build_id) if artifacts else None
        if lock and build is not None:
            session.scalar(select(Build).where(Build.id == build.id).with_for_update())
            artifacts = session.scalars(
                select(Artifact)
                .where(Artifact.id.in_([left, right]))
                .order_by(Artifact.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        by_id = {row.id: row for row in artifacts}
        if build is None or not left or not right or set(by_id) != {left, right}:
            result["reason"] = "HISTORICAL_PAIR_INCOMPLETE"
        for kind, artifact_id in (("pe", left), ("pdb", right)):
            artifact = by_id.get(artifact_id)
            if artifact is None:
                continue
            file = {
                name: getattr(artifact, name)
                for name in (
                    "id",
                    "build_id",
                    "module_id",
                    "kind",
                    "sha256",
                    "size",
                    "object_key",
                    "artifact_blob_id",
                    "code_id",
                    "debug_id",
                    "verification_status",
                )
            }
            blob = (
                session.get(ArtifactBlob, artifact.artifact_blob_id)
                if artifact.artifact_blob_id
                else None
            )
            file["blob"] = _blob(blob) if blob is not None else None
            result["files"][kind] = file
            if artifact.verification_status != "verified":
                result["reason"] = "HISTORICAL_ARTIFACT_NOT_VERIFIED"
            if artifact.artifact_blob_id is not None and blob is None:
                result["reason"] = "HISTORICAL_BLOB_MISSING"
        if build is not None:
            result["workspace_id"], result["build_id"] = build.workspace_id, build.id
        pe, pdb = by_id.get(left), by_id.get(right)
        if pe is not None and pdb is not None:
            module = session.get(BuildModule, pe.module_id) if pe.module_id else None
            if (
                pe.kind != "pe"
                or pdb.kind != "pdb"
                or pe.build_id != pdb.build_id
                or pe.module_id is None
                or pe.module_id != pdb.module_id
                or module is None
                or module.build_id != pe.build_id
            ):
                result["reason"] = "HISTORICAL_PAIR_SCOPE_INVALID"
            result["module_id"] = pe.module_id
    elif source == "publication":
        statement = select(ArtifactBlobPair).where(ArtifactBlobPair.id == left)
        pair = session.scalar(statement.with_for_update() if lock else statement)
        if pair is None:
            result["reason"] = "HISTORICAL_PUBLICATION_MISSING"
            return result
        result["workspace_id"] = pair.workspace_id
        result["publication_state"] = pair.state
        if pair.state != "published":
            result["reason"] = "HISTORICAL_PAIR_NOT_PUBLISHED"
        for kind, blob_id in (("pe", pair.pe_blob_id), ("pdb", pair.pdb_blob_id)):
            blob = session.get(ArtifactBlob, blob_id)
            if blob is None:
                result["reason"] = "HISTORICAL_BLOB_MISSING"
                continue
            result["files"][kind] = {**_blob(blob), "blob": _blob(blob)}
    else:
        raise ValueError("Unknown historical locator type")
    for kind, file in result["files"].items():
        blob = file["blob"]
        if file["kind"] != kind:
            result["reason"] = "HISTORICAL_KIND_MISMATCH"
        if blob is not None and (
            blob["verification_status"] != "verified"
            or blob["workspace_id"] != result["workspace_id"]
            or blob["kind"] != kind
            or blob["sha256"].lower() != file["sha256"].lower()
            or blob["size"] != file["size"]
            or blob["payload_format_version"] != "artifact-blob-payload-v1"
        ):
            result["reason"] = "HISTORICAL_BLOB_METADATA_INVALID"
    return result


def _materialize(store: ObjectStore, file: dict[str, Any], destination: Path) -> None:
    limit = 512 * 1024**2 if file["kind"] == "pe" else 2 * 1024**3
    if not 0 < file["size"] <= limit:
        raise CoreExecutionError(
            "HISTORICAL_FILE_LIMIT", "Historical raw size exceeds the format limit"
        )
    if file["blob"] is not None:
        BlobMaterializer(store, destination.parent).materialize(
            artifact_blob_from_snapshot(file["blob"]), destination
        )
        return
    total, sha = 0, hashlib.sha256()
    with destination.open("xb") as target:
        for block in store.stream(file["object_key"]):
            total += len(block)
            if total > file["size"]:
                raise ArtifactPayloadError(
                    "raw_size_mismatch", "Historical object grew beyond recorded size"
                )
            sha.update(block)
            target.write(block)
    if total != file["size"] or sha.hexdigest() != file["sha256"].lower():
        raise ArtifactPayloadError(
            "raw_sha256_mismatch", "Historical raw bytes differ from the recorded identity"
        )


def _check_reports(snapshot: dict[str, Any], reports: dict[str, dict[str, object]]) -> None:
    for kind, file in snapshot["files"].items():
        actual = reports[kind]
        if (file["sha256"].lower(), file["size"]) != (actual["sha256"], actual["size"]):
            raise CoreExecutionError(
                "HISTORICAL_RAW_IDENTITY_MISMATCH",
                "Actual raw content disagrees with the historical artifact",
            )
        for recorded in (file, file["blob"]):
            if recorded is None:
                continue
            identity = normalize_identity(
                {
                    "code_id": recorded.get("code_id"),
                    "debug_id": recorded.get("debug_id"),
                    "architecture": "unknown",
                }
            )
            for field in ("code_id", "debug_id"):
                if identity[field] is not None and identity[field] != actual[field]:
                    raise CoreExecutionError(
                        "HISTORICAL_MODULE_IDENTITY_MISMATCH",
                        "Recorded module identity disagrees with actual bytes",
                    )


def _origin(snapshot: dict[str, Any]) -> OriginEvidence:
    return OriginEvidence(
        "build_artifacts" if snapshot["locator"][0] == "artifact" else "publication",
        digest(["catalog-history-origin-v1", snapshot["locator"]]),
        snapshot["workspace_id"],
        snapshot["build_id"],
        {
            "locator": snapshot["locator"],
            "module_id": snapshot["module_id"],
            "files": {
                kind: {
                    "id": file["id"],
                    "raw_sha256": file["sha256"].lower(),
                    "raw_size": file["size"],
                }
                for kind, file in snapshot["files"].items()
            },
        },
    )


def backfill_catalog(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    core: CoreExecutor,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
    retry_gaps: bool = False,
) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise ValueError("Catalog backfill page size must be between 1 and 200")
    if core.settings.core_executor == "fake":
        raise ValueError("Historical catalog validation requires a real Core")
    if apply and (
        not core.settings.symbol_imports_enabled or core.settings.environment == "production"
    ):
        raise ValueError(
            "Catalog backfill writes require the non-production symbol import qualification flag"
        )
    cursor = _cursor(after, retry_gaps)
    with sessions() as session:
        targets = _locators(session, cursor, limit + 1)
    cases = []
    for locator, marker in targets[:limit]:
        record_id = digest(["catalog-backfill-v1", locator])
        with sessions() as session:
            snapshot = _snapshot(session, locator)
            previous = session.get(SymbolCatalogBackfill, record_id)
            fingerprint = digest(snapshot)
            if (
                apply
                and previous is not None
                and previous.outcome == "admitted"
                and previous.source_fingerprint == fingerprint
            ):
                cases.append(
                    {
                        "locator": locator,
                        "record_id": record_id,
                        "outcome": "already_admitted",
                        "pair_id": previous.pair_id,
                        "reason": None,
                    }
                )
                cursor["after"] = marker
                continue
        outcome, reason, pair_id = "rejected", snapshot["reason"], None
        prepared = None
        if reason is None:
            try:
                with tempfile.TemporaryDirectory(prefix="crashcap-history-") as temporary:
                    paths = {kind: Path(temporary) / kind for kind in ("pe", "pdb")}
                    for kind, path in paths.items():
                        _materialize(store, snapshot["files"][kind], path)
                    reports = inspect_catalog_pair(core, paths["pe"], paths["pdb"])
                    _check_reports(snapshot, reports)
                    pair_id = digest(["pair-v1", reports["pe"]["sha256"], reports["pdb"]["sha256"]])
                    if apply:
                        prepared = prepare_catalog_pair(core, store, paths["pe"], paths["pdb"])
                    outcome = "admitted" if apply else "would_admit"
            except Exception as error:
                pair_id = None
                reason = (
                    error.code
                    if isinstance(error, (CoreExecutionError, ArtifactPayloadError))
                    else "HISTORICAL_OBJECT_MISSING"
                    if isinstance(error, ObjectNotFoundError)
                    else "HISTORICAL_" + type(error).__name__.upper()
                )
                if isinstance(error, FrozenInputError):
                    reason = "HISTORICAL_MODULE_IDENTITY_INVALID"
                outcome = (
                    "rejected"
                    if reason
                    in {
                        "ARTIFACT_IDENTIFY_FAILED",
                        "CATALOG_PAIR_INVALID",
                        "HISTORICAL_MODULE_IDENTITY_MISMATCH",
                        "HISTORICAL_MODULE_IDENTITY_INVALID",
                        "HISTORICAL_RAW_IDENTITY_MISMATCH",
                        "HISTORICAL_FILE_LIMIT",
                    }
                    else "retryable"
                )
        if apply:
            with sessions.begin() as session:
                current = _snapshot(session, locator, lock=True)
                if digest(current) != fingerprint:
                    prepared, pair_id = None, None
                    outcome, reason = "retryable", "HISTORICAL_SOURCE_CHANGED"
                insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
                inserted = session.scalar(
                    insert(SymbolCatalogBackfill)
                    .values(
                        id=record_id,
                        locator=locator,
                        source_fingerprint=fingerprint,
                        outcome="retryable",
                        reason="ADMISSION_PENDING",
                        attempt_count=1,
                        checked_at=utcnow(),
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                    .returning(SymbolCatalogBackfill.id)
                )
                record = session.scalars(
                    select(SymbolCatalogBackfill)
                    .where(SymbolCatalogBackfill.id == record_id)
                    .with_for_update()
                ).one()
                if prepared is not None:
                    try:
                        with session.begin_nested():
                            pair = admit_pair(
                                session,
                                prepared.pe,
                                prepared.pdb,
                                prepared.locations,
                                _origin(snapshot),
                            )
                            pair_id = pair.id
                    except CatalogError:
                        outcome, reason, pair_id = "rejected", "CATALOG_ADMISSION_REJECTED", None
                record.source_fingerprint, record.outcome, record.pair_id, record.reason = (
                    fingerprint,
                    outcome,
                    pair_id,
                    reason,
                )
                record.attempt_count += int(inserted is None)
                record.checked_at = utcnow()
        cases.append(
            {
                "locator": locator,
                "record_id": record_id,
                "outcome": outcome,
                "pair_id": pair_id,
                "reason": reason,
            }
        )
        cursor["after"] = marker
    with sessions() as session:
        unresolved = (
            session.scalar(
                select(func.count())
                .select_from(SymbolCatalogBackfill)
                .where(SymbolCatalogBackfill.outcome != "admitted")
            )
            or 0
        )
    return {
        "schema_version": "catalog-backfill-v1",
        "mode": "apply" if apply else "dry-run",
        "cutoff": cursor["before"],
        "next_cursor": _encode_cursor(cursor),
        "has_more": len(targets) > limit,
        "scanned": len(cases),
        "unresolved_records": unresolved,
        "cases": cases,
    }
