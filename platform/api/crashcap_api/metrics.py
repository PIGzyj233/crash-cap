from __future__ import annotations

import math
from datetime import UTC, datetime

from prometheus_client import Counter as PrometheusCounter
from prometheus_client import Gauge
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    ANALYSIS_STATUSES,
    UPLOAD_STATUSES,
    AnalysisRun,
    Artifact,
    DumpBlob,
    Upload,
    utcnow,
)

PHASE1_QUEUES = ("verify", "ingest", "dump-small", "dump-large")
TERMINAL_ANALYSIS_STATUSES = {
    "COMPLETE",
    "PARTIAL",
    "FAILED",
    "REJECTED",
    "CANCELLED",
    "TIMEOUT",
    "OOM",
}

QUEUE_DEPTH = Gauge(
    "crashcap_queue_depth",
    "Current number of messages in each Phase 1 task queue.",
    ("queue",),
)
ANALYSIS_STATE = Gauge(
    "crashcap_analysis_runs",
    "Analysis Runs by durable PostgreSQL state.",
    ("status",),
)
ANALYSIS_STATE_OLDEST_AGE = Gauge(
    "crashcap_analysis_state_oldest_age_seconds",
    "Age of the oldest non-terminal Analysis Run in each state.",
    ("status",),
)
ANALYSIS_DURATION = Gauge(
    "crashcap_analysis_duration_seconds",
    "Observed end-to-end Analysis Run duration for completed attempts.",
    ("status", "quantile"),
)
UPLOAD_STATE = Gauge(
    "crashcap_uploads",
    "Uploads by durable verification state.",
    ("status",),
)
OBJECT_COUNT = Gauge(
    "crashcap_object_count",
    "Objects represented by PostgreSQL metadata.",
    ("kind", "state"),
)
OBJECT_BYTES = Gauge(
    "crashcap_object_bytes",
    "Object bytes represented by PostgreSQL metadata.",
    ("kind", "state"),
)
METRICS_REFRESH_FAILURES = PrometheusCounter(
    "crashcap_metrics_refresh_failures_total",
    "Operational metric refresh failures that leave a component unavailable.",
    ("component",),
)


def refresh_operational_metrics(sessions: sessionmaker[Session], dispatcher: object) -> None:
    """Refresh gauges from durable state without changing application data."""

    _refresh_queue_depth(dispatcher)
    with sessions() as session:
        analysis_counts: dict[str, int] = {
            status: int(count)
            for status, count in session.execute(
                select(AnalysisRun.status, func.count()).group_by(AnalysisRun.status)
            )
        }
        upload_counts: dict[str, int] = {
            status: int(count)
            for status, count in session.execute(
                select(Upload.verification_status, func.count()).group_by(
                    Upload.verification_status
                )
            )
        }
        for status in sorted(ANALYSIS_STATUSES):
            ANALYSIS_STATE.labels(status).set(int(analysis_counts.get(status, 0)))
        for status in sorted(UPLOAD_STATUSES):
            UPLOAD_STATE.labels(status).set(int(upload_counts.get(status, 0)))

        _refresh_analysis_age_and_duration(session)
        _refresh_object_growth(session)


def _refresh_queue_depth(dispatcher: object) -> None:
    depths: dict[str, float] = {}
    messages = getattr(dispatcher, "messages", None)
    if messages is not None:
        for message in messages:
            queue = message.get("queue")
            if isinstance(queue, str):
                depths[queue] = depths.get(queue, 0.0) + 1.0
    else:
        broker = getattr(dispatcher, "broker", None)
        if broker is not None:
            for queue in PHASE1_QUEUES:
                try:
                    depths[queue] = float(broker.do_qsize(queue))
                except Exception:
                    METRICS_REFRESH_FAILURES.labels("redis_queue_depth").inc()
                    depths[queue] = math.nan
    for queue in PHASE1_QUEUES:
        QUEUE_DEPTH.labels(queue).set(depths.get(queue, 0))


def _refresh_analysis_age_and_duration(session: Session) -> None:
    now = utcnow()
    active_rows = session.execute(
        select(AnalysisRun.id, AnalysisRun.status, AnalysisRun.started_at).where(
            AnalysisRun.status.not_in(TERMINAL_ANALYSIS_STATUSES)
        )
    ).all()
    oldest: dict[str, float] = {}
    for run_id, status, started_at in active_rows:
        start = started_at or _ulid_datetime(run_id)
        age = max(0.0, (now - _aware(start)).total_seconds())
        oldest[status] = max(oldest.get(status, 0.0), age)
    for status in sorted(ANALYSIS_STATUSES - TERMINAL_ANALYSIS_STATUSES):
        ANALYSIS_STATE_OLDEST_AGE.labels(status).set(oldest.get(status, 0.0))

    durations: dict[str, list[float]] = {}
    rows = session.execute(
        select(AnalysisRun.status, AnalysisRun.started_at, AnalysisRun.finished_at)
        .where(AnalysisRun.started_at.is_not(None), AnalysisRun.finished_at.is_not(None))
        .order_by(AnalysisRun.id.desc())
        .limit(10_000)
    ).all()
    for status, started_at, finished_at in rows:
        duration = max(0.0, (_aware(finished_at) - _aware(started_at)).total_seconds())
        durations.setdefault(status, []).append(duration)
    for status in sorted(TERMINAL_ANALYSIS_STATUSES):
        values = sorted(durations.get(status, []))
        ANALYSIS_DURATION.labels(status, "p50").set(_percentile(values, 0.50))
        ANALYSIS_DURATION.labels(status, "p95").set(_percentile(values, 0.95))
        ANALYSIS_DURATION.labels(status, "p99").set(_percentile(values, 0.99))


def _refresh_object_growth(session: Session) -> None:
    active_dump_count, active_dump_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(DumpBlob.size), 0)).where(
            DumpBlob.deleted_at.is_(None)
        )
    ).one()
    deleted_dump_count, deleted_dump_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(DumpBlob.size), 0)).where(
            DumpBlob.deleted_at.is_not(None)
        )
    ).one()
    artifact_count, artifact_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(Artifact.size), 0))
    ).one()
    staging_count, staging_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(Upload.declared_length), 0))
    ).one()
    values = {
        ("dump_blob", "active"): (active_dump_count, active_dump_bytes),
        ("dump_blob", "deleted"): (deleted_dump_count, deleted_dump_bytes),
        ("artifact", "all"): (artifact_count, artifact_bytes),
        ("upload_staging", "all"): (staging_count, staging_bytes),
    }
    for (kind, state), (count, size) in values.items():
        OBJECT_COUNT.labels(kind, state).set(int(count))
        OBJECT_BYTES.labels(kind, state).set(int(size))


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    index = max(0, math.ceil(len(values) * quantile) - 1)
    return values[index]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _ulid_datetime(identifier: str) -> datetime:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    encoded = identifier.rsplit("_", 1)[-1][:10]
    timestamp_ms = 0
    try:
        for char in encoded:
            timestamp_ms = timestamp_ms * 32 + alphabet.index(char)
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    except (ValueError, OSError, OverflowError):
        return datetime.now(UTC)
