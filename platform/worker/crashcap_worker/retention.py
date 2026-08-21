from __future__ import annotations

from datetime import datetime

from crashcap_api.models import DumpBlob, utcnow
from crashcap_api.services.common import operation_log
from crashcap_api.storage import ObjectNotFoundError, ObjectStore
from sqlalchemy import select
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
        blobs = session.scalars(
            select(DumpBlob)
            .where(
                DumpBlob.expires_at.is_not(None),
                DumpBlob.expires_at <= cutoff,
                DumpBlob.deleted_at.is_(None),
            )
            .order_by(DumpBlob.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for blob in blobs:
            result = "deleted_raw_only"
            try:
                store.delete(blob.object_key)
            except ObjectNotFoundError:
                # A retry after a successful object delete is still success:
                # converge the durable marker without resurrecting history.
                result = "raw_already_absent"
            except Exception as error:
                # Never claim database completion after a 403, timeout, or
                # storage failure. Persist a non-sensitive audit record and
                # leave the Blob eligible for the next scheduled run.
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
        session.commit()
    return expired
