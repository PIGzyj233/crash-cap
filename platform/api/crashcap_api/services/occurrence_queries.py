from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..errors import ApiError
from ..models import (
    AnalysisRun,
    AnalysisSummary,
    CrashGroup,
    GroupMembership,
    MissingSymbolOccurrence,
    Occurrence,
    OccurrenceSubmission,
)

CURSOR_VERSION: Final = 1
MAX_CURSOR_LENGTH: Final = 2048
MAX_CURSOR_PAYLOAD_LENGTH: Final = 1024
FAILED_ATTEMPT_STATES: Final = frozenset({"FAILED", "REJECTED", "CANCELLED", "TIMEOUT", "OOM"})
IN_PROGRESS_ATTEMPT_STATES: Final = frozenset(
    {
        "UPLOADED",
        "VALIDATING",
        "INSPECTED",
        "MATCHING_SYMBOLS",
        "WAITING_FOR_SYMBOLS",
        "SYMBOLS_READY",
        "QUEUED",
        "ANALYZING",
        "NORMALIZING",
        "GROUPING",
    }
)


@dataclass(frozen=True)
class OccurrenceFilters:
    workspace_id: str | None = None
    from_: datetime | None = None
    to: datetime | None = None
    crash_type: str | None = None
    latest_status: str | None = None
    version: str | None = None
    test_label: str | None = None
    test_batch: str | None = None
    grouping: str | None = None
    q: str | None = None


@dataclass(frozen=True)
class OccurrenceCursor:
    occurred_at: datetime
    occurrence_id: str


@dataclass(frozen=True)
class OccurrenceProjection:
    occurrence: Occurrence
    current_analysis: AnalysisRun | None
    latest_attempt: AnalysisRun | None
    summary: AnalysisSummary | None
    group: CrashGroup | None


@dataclass(frozen=True)
class OccurrencePage:
    items: list[OccurrenceProjection]
    next_cursor: str | None


@dataclass(frozen=True)
class WorkspaceOccurrenceAggregate:
    occurrence_count: int
    attention_count: int
    last_occurrence_at: datetime | None
    in_progress: int
    latest_attempt_failed: int
    unclassified_crashes: int
    symbol_affected_occurrences: int


def resolve_time_window(
    from_: datetime | None,
    to: datetime | None,
    *,
    default_days: int,
    max_days: int,
) -> tuple[datetime, datetime]:
    window_end = _aware_utc(to or datetime.now(UTC), "to")
    window_start = _aware_utc(from_ or window_end - timedelta(days=default_days), "from")
    if window_start > window_end:
        raise ApiError(
            "VALIDATION",
            "from must be earlier than or equal to to",
            status_code=422,
        )
    if window_end - window_start > timedelta(days=max_days):
        raise ApiError(
            "VALIDATION",
            f"time range must not exceed {max_days} days",
            status_code=422,
        )
    return window_start, window_end


