from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..metrics import (
    METRICS_REFRESH_FAILURES,
    UPLOAD_PAYLOAD_GC,
    UPLOAD_PAYLOAD_GC_INELIGIBLE,
    UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_BYTES,
    UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_OBJECTS,
)
from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobUploadClaim,
    Build,
    DumpBlob,
    TaskExecution,
    Upload,
)
from ..storage import ObjectNotFoundError, ObjectStore
from .artifact_payloads import payload_head_valid
from .common import operation_log

TERMINAL_UPLOAD_STATES = {"ACCEPTED", "REJECTED", "QUARANTINED"}
UPLOAD_STORAGE_CONDITIONS = (
    "orphan",
    "missing_retained",
    "deleted_marker_present",
    "size_mismatch",
)


@dataclass(frozen=True)
class UploadGcEligibility:
    eligible: bool
    reason: str
    bytes: int


def sweep_terminal_upload_payloads(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    cutoff = _aware(now or datetime.now(UTC))
    batch_limit = max(1, min(limit, 10_000))
    accepted_before = cutoff - timedelta(hours=settings.artifact_upload_gc_accepted_hours)
    rejected_before = cutoff - timedelta(hours=settings.artifact_upload_gc_rejected_hours)
    with sessions() as session:
        candidates = session.scalars(
            select(Upload)
            .where(
                Upload.payload_deleted_at.is_(None),
                or_(
                    (
                        (Upload.verification_status == "ACCEPTED")
                        & (Upload.completed_at.is_not(None))
                        & (Upload.completed_at <= accepted_before)
                    ),
                    (
                        Upload.verification_status.in_(["REJECTED", "QUARANTINED"])
                        & (Upload.completed_at.is_not(None))
                        & (Upload.completed_at <= rejected_before)
                    ),
                ),
            )
            .order_by(Upload.completed_at, Upload.id)
            .limit(batch_limit)
        ).all()
        candidate_ids = [row.id for row in candidates]

    cases: list[dict[str, Any]] = []
    deleted = would_delete = skipped = failed = 0
    reclaimed_bytes = 0
    for upload_id in candidate_ids:
        if not apply:
            with sessions() as session:
                upload = session.get(Upload, upload_id)
                if upload is None:
                    continue
                eligibility = upload_payload_gc_eligibility(session, store, upload, cutoff)
            outcome = "would_delete" if eligibility.eligible else "skipped"
            would_delete += int(eligibility.eligible)
            skipped += int(not eligibility.eligible)
            reclaimed_bytes += eligibility.bytes if eligibility.eligible else 0
            cases.append(_case(upload, outcome, eligibility.reason, eligibility.bytes))
            UPLOAD_PAYLOAD_GC.labels(upload.file_kind, outcome).inc()
            if not eligibility.eligible:
                UPLOAD_PAYLOAD_GC_INELIGIBLE.labels(
                    upload.file_kind, eligibility.reason
                ).inc()
            continue

        token = uuid.uuid4().hex
        with sessions() as session:
            upload = session.scalar(select(Upload).where(Upload.id == upload_id).with_for_update())
            if upload is None:
                continue
            eligibility = upload_payload_gc_eligibility(session, store, upload, cutoff)
            if not eligibility.eligible:
                skipped += 1
                cases.append(_case(upload, "skipped", eligibility.reason, eligibility.bytes))
                UPLOAD_PAYLOAD_GC.labels(upload.file_kind, "skipped").inc()
                UPLOAD_PAYLOAD_GC_INELIGIBLE.labels(
                    upload.file_kind, eligibility.reason
                ).inc()
                session.rollback()
                continue
            upload.payload_delete_claim_token = token
            upload.payload_delete_lease_expires_at = cutoff + timedelta(
                seconds=settings.artifact_upload_gc_claim_seconds
            )
            upload.payload_deletion_attempts += 1
            upload.payload_delete_last_error = None
            session.commit()
            object_key = upload.object_key
            workspace_id = upload.workspace_id
            byte_count = eligibility.bytes
            attempt = upload.payload_deletion_attempts

        try:
            try:
                store.head(object_key)
                payload_present = True
            except ObjectNotFoundError:
                payload_present = False
            if payload_present:
                store.delete(object_key)
            elif attempt <= 1:
                raise ObjectNotFoundError(object_key)
            result = "deleted" if payload_present else "already_absent_after_retry"
            with sessions() as session:
                upload = session.scalar(
                    select(Upload).where(Upload.id == upload_id).with_for_update()
                )
                if upload is None or upload.payload_delete_claim_token != token:
                    failed += 1
                    cases.append(
                        {
                            "upload_id": upload_id,
                            "outcome": "fenced",
                            "reason": "claim_changed_after_delete",
                            "bytes": byte_count,
                        }
                    )
                    session.rollback()
                    continue
                upload.payload_deleted_at = cutoff
                upload.payload_deletion_reason = "terminal_retention_elapsed"
                upload.payload_delete_claim_token = None
                upload.payload_delete_lease_expires_at = None
                upload.payload_delete_last_error = None
                operation_log(
                    session,
                    action="upload.payload_delete",
                    target_type="upload",
                    target_id=upload.id,
                    workspace_id=workspace_id,
                    result=result,
                    details={"file_kind": upload.file_kind, "bytes": byte_count},
                )
                session.commit()
                deleted += 1
                reclaimed_bytes += byte_count
                cases.append(_case(upload, result, "eligible", byte_count))
                UPLOAD_PAYLOAD_GC.labels(upload.file_kind, result).inc()
        except Exception as error:
            with sessions() as session:
                upload = session.scalar(
                    select(Upload).where(Upload.id == upload_id).with_for_update()
                )
                if upload is not None and upload.payload_delete_claim_token == token:
                    upload.payload_delete_claim_token = None
                    upload.payload_delete_lease_expires_at = None
                    upload.payload_delete_last_error = type(error).__name__[:200]
                    operation_log(
                        session,
                        action="upload.payload_delete",
                        target_type="upload",
                        target_id=upload.id,
                        workspace_id=upload.workspace_id,
                        result="failed",
                        details={"error_type": type(error).__name__},
                    )
                    session.commit()
            failed += 1
            cases.append(
                {
                    "upload_id": upload_id,
                    "outcome": "failed",
                    "reason": type(error).__name__,
                    "bytes": byte_count,
                }
            )
            UPLOAD_PAYLOAD_GC.labels(
                upload.file_kind if upload is not None else "unknown", "failed"
            ).inc()

    return {
        "schema_version": "upload-payload-gc-v1",
        "mode": "apply" if apply else "dry-run",
        "scanned": len(candidate_ids),
        "deleted": deleted,
        "would_delete": would_delete,
        "skipped": skipped,
        "failed": failed,
        "reclaimed_or_reclaimable_bytes": reclaimed_bytes,
        "storage_reconciliation": refresh_upload_payload_storage_metrics(sessions, store),
        "cases": cases,
    }


def refresh_upload_payload_storage_metrics(
    sessions: sessionmaker[Session], store: ObjectStore
) -> dict[str, Any]:
    """Reconcile the Upload staging prefix without exporting keys or Workspace labels."""

    counts = {condition: 0 for condition in UPLOAD_STORAGE_CONDITIONS}
    byte_counts = {condition: 0 for condition in UPLOAD_STORAGE_CONDITIONS}
    try:
        with sessions() as session:
            rows = session.execute(
                select(
                    Upload.object_key,
                    Upload.payload_deleted_at,
                    func.coalesce(
                        Upload.verified_wire_length,
                        Upload.wire_declared_length,
                        Upload.declared_length,
                    ),
                )
            ).all()
        durable = {
            object_key: {
                "deleted": payload_deleted_at is not None,
                "bytes": int(byte_count),
            }
            for object_key, payload_deleted_at, byte_count in rows
        }
        objects = {item.key: int(item.size) for item in store.iter_objects("uploads")}
        for object_key, size in objects.items():
            state = durable.get(object_key)
            if state is None:
                counts["orphan"] += 1
                byte_counts["orphan"] += size
            elif bool(state["deleted"]):
                counts["deleted_marker_present"] += 1
                byte_counts["deleted_marker_present"] += size
            elif int(state["bytes"]) != size:
                counts["size_mismatch"] += 1
                byte_counts["size_mismatch"] += abs(int(state["bytes"]) - size)
        for object_key, state in durable.items():
            if not bool(state["deleted"]) and object_key not in objects:
                counts["missing_retained"] += 1
                byte_counts["missing_retained"] += int(state["bytes"])
        for condition in UPLOAD_STORAGE_CONDITIONS:
            UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_OBJECTS.labels(condition).set(counts[condition])
            UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_BYTES.labels(condition).set(
                byte_counts[condition]
            )
        return {"status": "ok", "objects": counts, "bytes": byte_counts}
    except Exception as error:
        METRICS_REFRESH_FAILURES.labels("upload_payload_storage").inc()
        for condition in UPLOAD_STORAGE_CONDITIONS:
            UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_OBJECTS.labels(condition).set(math.nan)
            UPLOAD_PAYLOAD_STORAGE_INCONSISTENT_BYTES.labels(condition).set(math.nan)
        return {"status": "failed", "error_type": type(error).__name__}


def upload_payload_gc_eligibility(
    session: Session, store: ObjectStore, upload: Upload, now: datetime
) -> UploadGcEligibility:
    byte_count = int(upload.verified_wire_length or upload.wire_declared_length)
    if upload.verification_status not in TERMINAL_UPLOAD_STATES:
        return UploadGcEligibility(False, "upload_not_terminal", byte_count)
    if upload.payload_deleted_at is not None:
        return UploadGcEligibility(False, "payload_already_deleted", byte_count)
    if (
        upload.payload_delete_claim_token
        and upload.payload_delete_lease_expires_at is not None
        and _aware(upload.payload_delete_lease_expires_at) > now
    ):
        return UploadGcEligibility(False, "payload_delete_claim_active", byte_count)
    transfer_claim = session.scalar(
        select(ArtifactBlobUploadClaim).where(ArtifactBlobUploadClaim.upload_id == upload.id)
    )
    if transfer_claim is not None and _aware(transfer_claim.lease_expires_at) > now:
        return UploadGcEligibility(False, "artifact_transfer_claim_active", byte_count)
    execution = session.get(TaskExecution, {"task_type": "verify_upload", "logical_key": upload.id})
    if (
        execution is not None
        and execution.outcome == "running"
        and execution.lease_until is not None
        and _aware(execution.lease_until) > now
    ):
        return UploadGcEligibility(False, "verification_task_active", byte_count)
    if upload.verification_status != "ACCEPTED":
        return UploadGcEligibility(True, "forensic_retention_elapsed", byte_count)
    if not upload.verified_sha256 or upload.verified_length is None:
        return UploadGcEligibility(False, "verified_identity_missing", byte_count)
    if upload.file_kind == "dmp":
        dump_blob = session.scalar(
            select(DumpBlob).where(
                DumpBlob.workspace_id == upload.workspace_id,
                DumpBlob.sha256 == upload.verified_sha256,
                DumpBlob.size == upload.verified_length,
                DumpBlob.verification_status == "ACCEPTED",
                DumpBlob.deleted_at.is_(None),
            )
        )
        if dump_blob is None or not _raw_object_matches(
            store, dump_blob.object_key, dump_blob.size, dump_blob.sha256
        ):
            return UploadGcEligibility(False, "authoritative_dump_missing", byte_count)
        return UploadGcEligibility(True, "eligible", byte_count)
    artifact = session.scalar(
        select(Artifact)
        .join(Build, Build.id == Artifact.build_id)
        .where(
            Build.workspace_id == upload.workspace_id,
            Artifact.build_id == upload.build_id,
            Artifact.kind == upload.file_kind,
            Artifact.sha256 == upload.verified_sha256,
            Artifact.size == upload.verified_length,
            Artifact.verification_status == "verified",
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    if artifact is None:
        return UploadGcEligibility(False, "authoritative_artifact_missing", byte_count)
    if artifact.artifact_blob_id is not None:
        artifact_blob = session.get(ArtifactBlob, artifact.artifact_blob_id)
        if (
            artifact_blob is None
            or artifact_blob.verification_status != "verified"
            or not payload_head_valid(store, artifact_blob)
        ):
            return UploadGcEligibility(False, "authoritative_blob_missing", byte_count)
    elif not _raw_object_matches(store, artifact.object_key, artifact.size, artifact.sha256):
        return UploadGcEligibility(False, "authoritative_artifact_object_missing", byte_count)
    return UploadGcEligibility(True, "eligible", byte_count)


def _raw_object_matches(store: ObjectStore, key: str, size: int, sha256: str) -> bool:
    try:
        if store.head(key).size != size:
            return False
        digest = hashlib.sha256()
        observed_size = 0
        for chunk in store.stream(key):
            observed_size += len(chunk)
            if observed_size > size:
                return False
            digest.update(chunk)
        return observed_size == size and digest.hexdigest() == sha256.lower()
    except ObjectNotFoundError:
        return False


def _case(upload: Upload, outcome: str, reason: str, byte_count: int) -> dict[str, Any]:
    return {
        "upload_id": upload.id,
        "file_kind": upload.file_kind,
        "state": upload.verification_status,
        "outcome": outcome,
        "reason": reason,
        "bytes": byte_count,
    }


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
