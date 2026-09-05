from __future__ import annotations

from datetime import datetime

from crashcap_api.config import Settings
from crashcap_api.models import DumpBlob, utcnow
from crashcap_api.services.common import operation_log
from crashcap_api.services.dump_content import lock_dump_content
from crashcap_api.services.upload_gc import (
    refresh_upload_payload_storage_metrics,
    sweep_terminal_upload_payloads,
)
from crashcap_api.storage import ObjectNotFoundError, ObjectStore
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker


def expire_dump_blobs(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    *,
    now: datetime | None = None,
    limit: int = 1000,
) -> int:
    cutoff = now or utcnow()
    expired = 0
    with sessions() as session:
        candidates = session.execute(
            select(DumpBlob.id, DumpBlob.sha256)
            .where(
                DumpBlob.expires_at.is_not(None),
                DumpBlob.expires_at <= cutoff,
                DumpBlob.deleted_at.is_(None),
            )
            .order_by(DumpBlob.expires_at)
            .limit(limit)
        ).all()
    for blob_id, sha256 in candidates:
        with sessions.begin() as session:
            lock_dump_content(session, sha256)
            blob = session.scalar(
                select(DumpBlob)
                .where(
                    DumpBlob.id == blob_id,
                    DumpBlob.expires_at <= cutoff,
                    DumpBlob.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if blob is None:
                continue
            shared = session.scalar(
                select(DumpBlob.id)
                .where(
                    DumpBlob.id != blob.id,
                    DumpBlob.object_key == blob.object_key,
                    DumpBlob.deleted_at.is_(None),
                    or_(DumpBlob.expires_at.is_(None), DumpBlob.expires_at > cutoff),
                )
                .limit(1)
            )
            result = "shared_content_retained" if shared else "deleted_raw_only"
            if not shared:
                try:
                    store.delete(blob.object_key)
                except ObjectNotFoundError:
                    result = "raw_already_absent"
                except Exception as error:
                    operation_log(
                        session,
                        action="retention.expire",
                        target_type="dump_blob",
                        target_id=blob.id,
                        workspace_id=blob.workspace_id,
                        result="object_delete_failed",
                        details={"error_type": type(error).__name__},
                    )
                    continue
            blob.deleted_at = cutoff
            operation_log(
                session,
                action="retention.expire",
                target_type="dump_blob",
                target_id=blob.id,
                workspace_id=blob.workspace_id,
                result=result,
                details={"sha256": blob.sha256},
            )
            expired += 1
    return expired


def sweep_upload_payloads(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = 1000,
) -> dict[str, object]:
    mode = settings.artifact_upload_gc_mode
    if mode == "off":
        return {
            "schema_version": "upload-payload-gc-v1",
            "mode": "off",
            "scanned": 0,
            "deleted": 0,
            "would_delete": 0,
            "skipped": 0,
            "failed": 0,
            "reclaimed_or_reclaimable_bytes": 0,
            "storage_reconciliation": refresh_upload_payload_storage_metrics(sessions, store),
            "cases": [],
        }
    return sweep_terminal_upload_payloads(
        sessions,
        store,
        settings,
        now=now,
        limit=limit,
        apply=mode == "active",
    )
