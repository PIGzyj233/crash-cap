from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPayloadBackfillGap,
    ArtifactBlobPayloadLegacyCopy,
)
from ..object_keys import artifact_blob_payload_key
from ..storage import ObjectStore
from .artifact_payloads import (
    ArtifactBlobCodec,
    ArtifactPayloadError,
    BlobMaterializer,
    PayloadDigest,
    artifact_blob_snapshot,
    configure_zstd_payload,
    payload_object_key,
)
from .common import operation_log
from .symbol_catalog import protects_object


@dataclass(frozen=True)
class PreparedPayload:
    blob_id: str
    workspace_id: str
    kind: str
    raw_size: int
    raw_sha256: str
    current_snapshot: dict[str, Any]
    payload_key: str
    payload: PayloadDigest | None
    encoded_path: Path | None
    gap_reason: str | None
    gap_detail: str | None


def backfill_artifact_blob_payloads(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    batch_limit = max(1, min(limit, 10_000))
    with sessions() as session:
        query = (
            select(ArtifactBlob)
            .where(ArtifactBlob.verification_status == "verified")
            .order_by(ArtifactBlob.id)
        )
        if after:
            query = query.where(ArtifactBlob.id > after)
        rows = session.scalars(query.limit(batch_limit + 1)).all()
        snapshots = [artifact_blob_snapshot(blob) for blob in rows[:batch_limit]]
        has_more = len(rows) > batch_limit

    cases: list[dict[str, Any]] = []
    compressed = already_zstd = gaps = 0
    for snapshot in snapshots:
        if snapshot["payload_encoding"] == "zstd-v1":
            try:
                with tempfile.TemporaryDirectory(
                    prefix="payload-backfill-check-", dir=_temp_root(settings)
                ) as raw:
                    BlobMaterializer(store, settings.task_tmp_root).materialize(
                        _snapshot_blob(snapshot), Path(raw) / f"artifact.{snapshot['kind']}"
                    )
                outcome, reason = "already_zstd", None
                already_zstd += 1
                if apply:
                    _resolve_gap(sessions, str(snapshot["id"]))
            except Exception as error:
                outcome, reason = "gap", _error_code(error)
                gaps += 1
                if apply:
                    _record_gap(sessions, snapshot, reason, type(error).__name__)
            cases.append(_payload_case(snapshot, outcome, reason, None))
            continue

        with tempfile.TemporaryDirectory(
            prefix="payload-backfill-", dir=_temp_root(settings)
        ) as raw:
            prepared = _prepare_payload(store, settings, snapshot, Path(raw))
            if prepared.gap_reason is not None:
                outcome = "gap"
                gaps += 1
                if apply:
                    _record_gap(
                        sessions,
                        snapshot,
                        prepared.gap_reason,
                        prepared.gap_detail,
                    )
            elif apply:
                outcome = _apply_payload(sessions, store, settings, prepared)
                compressed += int(outcome == "compressed")
                already_zstd += int(outcome == "already_zstd")
                gaps += int(outcome == "gap")
            else:
                outcome = "would_compress"
                compressed += 1
            ratio = (
                prepared.payload.payload_size / prepared.raw_size
                if prepared.payload is not None
                else None
            )
            cases.append(_payload_case(snapshot, outcome, prepared.gap_reason, ratio))

    with sessions() as session:
        unresolved = int(
            session.scalar(
                select(func.count())
                .select_from(ArtifactBlobPayloadBackfillGap)
                .where(ArtifactBlobPayloadBackfillGap.resolved_at.is_(None))
            )
            or 0
        )
    return {
        "schema_version": "artifact-blob-payload-backfill-v1",
        "mode": "apply" if apply else "dry-run",
        "input_cursor": after,
        "next_cursor": snapshots[-1]["id"] if snapshots else after,
        "limit": batch_limit,
        "has_more": has_more,
        "scanned": len(snapshots),
        "compressed_or_would_compress": compressed,
        "already_zstd": already_zstd,
        "gaps": gaps,
        "unresolved_gaps": unresolved,
        "cases": cases,
    }


def cleanup_artifact_blob_raw_payloads(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    *,
    now: datetime | None = None,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    cutoff = _aware(now or datetime.now(UTC))
    batch_limit = max(1, min(limit, 10_000))
    with sessions() as session:
        query = (
            select(ArtifactBlobPayloadLegacyCopy, ArtifactBlob)
            .join(ArtifactBlob, ArtifactBlob.id == ArtifactBlobPayloadLegacyCopy.artifact_blob_id)
            .where(
                ArtifactBlobPayloadLegacyCopy.deleted_at.is_(None),
                ArtifactBlobPayloadLegacyCopy.retained_until <= cutoff,
            )
            .order_by(ArtifactBlobPayloadLegacyCopy.artifact_blob_id)
        )
        if after:
            query = query.where(ArtifactBlobPayloadLegacyCopy.artifact_blob_id > after)
        rows = session.execute(query.limit(batch_limit + 1)).all()
        candidates = rows[:batch_limit]
        has_more = len(rows) > batch_limit

    cases: list[dict[str, Any]] = []
    deleted = skipped = 0
    for legacy, blob in candidates:
        outcome, reason = _raw_cleanup_eligibility(sessions, store, settings, legacy, blob)
        if outcome == "would_delete" and apply:
            with sessions() as session:
                current = session.scalar(
                    select(ArtifactBlob)
                    .where(ArtifactBlob.id == legacy.artifact_blob_id)
                    .with_for_update()
                )
                locked = session.scalar(
                    select(ArtifactBlobPayloadLegacyCopy)
                    .where(
                        ArtifactBlobPayloadLegacyCopy.artifact_blob_id == legacy.artifact_blob_id
                    )
                    .with_for_update()
                )
                if (
                    locked is None
                    or locked.deleted_at is not None
                    or current is None
                    or current.payload_encoding != "zstd-v1"
                    or locked.object_key == payload_object_key(current)
                    or protects_object(session, locked.object_key)
                ):
                    session.rollback()
                    outcome, reason = "fenced", "state_changed_before_delete"
                else:
                    store.delete(locked.object_key)
                    locked.deleted_at = cutoff
                    locked.deletion_reason = "rollback_window_complete"
                    operation_log(
                        session,
                        action="artifact_blob.raw_payload_delete",
                        target_type="artifact_blob",
                        target_id=current.id,
                        workspace_id=current.workspace_id,
                        result="deleted",
                        details={"kind": current.kind, "bytes": locked.size},
                    )
                    session.commit()
                    outcome = "deleted"
        deleted += int(outcome in {"deleted", "would_delete"})
        skipped += int(outcome not in {"deleted", "would_delete"})
        cases.append(
            {
                "artifact_blob_id": blob.id,
                "workspace_id": blob.workspace_id,
                "kind": blob.kind,
                "bytes": legacy.size,
                "outcome": outcome,
                "reason": reason,
            }
        )
    return {
        "schema_version": "artifact-blob-raw-payload-cleanup-v1",
        "mode": "apply" if apply else "dry-run",
        "input_cursor": after,
        "next_cursor": candidates[-1][0].artifact_blob_id if candidates else after,
        "limit": batch_limit,
        "has_more": has_more,
        "scanned": len(candidates),
        "deleted_or_would_delete": deleted,
        "skipped": skipped,
        "cases": cases,
    }


def _prepare_payload(
    store: ObjectStore, settings: Settings, snapshot: dict[str, Any], root: Path
) -> PreparedPayload:
    payload_key = artifact_blob_payload_key(
        str(snapshot["workspace_id"]), str(snapshot["sha256"]), "zstd-v1"
    )
    raw_path = root / f"artifact.{snapshot['kind']}"
    encoded_path = root / "payload.zst"
    decoded_path = root / f"decoded.{snapshot['kind']}"
    try:
        blob = _snapshot_blob(snapshot)
        BlobMaterializer(store, settings.task_tmp_root).materialize(blob, raw_path)
        payload = ArtifactBlobCodec().encode_file(
            raw_path,
            encoded_path,
            kind=str(snapshot["kind"]),
            encoding="zstd-v1",
            expected_raw_size=int(snapshot["size"]),
            expected_raw_sha256=str(snapshot["sha256"]),
        )
        ArtifactBlobCodec().decode_file(
            encoded_path,
            decoded_path,
            kind=str(snapshot["kind"]),
            encoding="zstd-v1",
            expected_raw_size=int(snapshot["size"]),
            expected_raw_sha256=str(snapshot["sha256"]),
        )
        return PreparedPayload(
            str(snapshot["id"]),
            str(snapshot["workspace_id"]),
            str(snapshot["kind"]),
            int(snapshot["size"]),
            str(snapshot["sha256"]),
            snapshot,
            payload_key,
            payload,
            encoded_path,
            None,
            None,
        )
    except Exception as error:
        return PreparedPayload(
            str(snapshot["id"]),
            str(snapshot["workspace_id"]),
            str(snapshot["kind"]),
            int(snapshot["size"]),
            str(snapshot["sha256"]),
            snapshot,
            payload_key,
            None,
            None,
            _error_code(error),
            type(error).__name__,
        )


def _apply_payload(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    prepared: PreparedPayload,
) -> str:
    assert prepared.payload is not None and prepared.encoded_path is not None
    try:
        store.put_file(prepared.payload_key, prepared.encoded_path, "application/zstd")
        candidate = _snapshot_blob(
            {
                **prepared.current_snapshot,
                "payload_encoding": "zstd-v1",
                "payload_size": prepared.payload.payload_size,
                "payload_sha256": prepared.payload.payload_sha256,
                "payload_object_key": prepared.payload_key,
            }
        )
        with tempfile.TemporaryDirectory(
            prefix="payload-backfill-readback-", dir=_temp_root(settings)
        ) as raw:
            BlobMaterializer(store, settings.task_tmp_root).materialize(
                candidate, Path(raw) / f"artifact.{prepared.kind}"
            )
    except Exception as error:
        _record_gap(
            sessions,
            prepared.current_snapshot,
            _error_code(error),
            type(error).__name__,
        )
        return "gap"

    with sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(ArtifactBlob.id == prepared.blob_id).with_for_update()
        )
        if blob is None or blob.verification_status != "verified":
            session.rollback()
            _record_gap(
                sessions,
                prepared.current_snapshot,
                "state_changed",
                "Artifact Blob changed before payload apply",
            )
            return "gap"
        if blob.payload_encoding == "zstd-v1":
            session.rollback()
            _resolve_gap(sessions, blob.id)
            return "already_zstd"
        if blob.sha256 != prepared.raw_sha256 or blob.size != prepared.raw_size:
            session.rollback()
            _record_gap(
                sessions,
                prepared.current_snapshot,
                "identity_changed",
                "Artifact Blob raw identity changed before payload apply",
            )
            return "gap"
        now = datetime.now(UTC)
        if session.get(ArtifactBlobPayloadLegacyCopy, blob.id) is None:
            session.add(
                ArtifactBlobPayloadLegacyCopy(
                    artifact_blob_id=blob.id,
                    object_key=blob.object_key,
                    size=blob.size,
                    sha256=blob.sha256,
                    retained_until=now + timedelta(days=settings.artifact_payload_rollback_days),
                )
            )
        configure_zstd_payload(
            blob,
            object_key=prepared.payload_key,
            payload=prepared.payload,
            verified_at=now,
        )
        session.execute(
            update(Artifact)
            .where(Artifact.artifact_blob_id == blob.id)
            .values(object_key=prepared.payload_key)
        )
        gap = session.get(ArtifactBlobPayloadBackfillGap, blob.id)
        if gap is not None:
            gap.resolved_at = now
            gap.last_seen_at = now
        operation_log(
            session,
            action="artifact_blob.payload_backfill",
            target_type="artifact_blob",
            target_id=blob.id,
            workspace_id=blob.workspace_id,
            result="compressed",
            details={
                "kind": blob.kind,
                "logical_bytes": blob.size,
                "stored_bytes": blob.payload_size,
                "encoding": blob.payload_encoding,
            },
        )
        session.commit()
    return "compressed"


def _raw_cleanup_eligibility(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    legacy: ArtifactBlobPayloadLegacyCopy,
    blob: ArtifactBlob,
) -> tuple[str, str | None]:
    if blob.payload_encoding != "zstd-v1" or blob.verification_status != "verified":
        return "skipped", "current_payload_not_verified_zstd"
    if legacy.object_key == payload_object_key(blob) or not legacy.object_key.startswith(
        "artifact-blobs/"
    ):
        return "skipped", "legacy_key_not_exact_raw_canonical"
    with sessions() as session:
        if protects_object(session, legacy.object_key):
            return "skipped", "catalog_retention_reference"
        referenced = int(
            session.scalar(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.object_key == legacy.object_key)
            )
            or 0
        )
    if referenced:
        return "skipped", "raw_object_still_referenced"
    try:
        with tempfile.TemporaryDirectory(
            prefix="payload-cleanup-check-", dir=_temp_root(settings)
        ) as raw:
            BlobMaterializer(store, settings.task_tmp_root).materialize(
                blob, Path(raw) / f"artifact.{blob.kind}"
            )
    except Exception as error:
        return "skipped", f"materialize_{_error_code(error)}"
    return "would_delete", None