def normalized_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def list_occurrence_projections(
    session: Session,
    filters: OccurrenceFilters,
    *,
    limit: int,
    cursor: str | None = None,
) -> OccurrencePage:
    current_run = aliased(AnalysisRun, name="current_analysis")
    latest_run = aliased(AnalysisRun, name="latest_attempt")
    latest_run_id = _latest_run_id_subquery()

    statement = (
        select(Occurrence, current_run, latest_run, AnalysisSummary, CrashGroup)
        .outerjoin(
            current_run,
            and_(
                current_run.id == Occurrence.current_run_id,
                current_run.occurrence_id == Occurrence.id,
            ),
        )
        .outerjoin(
            AnalysisSummary,
            AnalysisSummary.analysis_run_id == Occurrence.current_run_id,
        )
        .outerjoin(latest_run, latest_run.id == latest_run_id)
        .outerjoin(
            GroupMembership,
            and_(
                GroupMembership.occurrence_id == Occurrence.id,
                GroupMembership.analysis_run_id == Occurrence.current_run_id,
            ),
        )
        .outerjoin(
            CrashGroup,
            and_(
                CrashGroup.id == GroupMembership.group_id,
                CrashGroup.workspace_id == Occurrence.workspace_id,
            ),
        )
    )

    if filters.workspace_id is not None:
        statement = statement.where(Occurrence.workspace_id == filters.workspace_id)
    if filters.from_ is not None:
        statement = statement.where(Occurrence.occurred_at >= filters.from_)
    if filters.to is not None:
        statement = statement.where(Occurrence.occurred_at <= filters.to)
    if filters.crash_type == "no_current":
        statement = statement.where(current_run.id.is_(None))
    elif filters.crash_type is not None:
        statement = statement.where(AnalysisSummary.crash_type == filters.crash_type)
    if filters.latest_status is not None:
        statement = statement.where(latest_run.status == filters.latest_status)
    if filters.version is not None:
        statement = statement.where(Occurrence.version == filters.version)
    if filters.test_label is not None or filters.test_batch is not None:
        submission = select(OccurrenceSubmission.upload_id).where(
            OccurrenceSubmission.occurrence_id == Occurrence.id,
            OccurrenceSubmission.verified_at.is_not(None),
        )
        if filters.test_label is not None:
            submission = submission.where(OccurrenceSubmission.label == filters.test_label)
        if filters.test_batch is not None:
            submission = submission.where(OccurrenceSubmission.batch == filters.test_batch)
        statement = statement.where(submission.exists())

    if filters.grouping == "no_current":
        statement = statement.where(current_run.id.is_(None))
    elif filters.grouping == "exact":
        statement = statement.where(CrashGroup.id.is_not(None))
    elif filters.grouping == "unclassified":
        statement = statement.where(current_run.id.is_not(None), CrashGroup.id.is_(None))
    if filters.q is not None:
        pattern = f"%{_escape_like(filters.q)}%"
        statement = statement.where(
            or_(
                Occurrence.id.ilike(pattern, escape="\\"),
                AnalysisSummary.exception_name.ilike(pattern, escape="\\"),
                AnalysisSummary.exception_code.ilike(pattern, escape="\\"),
                AnalysisSummary.fault_module.ilike(pattern, escape="\\"),
                AnalysisSummary.top_function.ilike(pattern, escape="\\"),
                Occurrence.version.ilike(pattern, escape="\\"),
            )
        )

    if cursor is not None:
        decoded = decode_cursor(cursor, filters)
        statement = statement.where(
            or_(
                Occurrence.occurred_at < decoded.occurred_at,
                and_(
                    Occurrence.occurred_at == decoded.occurred_at,
                    Occurrence.id < decoded.occurrence_id,
                ),
            )
        )

    statement = statement.order_by(Occurrence.occurred_at.desc(), Occurrence.id.desc()).limit(
        limit + 1
    )
    rows = session.execute(statement).all()
    has_more = len(rows) > limit
    selected = rows[:limit]
    items = [
        OccurrenceProjection(
            occurrence=row[0],
            current_analysis=row[1],
            latest_attempt=row[2],
            summary=row[3],
            group=row[4],
        )
        for row in selected
    ]
    next_cursor = encode_cursor(items[-1], filters) if has_more and items else None
    return OccurrencePage(items=items, next_cursor=next_cursor)


def aggregate_occurrences(
    session: Session,
    *,
    window_start: datetime,
    window_end: datetime,
) -> dict[str, WorkspaceOccurrenceAggregate]:
    current_run = aliased(AnalysisRun, name="aggregate_current_analysis")
    latest_run = aliased(AnalysisRun, name="aggregate_latest_attempt")
    latest_ids = _latest_run_ids(session, "aggregate_latest_attempt_ids")
    missing_pairs = (
        select(
            MissingSymbolOccurrence.occurrence_id,
            MissingSymbolOccurrence.analysis_run_id,
        )
        .distinct()
        .subquery("aggregate_missing_symbol_pairs")
    )
    in_progress = latest_run.status.in_(IN_PROGRESS_ATTEMPT_STATES)
    latest_failed = latest_run.status.in_(FAILED_ATTEMPT_STATES)
    unclassified = and_(
        current_run.id.is_not(None),
        AnalysisSummary.crash_type == "crash",
        CrashGroup.id.is_(None),
    )
    symbol_affected = missing_pairs.c.occurrence_id.is_not(None)
    attention = or_(in_progress, latest_failed, unclassified, symbol_affected)

    statement = (
        select(
            Occurrence.workspace_id,
            func.count(Occurrence.id),
            func.sum(case((attention, 1), else_=0)),
            func.max(Occurrence.occurred_at),
            func.sum(case((in_progress, 1), else_=0)),
            func.sum(case((latest_failed, 1), else_=0)),
            func.sum(case((unclassified, 1), else_=0)),
            func.sum(case((symbol_affected, 1), else_=0)),
        )
        .outerjoin(
            current_run,
            and_(
                current_run.id == Occurrence.current_run_id,
                current_run.occurrence_id == Occurrence.id,
            ),
        )
        .outerjoin(
            AnalysisSummary,
            AnalysisSummary.analysis_run_id == Occurrence.current_run_id,
        )
        .outerjoin(latest_ids, latest_ids.c.occurrence_id == Occurrence.id)
        .outerjoin(latest_run, latest_run.id == latest_ids.c.run_id)
        .outerjoin(
            GroupMembership,
            and_(
                GroupMembership.occurrence_id == Occurrence.id,
                GroupMembership.analysis_run_id == Occurrence.current_run_id,
            ),
        )
        .outerjoin(
            CrashGroup,
            and_(
                CrashGroup.id == GroupMembership.group_id,
                CrashGroup.workspace_id == Occurrence.workspace_id,
            ),
        )
        .outerjoin(
            missing_pairs,
            and_(
                missing_pairs.c.occurrence_id == Occurrence.id,
                missing_pairs.c.analysis_run_id == Occurrence.current_run_id,
            ),
        )
        .where(
            Occurrence.occurred_at >= window_start,
            Occurrence.occurred_at <= window_end,
        )
        .group_by(Occurrence.workspace_id)
    )
    return {
        str(row[0]): WorkspaceOccurrenceAggregate(
            occurrence_count=int(row[1] or 0),
            attention_count=int(row[2] or 0),
            last_occurrence_at=row[3],
            in_progress=int(row[4] or 0),
            latest_attempt_failed=int(row[5] or 0),
            unclassified_crashes=int(row[6] or 0),
            symbol_affected_occurrences=int(row[7] or 0),
        )
        for row in session.execute(statement)
    }


