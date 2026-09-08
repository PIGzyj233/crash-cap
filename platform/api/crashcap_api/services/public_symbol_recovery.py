"""Recover only cache jobs; this service never emits analysis work."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import PublicSymbolJob, TaskExecution, TaskIntent
from ..task_handoff import request_task_redelivery


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recover_public_symbol_jobs(session: Session, settings: Settings, *, now: datetime) -> int:
    candidates = session.execute(
        select(PublicSymbolJob, TaskIntent)
        .join(
            TaskIntent,
            (TaskIntent.task_type == "fetch_public_symbols")
            & (TaskIntent.target_id == PublicSymbolJob.id),
        )
        .where(
            PublicSymbolJob.status.in_(["queued", "running"]),
            TaskIntent.state.in_(["published", "dead"]),
        )
        .order_by(PublicSymbolJob.created_at)
        .limit(100)
    ).all()
    recovered = 0
    for job, intent in candidates:
        execution = session.get(TaskExecution, ("fetch_public_symbols", job.id))
        if (
            execution
            and execution.outcome == "running"
            and execution.lease_until
            and _utc(execution.lease_until) > _utc(now)
        ):
            continue
        if (
            execution is None
            and intent.published_at
            and _utc(intent.published_at)
            + timedelta(seconds=settings.automatic_analysis_delivery_timeout_seconds)
            > _utc(now)
        ):
            continue
        decision = request_task_redelivery(
            session, dict(intent.message), settings.schema_root, now=now
        )
        recovered += int(decision.reopened)
        if decision.reopened and intent.delivery_attempts >= 3:
            job.status, job.error_code, job.finished_at = (
                "failed",
                "PUBLIC_SYMBOL_DELIVERY_EXHAUSTED",
                now,
            )
            intent.state, intent.dead_at = "dead", now
    return recovered
