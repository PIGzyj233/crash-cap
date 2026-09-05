"""Settle abandoned frozen executions through the existing finite Demand budget."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import AnalysisDemand, AnalysisRun, DumpBlob, Occurrence, TaskExecution, TaskIntent
from .analysis_demands import settle_demand_after_execution_failure
from .analysis_lifecycle import fail_analysis
from .analysis_scheduler import release_execution_slot_for_run
from .common import operation_log


def recover_expired_frozen_runs(session: Session, settings: Settings, *, now: datetime) -> int:
    if not settings.automatic_analysis_enabled:
        return 0
    current = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    delivery_cutoff = current - timedelta(
        seconds=settings.automatic_analysis_delivery_timeout_seconds
    )
    intents = list(
        session.scalars(
            select(TaskIntent)
            .outerjoin(
                TaskExecution,
                and_(
                    TaskExecution.task_type == TaskIntent.task_type,
                    TaskExecution.logical_key == TaskIntent.logical_key,
                ),
            )
            .join(AnalysisRun, AnalysisRun.id == TaskIntent.logical_key)
            .where(
                TaskIntent.task_type == "analyze_frozen_run",
                AnalysisRun.schema_version == "2.0",
                AnalysisRun.assembly_mode == "core-final",
                AnalysisRun.demand_id.is_not(None),
                or_(
                    and_(
                        TaskExecution.outcome == "running",
                        TaskExecution.lease_until <= current,
                        AnalysisRun.status == "ANALYZING",
                    ),
                    and_(
                        TaskExecution.logical_key.is_(None),
                        TaskIntent.state == "published",
                        TaskIntent.published_at <= delivery_cutoff,
                        AnalysisRun.status == "QUEUED",
                    ),
                ),
            )
            .order_by(
                func.coalesce(TaskExecution.lease_until, TaskIntent.published_at),
                TaskIntent.attempt_id,
            )
            .limit(settings.automatic_analysis_release_limit)
            .with_for_update(of=TaskIntent, skip_locked=True)
        )
    )
    recovered = 0
    for intent in intents:
        execution = session.scalar(
            select(TaskExecution)
            .where(
                TaskExecution.task_type == intent.task_type,
                TaskExecution.logical_key == intent.logical_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if execution is None:
            published = intent.published_at
            if published is not None and published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            if intent.state != "published" or published is None or published > delivery_cutoff:
                continue
            expected_status = "QUEUED"
            code = "FROZEN_DELIVERY_UNCLAIMED_TIMEOUT"
        else:
            if execution.outcome != "running" or execution.lease_until is None:
                continue
            lease = execution.lease_until
            if lease.tzinfo is None:
                lease = lease.replace(tzinfo=UTC)
            if lease > current or execution.active_attempt_id != intent.attempt_id:
                continue
            expected_status = "ANALYZING"
            code = "FROZEN_EXECUTION_LEASE_EXPIRED"
        run = session.scalar(
            select(AnalysisRun)
            .where(
                AnalysisRun.id == intent.logical_key,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None or run.status != expected_status:
            continue
        fail_analysis(run, code)
        run.error_code = code
        run.error_detail = (
            "Published task was not claimed within the configured delivery timeout"
            if execution is None
            else "Execution lease expired before a terminal transaction committed"
        )
        if execution is not None:
            execution.outcome = "failed"
            execution.lease_until = None
            execution.updated_at = current
        demand = session.scalar(
            select(AnalysisDemand)
            .where(
                AnalysisDemand.id == run.demand_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        occurrence = session.get(Occurrence, run.occurrence_id)
        blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
        if (
            demand is not None
            and blob is not None
            and demand.generation == run.demand_generation
            and demand.retry_attempt == run.retry_attempt
        ):
            settle_demand_after_execution_failure(
                demand,
                blob,
                cause=str(run.run_spec.get("reason", "initial")),
                error_code=code,
                retryable=True,
                settings=settings,
                now=current,
            )
        release_execution_slot_for_run(session, run.id)
        operation_log(
            session,
            action="analysis.frozen.recovery",
            target_type="analysis_run",
            target_id=run.id,
            workspace_id=occurrence.workspace_id if occurrence else None,
            result=run.status,
            details={
                "attempt_id": intent.attempt_id,
                "generation": execution.generation if execution is not None else None,
                "error_code": code,
            },
        )
        recovered += 1
    session.flush()
    return recovered