def _latest_run_id_subquery() -> Any:
    return (
        select(AnalysisRun.id)
        .where(AnalysisRun.occurrence_id == Occurrence.id)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
        .correlate(Occurrence)
        .scalar_subquery()
    )


def _latest_run_ids(session: Session, name: str) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        return (
            select(
                AnalysisRun.occurrence_id,
                AnalysisRun.id.label("run_id"),
            )
            .distinct(AnalysisRun.occurrence_id)
            .order_by(AnalysisRun.occurrence_id, AnalysisRun.id.desc())
            .subquery(name)
        )
    return (
        select(
            AnalysisRun.occurrence_id.label("occurrence_id"),
            func.max(AnalysisRun.id).label("run_id"),
        )
        .group_by(AnalysisRun.occurrence_id)
        .subquery(name)
    )


def encode_cursor(item: OccurrenceProjection, filters: OccurrenceFilters) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "occurred_at": _storage_utc(item.occurrence.occurred_at).isoformat(),
        "id": item.occurrence.id,
        "filter": _filter_digest(filters),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str, filters: OccurrenceFilters) -> OccurrenceCursor:
    try:
        if not value or len(value) > MAX_CURSOR_LENGTH:
            raise ValueError("cursor length")
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode((value + padding).encode("ascii"), altchars=b"-_", validate=True)
        if len(raw) > MAX_CURSOR_PAYLOAD_LENGTH:
            raise ValueError("cursor payload length")
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "occurred_at",
            "id",
            "filter",
        }:
            raise ValueError("cursor shape")
        if payload["v"] != CURSOR_VERSION:
            raise ValueError("cursor version")
        if not isinstance(payload["id"], str) or not 1 <= len(payload["id"]) <= 128:
            raise ValueError("cursor id")
        if not isinstance(payload["filter"], str) or payload["filter"] != _filter_digest(filters):
            raise ValueError("cursor filter")
        if not isinstance(payload["occurred_at"], str):
            raise ValueError("cursor timestamp")
        occurred_at = _aware_utc(
            datetime.fromisoformat(payload["occurred_at"]), "cursor occurred_at"
        )
    except (UnicodeError, ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ApiError(
            "INVALID_CURSOR",
            "cursor is invalid or does not match the current filters",
            status_code=422,
        ) from None
    return OccurrenceCursor(occurred_at=occurred_at, occurrence_id=payload["id"])


def _filter_digest(filters: OccurrenceFilters) -> str:
    payload = {
        "workspace_id": filters.workspace_id,
        "from": _datetime_text(filters.from_),
        "to": _datetime_text(filters.to),
        "crash_type": filters.crash_type,
        "latest_status": filters.latest_status,
        "version": filters.version,
        "grouping": filters.grouping,
        "q": filters.q,
    }
    if filters.test_label is not None:
        payload["test_label"] = filters.test_label
    if filters.test_batch is not None:
        payload["test_batch"] = filters.test_batch
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _datetime_text(value: datetime | None) -> str | None:
    return _aware_utc(value, "filter timestamp").isoformat() if value is not None else None


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApiError(
            "VALIDATION",
            f"{field} must include a timezone",
            status_code=422,
        )
    return value.astimezone(UTC)


def _storage_utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata even for DateTime(timezone=True). Test and
    # local-development databases still store the same UTC values, so restore
    # the declared storage timezone when encoding an otherwise opaque cursor.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