def _record_gap(
    sessions: sessionmaker[Session], snapshot: dict[str, Any], reason: str, detail: str | None
) -> None:
    now = datetime.now(UTC)
    with sessions() as session:
        gap = session.get(ArtifactBlobPayloadBackfillGap, str(snapshot["id"]))
        if gap is None:
            gap = ArtifactBlobPayloadBackfillGap(
                artifact_blob_id=str(snapshot["id"]),
                workspace_id=str(snapshot["workspace_id"]),
                reason=reason,
                detail=detail,
                last_seen_at=now,
            )
            session.add(gap)
        else:
            gap.reason = reason
            gap.detail = detail
            gap.attempt_count += 1
            gap.last_seen_at = now
            gap.resolved_at = None
        session.commit()


def _resolve_gap(sessions: sessionmaker[Session], blob_id: str) -> None:
    with sessions() as session:
        gap = session.get(ArtifactBlobPayloadBackfillGap, blob_id)
        if gap is not None and gap.resolved_at is None:
            gap.resolved_at = datetime.now(UTC)
            gap.last_seen_at = gap.resolved_at
            session.commit()


def _snapshot_blob(snapshot: dict[str, Any]) -> ArtifactBlob:
    from .artifact_payloads import artifact_blob_from_snapshot

    return artifact_blob_from_snapshot(snapshot)


def _payload_case(
    snapshot: dict[str, Any], outcome: str, reason: str | None, ratio: float | None
) -> dict[str, Any]:
    return {
        "artifact_blob_id": snapshot["id"],
        "workspace_id": snapshot["workspace_id"],
        "kind": snapshot["kind"],
        "raw_size": snapshot["size"],
        "outcome": outcome,
        "gap_reason": reason,
        "stored_ratio": round(ratio, 6) if ratio is not None else None,
    }


def _error_code(error: Exception) -> str:
    return error.code if isinstance(error, ArtifactPayloadError) else type(error).__name__


def _temp_root(settings: Settings) -> str:
    settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
    return str(settings.task_tmp_root)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
