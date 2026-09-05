"""Request analysis; the planner alone creates immutable execution Runs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import AnalysisDemand, DumpBlob, Occurrence
from .analysis_demands import _demand, _note_change, ensure_demand
from .symbol_catalog import lock_catalog


def request_analysis(
    session: Session, occurrence: Occurrence, *, cause: str = "manual"
) -> AnalysisDemand:
    lock_catalog(session)
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    now = datetime.now(UTC)
    expired = blob.expires_at if blob else None
    if expired is not None and expired.tzinfo is None:
        expired = expired.replace(tzinfo=UTC)
    if blob is None or blob.deleted_at is not None or (expired is not None and expired <= now):
        raise ApiError("RAW_BLOB_EXPIRED", "Raw Dump Blob has expired", status_code=410)
    result = ensure_demand(session, occurrence.id, now=now)
    result = _demand(session, result.id)
    _note_change(session, result, now=now, cause=cause)
    if result.state != "running":
        result.state = "preparing"
        result.not_before = now
    return result
