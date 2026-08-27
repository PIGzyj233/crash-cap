from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ..ids import new_id
from ..metrics import ARTIFACT_BLOB_BACKFILL_OUTCOMES
from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobBackfillGap,
    ArtifactBlobLegacyCopy,
    ArtifactBlobPair,
    Build,
)
from ..object_keys import artifact_blob_key
from ..storage import ObjectNotFoundError, ObjectStore, stream_sha256
from .artifact_payloads import (
    ArtifactPayloadError,
    BlobMaterializer,
    artifact_blob_from_snapshot,
    artifact_blob_snapshot,
    configure_identity_payload,
    payload_object_key,
)
from .common import operation_log


@dataclass(frozen=True)
class _Candidate:
    artifact_id: str
    workspace_id: str
    build_id: str
    module_id: str | None
    kind: str
    logical_name: str
    sha256: str
    size: int
    object_key: str
    legacy_object_key: str | None
    artifact_blob_id: str | None
    artifact_blob: dict[str, Any] | None


@dataclass(frozen=True)
class _Prepared:
    candidate: _Candidate
    source_key: str | None
    identity: dict[str, Any] | None
    gap_reason: str | None
    gap_detail: str | None


def backfill_artifact_blobs(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    core: CoreExecutor,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    """Verify historical PE/PDB bytes before linking Workspace-scoped Blobs."""

    batch_limit = max(1, min(limit, 10_000))
    with sessions() as session:
        query = (
            select(Artifact, Build, ArtifactBlobLegacyCopy, ArtifactBlob)
            .join(Build, Build.id == Artifact.build_id)
            .outerjoin(ArtifactBlobLegacyCopy, ArtifactBlobLegacyCopy.artifact_id == Artifact.id)
            .outerjoin(ArtifactBlob, ArtifactBlob.id == Artifact.artifact_blob_id)
            .where(
                Artifact.kind.in_(["pe", "pdb"]),
                Artifact.verification_status == "verified",
            )
            .order_by(Artifact.id)
        )
        if after:
            query = query.where(Artifact.id > after)
        rows = session.execute(query.limit(batch_limit + 1)).all()
        candidates = [
            _Candidate(
                artifact_id=artifact.id,
                workspace_id=build.workspace_id,
                build_id=build.id,
                module_id=artifact.module_id,
                kind=artifact.kind,
                logical_name=artifact.logical_name,
                sha256=artifact.sha256.lower(),
                size=artifact.size,
                object_key=artifact.object_key,
                legacy_object_key=legacy.object_key if legacy is not None else None,
                artifact_blob_id=artifact.artifact_blob_id,
                artifact_blob=artifact_blob_snapshot(blob) if blob is not None else None,
            )
            for artifact, build, legacy, blob in rows[:batch_limit]
        ]
        has_more = len(rows) > batch_limit

    cases: list[dict[str, Any]] = []
    linked = already_linked = gaps = 0
    for candidate in candidates:
        prepared = _prepare(candidate, store, core)
        if prepared.gap_reason is not None:
            outcome = "gap"
            if apply:
                _record_prepared_gap(sessions, prepared)
            gaps += 1
        elif apply:
            outcome = _apply_prepared(sessions, store, prepared)
            gaps += int(outcome == "gap")
            linked += int(outcome == "linked")
            already_linked += int(outcome == "already_linked")
        else:
            outcome = "already_linked" if candidate.artifact_blob_id else "would_link"
            linked += int(outcome == "would_link")
            already_linked += int(outcome == "already_linked")
        ARTIFACT_BLOB_BACKFILL_OUTCOMES.labels(outcome).inc()
        cases.append(
            {
                "artifact_id": candidate.artifact_id,
                "workspace_id": candidate.workspace_id,
                "kind": candidate.kind,
                "sha256": candidate.sha256,
                "outcome": outcome,
                "gap_reason": prepared.gap_reason,
                "gap_detail": prepared.gap_detail,
            }
        )

    with sessions() as session:
        unresolved_gaps = int(
            session.scalar(
                select(func.count())
                .select_from(ArtifactBlobBackfillGap)
                .where(ArtifactBlobBackfillGap.resolved_at.is_(None))
            )
            or 0
        )
    return {
        "schema_version": "artifact-blob-backfill-v1",
        "mode": "apply" if apply else "dry-run",
        "input_cursor": after,
        "next_cursor": candidates[-1].artifact_id if candidates else after,
        "limit": batch_limit,
        "has_more": has_more,
        "scanned": len(candidates),
        "linked": linked,
        "already_linked": already_linked,
        "gaps": gaps,
        "unresolved_gaps": unresolved_gaps,
        "cases": cases,
    }


def cleanup_artifact_blob_legacy_copies(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    """Delete only recorded legacy copies; canonical shared Blobs are excluded."""

    batch_limit = max(1, min(limit, 10_000))
    with sessions() as session:
        query = (
            select(ArtifactBlobLegacyCopy, ArtifactBlob)
            .join(ArtifactBlob, ArtifactBlob.id == ArtifactBlobLegacyCopy.artifact_blob_id)
            .where(ArtifactBlobLegacyCopy.deleted_at.is_(None))
            .order_by(ArtifactBlobLegacyCopy.artifact_id)
        )
        if after:
            query = query.where(ArtifactBlobLegacyCopy.artifact_id > after)
        rows = session.execute(query.limit(batch_limit + 1)).all()
        candidates = rows[:batch_limit]
        has_more = len(rows) > batch_limit

    cases: list[dict[str, Any]] = []
    deleted = skipped = 0
    for legacy, blob in candidates:
        outcome = "would_delete"
        reason: str | None = None
        if legacy.object_key == blob.object_key or legacy.object_key.startswith("artifact-blobs/"):
            outcome, reason = "skipped", "canonical_key_is_never_legacy_cleanup"
        elif apply:
            with sessions() as session:
                locked = session.scalar(
                    select(ArtifactBlobLegacyCopy)
                    .where(ArtifactBlobLegacyCopy.artifact_id == legacy.artifact_id)
                    .with_for_update()
                )
                current_blob = session.get(ArtifactBlob, legacy.artifact_blob_id)
                referenced = int(
                    session.scalar(
                        select(func.count())
                        .select_from(Artifact)
                        .where(Artifact.object_key == legacy.object_key)
                    )
                    or 0
                )
                if (
                    locked is None
                    or locked.deleted_at is not None
                    or current_blob is None
                    or locked.object_key == current_blob.object_key
                    or referenced
                ):
                    outcome, reason = "skipped", "state_changed_or_still_referenced"
                    session.rollback()
                else:
                    store.delete(locked.object_key)
                    locked.deleted_at = datetime.now(UTC)
                    operation_log(
                        session,
                        action="artifact_blob.legacy_copy_delete",
                        target_type="artifact",
                        target_id=locked.artifact_id,
                        workspace_id=current_blob.workspace_id,
                        result="deleted",
                        details={"artifact_blob_id": current_blob.id},
                    )
                    session.commit()
                    outcome = "deleted"
        deleted += int(outcome in {"deleted", "would_delete"})
        skipped += int(outcome == "skipped")
        cases.append(
            {
                "artifact_id": legacy.artifact_id,
                "artifact_blob_id": legacy.artifact_blob_id,
                "outcome": outcome,
                "reason": reason,
            }
        )
    return {
        "schema_version": "artifact-blob-legacy-cleanup-v1",
        "mode": "apply" if apply else "dry-run",
        "input_cursor": after,
        "next_cursor": candidates[-1][0].artifact_id if candidates else after,
        "limit": batch_limit,
        "has_more": has_more,
        "scanned": len(candidates),
        "deleted_or_would_delete": deleted,
        "skipped": skipped,
        "cases": cases,
    }


def _prepare(candidate: _Candidate, store: ObjectStore, core: CoreExecutor) -> _Prepared:
    if candidate.artifact_blob is not None:
        try:
            prefix = f"artifact-backfill-{candidate.artifact_id}-"
            with tempfile.TemporaryDirectory(prefix=prefix) as raw:
                path = Path(raw) / candidate.logical_name
                BlobMaterializer(store, Path(raw)).materialize(
                    artifact_blob_from_snapshot(candidate.artifact_blob), path
                )
                identity = core.identify_artifact(path, candidate.kind)
        except (ObjectNotFoundError, ArtifactPayloadError) as error:
            fallback = _prepare_identity_blob_repair(candidate, store, core)
            if fallback is not None:
                return fallback
            if isinstance(error, ObjectNotFoundError):
                return _gap(candidate, "object_missing", "Artifact Blob payload is missing")
            return _gap(candidate, "object_corrupt", error.code)
        except CoreExecutionError as error:
            return _gap(candidate, "identity_rejected", error.code)
        except Exception as error:
            return _gap(candidate, "identity_failed", type(error).__name__)
        if str(identity.get("sha256", "")).lower() != candidate.sha256:
            return _gap(
                candidate,
                "identity_hash_mismatch",
                "identity output disagrees with the materialized Blob",
            )
        if candidate.kind == "pdb" and identity.get("is_fastlink"):
            return _gap(candidate, "fastlink", "historical PDB is FASTLINK")
        return _Prepared(candidate, None, identity, None, None)

    source_key: str | None = None
    saw_existing = False
    read_error: str | None = None
    for key in dict.fromkeys([candidate.object_key, candidate.legacy_object_key]):
        if key is None:
            continue
        try:
            digest, size, _prefix = stream_sha256(store, key)
        except ObjectNotFoundError:
            continue
        except Exception as error:
            read_error = type(error).__name__
            continue
        saw_existing = True
        if digest.lower() == candidate.sha256 and size == candidate.size:
            source_key = key
            break
    if source_key is None:
        if saw_existing:
            return _gap(
                candidate,
                "object_corrupt",
                "no current or retained legacy object matches the verified size and SHA-256",
            )
        if read_error is not None:
            return _gap(candidate, "object_read_failed", read_error)
        return _gap(
            candidate,
            "object_missing",
            "no current or retained legacy object exists",
        )

    try:
        prefix = f"artifact-backfill-{candidate.artifact_id}-"
        with tempfile.TemporaryDirectory(prefix=prefix) as raw:
            path = Path(raw) / candidate.logical_name
            store.download_file(source_key, path)
            identity = core.identify_artifact(path, candidate.kind)
    except ObjectNotFoundError:
        return _gap(candidate, "object_missing", "object disappeared during identity verification")
    except CoreExecutionError as error:
        return _gap(candidate, "identity_rejected", error.code)
    except Exception as error:
        return _gap(candidate, "identity_failed", type(error).__name__)
    if str(identity.get("sha256", "")).lower() != candidate.sha256:
        return _gap(
            candidate,
            "identity_hash_mismatch",
            "identity output disagrees with re-read bytes",
        )
    if candidate.kind == "pdb" and identity.get("is_fastlink"):
        return _gap(candidate, "fastlink", "historical PDB is FASTLINK")
    return _Prepared(candidate, source_key, identity, None, None)


def _apply_prepared(
    sessions: sessionmaker[Session], store: ObjectStore, prepared: _Prepared
) -> str:
    candidate = prepared.candidate
    assert prepared.identity is not None
    if candidate.artifact_blob_id is not None:
        if prepared.source_key is not None:
            snapshot = candidate.artifact_blob or {}
            if snapshot.get("payload_encoding") != "identity":
                failed = _gap(
                    candidate,
                    "compressed_payload_repair_requires_restore",
                    "A missing zstd payload cannot be repaired by copying raw bytes",
                )
                _record_prepared_gap(sessions, failed)
                return "gap"
            payload_key = str(snapshot.get("payload_object_key") or snapshot.get("object_key"))
            try:
                store.copy(prepared.source_key, payload_key)
                digest, size, _prefix = stream_sha256(store, payload_key)
            except Exception as error:
                failed = _gap(candidate, "canonical_copy_failed", type(error).__name__)
                _record_prepared_gap(sessions, failed)
                return "gap"
            if digest != candidate.sha256 or size != candidate.size:
                failed = _gap(
                    candidate,
                    "canonical_copy_verification_failed",
                    "repaired identity payload did not match the Artifact Blob",
                )
                _record_prepared_gap(sessions, failed)
                return "gap"
        with sessions() as session:
            artifact = session.get(Artifact, candidate.artifact_id)
            blob = session.get(ArtifactBlob, candidate.artifact_blob_id)
            conflict = _blob_conflict(blob, candidate, prepared.identity)
            if (
                artifact is None
                or blob is None
                or artifact.artifact_blob_id != blob.id
                or blob.verification_status != "verified"
                or conflict is not None
            ):
                failed = _gap(
                    candidate,
                    "state_changed",
                    conflict or "Artifact Blob binding changed before apply",
                )
                _record_gap(session, failed)
                session.commit()
                return "gap"
            gap = session.get(ArtifactBlobBackfillGap, artifact.id)
            if gap is not None:
                gap.resolved_at = datetime.now(UTC)
                gap.last_seen_at = gap.resolved_at
            session.commit()
            return "already_linked"
    assert prepared.source_key is not None
    canonical_key = artifact_blob_key(candidate.workspace_id, candidate.sha256)
    try:
        try:
            canonical_digest, canonical_size, _prefix = stream_sha256(store, canonical_key)
        except ObjectNotFoundError:
            canonical_digest, canonical_size = "", -1
        if canonical_digest != candidate.sha256 or canonical_size != candidate.size:
            store.copy(prepared.source_key, canonical_key)
            canonical_digest, canonical_size, _prefix = stream_sha256(store, canonical_key)
        if canonical_digest != candidate.sha256 or canonical_size != candidate.size:
            failed = _gap(
                candidate,
                "canonical_copy_verification_failed",
                "canonical object did not match after copy",
            )
            _record_prepared_gap(sessions, failed)
            return "gap"
    except Exception as error:
        failed = _gap(candidate, "canonical_copy_failed", type(error).__name__)
        _record_prepared_gap(sessions, failed)
        return "gap"

    with sessions() as session:
        artifact = session.scalar(
            select(Artifact).where(Artifact.id == candidate.artifact_id).with_for_update()
        )
        build = session.get(Build, candidate.build_id)
        if (
            artifact is None
            or build is None
            or build.workspace_id != candidate.workspace_id
            or artifact.verification_status != "verified"
            or artifact.kind != candidate.kind
            or artifact.size != candidate.size
            or artifact.sha256.lower() != candidate.sha256
        ):
            failed = _gap(candidate, "state_changed", "Artifact changed before apply")
            _record_gap(session, failed)
            session.commit()
            return "gap"
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": (f"artifact-blob:{candidate.workspace_id}:{candidate.sha256}")},
            )
        blob = session.scalar(
            select(ArtifactBlob)
            .where(
                ArtifactBlob.workspace_id == candidate.workspace_id,
                ArtifactBlob.sha256 == candidate.sha256,
            )
            .with_for_update()
        )
        conflict = _blob_conflict(blob, candidate, prepared.identity)
        if conflict:
            failed = _gap(candidate, "identity_conflict", conflict)
            _record_gap(session, failed)
            session.commit()
            return "gap"
        now = datetime.now(UTC)
        if blob is None:
            blob = ArtifactBlob(
                id=new_id("abl"),
                workspace_id=candidate.workspace_id,
                sha256=candidate.sha256,
                kind=candidate.kind,
                size=candidate.size,
                object_key=canonical_key,
                code_id=prepared.identity.get("code_id"),
                debug_id=prepared.identity.get("debug_id"),
                verification_status="verified",
                verified_at=now,
                updated_at=now,
            )
            configure_identity_payload(blob)
            session.add(blob)
            session.flush()
        else:
            blob.object_key = canonical_key
            blob.code_id = prepared.identity.get("code_id")
            blob.debug_id = prepared.identity.get("debug_id")
            blob.verification_status = "verified"
            blob.verification_reason = None
            blob.verified_at = now
            blob.updated_at = now
            if blob.payload_encoding != "zstd-v1":
                configure_identity_payload(blob)
        was_linked = artifact.artifact_blob_id == blob.id
        old_key = artifact.object_key
        if old_key != canonical_key and session.get(ArtifactBlobLegacyCopy, artifact.id) is None:
            session.add(
                ArtifactBlobLegacyCopy(
                    artifact_id=artifact.id,
                    artifact_blob_id=blob.id,
                    object_key=old_key,
                )
            )
        artifact.artifact_blob_id = blob.id
        artifact.materialization_source = "backfill"
        artifact.object_key = payload_object_key(blob)
        artifact.code_id = blob.code_id
        artifact.debug_id = blob.debug_id
        _backfill_historical_pair(session, artifact, now)
        gap = session.get(ArtifactBlobBackfillGap, artifact.id)
        if gap is not None:
            gap.resolved_at = now
            gap.last_seen_at = now
        operation_log(
            session,
            action="artifact_blob.backfill",
            target_type="artifact",
            target_id=artifact.id,
            workspace_id=candidate.workspace_id,
            result="already_linked" if was_linked else "linked",
            details={"artifact_blob_id": blob.id, "kind": blob.kind},
        )
        session.commit()
        return "already_linked" if was_linked else "linked"


def _prepare_identity_blob_repair(
    candidate: _Candidate, store: ObjectStore, core: CoreExecutor
) -> _Prepared | None:
    snapshot = candidate.artifact_blob or {}
    source_key = candidate.legacy_object_key
    if snapshot.get("payload_encoding") != "identity" or source_key is None:
        return None
    try:
        digest, size, _prefix = stream_sha256(store, source_key)
        if digest != candidate.sha256 or size != candidate.size:
            return None
        prefix = f"artifact-backfill-repair-{candidate.artifact_id}-"
        with tempfile.TemporaryDirectory(prefix=prefix) as raw:
            path = Path(raw) / candidate.logical_name
            store.download_file(source_key, path)
            identity = core.identify_artifact(path, candidate.kind)
    except (ObjectNotFoundError, CoreExecutionError):
        return None
    if str(identity.get("sha256", "")).lower() != candidate.sha256:
        return None
    if candidate.kind == "pdb" and identity.get("is_fastlink"):
        return None
    return _Prepared(candidate, source_key, identity, None, None)


def _backfill_historical_pair(session: Session, artifact: Artifact, now: datetime) -> None:
    if artifact.module_id is None:
        return
    other_kind = "pdb" if artifact.kind == "pe" else "pe"
    counterpart = session.scalar(
        select(Artifact)
        .where(
            Artifact.build_id == artifact.build_id,
            Artifact.module_id == artifact.module_id,
            Artifact.kind == other_kind,
            Artifact.verification_status == "verified",
            Artifact.artifact_blob_id.is_not(None),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    if counterpart is None:
        return
    pe = artifact if artifact.kind == "pe" else counterpart
    pdb = artifact if artifact.kind == "pdb" else counterpart
    build = session.get(Build, artifact.build_id)
    if build is None or pe.artifact_blob_id is None or pdb.artifact_blob_id is None:
        return
    pair = session.scalar(
        select(ArtifactBlobPair).where(
            ArtifactBlobPair.workspace_id == build.workspace_id,
            ArtifactBlobPair.pe_blob_id == pe.artifact_blob_id,
            ArtifactBlobPair.pdb_blob_id == pdb.artifact_blob_id,
        )
    )
    matches = bool(pe.debug_id and pdb.debug_id and pe.debug_id.lower() == pdb.debug_id.lower())
    if pair is None:
        pair = ArtifactBlobPair(
            id=new_id("abp"),
            workspace_id=build.workspace_id,
            pe_blob_id=pe.artifact_blob_id,
            pdb_blob_id=pdb.artifact_blob_id,
            state="published" if matches else "rejected",
            rejection_reason=None if matches else "debug_id_mismatch",
            published_at=now if matches else None,
            updated_at=now,
        )
        session.add(pair)
    elif pair.state == "pending":
        pair.state = "published" if matches else "rejected"
        pair.rejection_reason = None if matches else "debug_id_mismatch"
        pair.published_at = now if matches else None
        pair.updated_at = now


def _blob_conflict(
    blob: ArtifactBlob | None, candidate: _Candidate, identity: dict[str, Any]
) -> str | None:
    if blob is None:
        return None
    if blob.kind != candidate.kind:
        return "Workspace+SHA has a different kind"
    if blob.size != candidate.size:
        return "Workspace+SHA has a different size"
    for field in ("code_id", "debug_id"):
        old = getattr(blob, field)
        new = identity.get(field)
        if old and new and old.lower() != str(new).lower():
            return f"Workspace+SHA has a different {field}"
    return None


def _record_prepared_gap(sessions: sessionmaker[Session], prepared: _Prepared) -> None:
    with sessions() as session:
        _record_gap(session, prepared)
        session.commit()


def _record_gap(session: Session, prepared: _Prepared) -> None:
    candidate = prepared.candidate
    # The candidate list is deliberately read outside the apply transaction.
    # If an operator deleted the Artifact in between, its FK-backed gap row can
    # no longer be persisted; the current batch report still returns the gap.
    if session.get(Artifact, candidate.artifact_id) is None:
        return
    now = datetime.now(UTC)
    gap = session.get(ArtifactBlobBackfillGap, candidate.artifact_id)
    if gap is None:
        session.add(
            ArtifactBlobBackfillGap(
                artifact_id=candidate.artifact_id,
                workspace_id=candidate.workspace_id,
                reason=prepared.gap_reason or "unknown",
                detail=(prepared.gap_detail or "")[:2000] or None,
                attempt_count=1,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
        return
    gap.workspace_id = candidate.workspace_id
    gap.reason = prepared.gap_reason or "unknown"
    gap.detail = (prepared.gap_detail or "")[:2000] or None
    gap.attempt_count += 1
    gap.last_seen_at = now
    gap.resolved_at = None


def _gap(candidate: _Candidate, reason: str, detail: str) -> _Prepared:
    return _Prepared(candidate, None, None, reason, detail[:2000])
