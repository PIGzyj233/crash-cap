from __future__ import annotations

import math
from datetime import UTC, datetime

from prometheus_client import Counter as PrometheusCounter
from prometheus_client import Gauge, Histogram
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .analysis_states import TERMINAL_STATES
from .models import (
    ANALYSIS_STATUSES,
    UPLOAD_STATUSES,
    AnalysisRun,
    Artifact,
    DumpBlob,
    Occurrence,
    SymbolProjectionGap,
    SymbolProjectionState,
    TaskExecution,
    TaskIntent,
    Upload,
    utcnow,
)

PHASE1_QUEUES = ("verify", "ingest", "dump-small", "dump-large")
TERMINAL_ANALYSIS_STATUSES = TERMINAL_STATES

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
SYMBOL_PROJECTION_WRITES = PrometheusCounter(
    "crashcap_symbol_projection_writes_total",
    "Current Analysis Symbol projection writes by mode and outcome.",
    ("mode", "outcome"),
)
SYMBOL_PROJECTION_SHADOW_MISMATCHES = PrometheusCounter(
    "crashcap_symbol_projection_shadow_mismatches_total",
    "Compatibility/projection snapshot mismatches.",
)
SYMBOL_PROJECTION_STRICT_FAILURES = PrometheusCounter(
    "crashcap_symbol_projection_strict_failures_total",
    "Strict Symbol projection failures that roll back Current Analysis promotion.",
    ("reason",),
)
SYMBOL_PROJECTION_BACKFILL_REMAINING = Gauge(
    "crashcap_symbol_projection_backfill_remaining",
    "Current Analyses without a matching durable Symbol projection state.",
)
SYMBOL_PROJECTION_UNRESOLVED_GAPS = Gauge(
    "crashcap_symbol_projection_unresolved_gaps",
    "Unresolved durable Symbol projection backfill gaps.",
)
TASK_INTENT_STATE = Gauge(
    "crashcap_task_intents",
    "Durable task intents by type and delivery state.",
    ("task_type", "state"),
)
TASK_INTENT_OLDEST_PENDING_AGE = Gauge(
    "crashcap_task_intent_oldest_pending_age_seconds",
    "Age of the oldest pending or publishing durable intent by type.",
    ("task_type",),
)
TASK_EXECUTION_STATE = Gauge(
    "crashcap_task_executions",
    "Durable task executions by type and outcome.",
    ("task_type", "outcome"),
)
TASK_EXECUTION_EXPIRED_ACTIVE = Gauge(
    "crashcap_task_execution_expired_active",
    "Running task ownership leases that have expired, by type.",
    ("task_type",),
)
TASK_CLAIMS = PrometheusCounter(
    "crashcap_task_claims_total",
    "Execution ownership claims and rejections.",
    ("task_type", "outcome"),
)
RELAY_DELIVERIES = PrometheusCounter(
    "crashcap_relay_deliveries_total",
    "Outbox relay publish outcomes.",
    ("task_type", "outcome"),
)
RELAY_BACKOFF_SECONDS = Histogram(
    "crashcap_relay_backoff_seconds",
    "Scheduled outbox relay retry backoff after a transient publish failure.",
    ("task_type",),
    buckets=(1, 2, 4, 8, 16, 32, 60, 120, 300),
)
TASK_POISONED = PrometheusCounter(
    "crashcap_task_poisoned_total",
    "Permanently rejected task intents.",
    ("task_type", "source"),
)
ANALYSIS_TRANSITIONS = PrometheusCounter(
    "crashcap_analysis_transitions_total",
    "Analysis lifecycle transition decisions.",
    ("from_state", "to_state", "outcome"),
)
CURRENT_ANALYSIS_PROMOTIONS = PrometheusCounter(
    "crashcap_current_analysis_promotions_total",
    "Current Analysis promotion decisions.",
    ("outcome", "reason"),
)
TASK_HEARTBEATS = PrometheusCounter(
    "crashcap_task_heartbeats_total",
    "Execution ownership heartbeat decisions.",
    ("task_type", "outcome"),
)
FENCED_STALE_WRITES = PrometheusCounter(
    "crashcap_fenced_stale_writes_total",
    "Writes discarded because task execution ownership was stale.",
    ("task_type", "stage"),
)
CANONICAL_SHADOW_RESULTS = PrometheusCounter(
    "crashcap_canonical_shadow_results_total",
    "Canonical legacy/core-final shadow comparison outcomes.",
    ("outcome",),
)
CANONICAL_VALIDATION_FAILURES = PrometheusCounter(
    "crashcap_canonical_validation_failures_total",
    "Canonical validation failures before winner finalize.",
    ("kind",),
)
CANONICAL_WINNER_FINALIZES = PrometheusCounter(
    "crashcap_canonical_winner_finalizes_total",
    "Canonical winner finalizations by assembly and terminal mode.",
    ("assembly_mode", "status", "promotion"),
)
GENERATION_ORPHAN_OBJECTS = PrometheusCounter(
    "crashcap_generation_orphan_objects_total",
    "Generation-scoped objects left by a fenced stale owner.",
    ("kind",),
)
GENERATION_ORPHAN_BYTES = PrometheusCounter(
    "crashcap_generation_orphan_bytes_total",
    "Bytes left in generation-scoped objects by a fenced stale owner.",
    ("kind",),
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
        _refresh_symbol_projection(session)
        _refresh_task_handoff(session)


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


def _refresh_symbol_projection(session: Session) -> None:
    remaining = session.scalar(
        select(func.count())
        .select_from(Occurrence)
        .outerjoin(
            SymbolProjectionState,
            SymbolProjectionState.occurrence_id == Occurrence.id,
        )
        .where(
            Occurrence.current_run_id.is_not(None),
            (
                SymbolProjectionState.analysis_run_id.is_(None)
                | (SymbolProjectionState.analysis_run_id != Occurrence.current_run_id)
            ),
        )
    )
    gaps = session.scalar(
        select(func.count())
        .select_from(SymbolProjectionGap)
        .where(SymbolProjectionGap.resolved_at.is_(None))
    )
    SYMBOL_PROJECTION_BACKFILL_REMAINING.set(int(remaining or 0))
    SYMBOL_PROJECTION_UNRESOLVED_GAPS.set(int(gaps or 0))


def _refresh_task_handoff(session: Session) -> None:
    now = utcnow()
    intent_counts = {
        (str(task_type), str(state)): int(count)
        for task_type, state, count in session.execute(
            select(TaskIntent.task_type, TaskIntent.state, func.count()).group_by(
                TaskIntent.task_type, TaskIntent.state
            )
        )
    }
    execution_counts = {
        (str(task_type), str(outcome)): int(count)
        for task_type, outcome, count in session.execute(
            select(TaskExecution.task_type, TaskExecution.outcome, func.count()).group_by(
                TaskExecution.task_type, TaskExecution.outcome
            )
        )
    }
    task_types = sorted(
        {"verify_upload", "ingest_artifact", "reindex_symbols", "analyze_occurrence"}
        | {item[0] for item in intent_counts}
        | {item[0] for item in execution_counts}
    )
    for task_type in task_types:
        for state in ("pending", "publishing", "published", "dead"):
            TASK_INTENT_STATE.labels(task_type, state).set(intent_counts.get((task_type, state), 0))
        for outcome in ("idle", "running", "succeeded", "failed", "dead"):
            TASK_EXECUTION_STATE.labels(task_type, outcome).set(
                execution_counts.get((task_type, outcome), 0)
            )
        oldest = session.scalar(
            select(func.min(TaskIntent.created_at)).where(
                TaskIntent.task_type == task_type,
                TaskIntent.state.in_(["pending", "publishing"]),
            )
        )
        age = max(0.0, (now - _aware(oldest)).total_seconds()) if oldest else 0.0
        TASK_INTENT_OLDEST_PENDING_AGE.labels(task_type).set(age)
        expired = session.scalar(
            select(func.count())
            .select_from(TaskExecution)
            .where(
                TaskExecution.task_type == task_type,
                TaskExecution.outcome == "running",
                TaskExecution.lease_until.is_not(None),
                TaskExecution.lease_until <= now,
            )
        )
        TASK_EXECUTION_EXPIRED_ACTIVE.labels(task_type).set(int(expired or 0))


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
