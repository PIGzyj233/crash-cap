from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .ids import new_ulid
from .models import (
    AnalysisRun,
    Artifact,
    Build,
    Occurrence,
    TaskExecution,
    TaskIntent,
    Upload,
    utcnow,
)
from .services.analysis import analysis_task_message
from .services.common import operation_log
from .task_handoff import create_task_intent, request_task_redelivery, task_identity


def reconcile_task_intents(
    session: Session,
    settings: Settings,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
) -> dict[str, Any]:
    """Scan recoverable historical work; mutate only when the caller explicitly applies."""

    candidates = _candidates(session, settings)
    if after:
        candidates = [item for item in candidates if str(item["cursor"]) > after]
    selected = candidates[: max(1, limit)]
    created = 0
    reopened = 0
    if apply:
        for item in selected:
            message = dict(item.pop("_message"))
            if item["action"] == "create":
                intent = create_task_intent(session, message, settings.schema_root)
                item["attempt_id"] = intent.attempt_id
                created += 1
            elif item["action"] == "reopen":
                decision = request_task_redelivery(session, message, settings.schema_root)
                item["attempt_id"] = decision.message["attempt_id"]
                item["dispatch_state"] = decision.dispatch_state
                reopened += int(decision.reopened)
            operation_log(
                session,
                action="task.reconcile",
                target_type=str(item["target_type"]),
                target_id=str(item["target_id"]),
                workspace_id=str(item["workspace_id"]),
                result=str(item["action"]),
                details={
                    "task_type": item["task_type"],
                    "attempt_id": item["attempt_id"],
                },
            )
        session.flush()
    else:
        for item in selected:
            item.pop("_message")
    return {
        "mode": "apply" if apply else "dry-run",
        "scanned_count": len(candidates),
        "selected_count": len(selected),
        "created_count": created,
        "reopened_count": reopened,
        "next_cursor": selected[-1]["cursor"] if len(candidates) > len(selected) else None,
        "items": selected,
    }


def _candidates(session: Session, settings: Settings) -> list[dict[str, Any]]:
    now = utcnow()
    rows: list[dict[str, Any]] = []
    for upload in session.scalars(
        select(Upload).where(Upload.verification_status == "VERIFYING").order_by(Upload.id)
    ):
        message = {
            "schema_version": "1.0",
            "task_type": "verify_upload",
            "upload_id": upload.id,
            "attempt_id": f"att_{new_ulid()}",
            "queue": "verify",
        }
        candidate = _candidate(session, message, upload.workspace_id, "upload", upload.id, now)
        if candidate:
            rows.append(candidate)

    artifacts = session.execute(
        select(Artifact, Build)
        .join(Build, Build.id == Artifact.build_id)
        .where(Artifact.verification_status == "pending")
        .order_by(Artifact.id)
    ).all()
    for artifact, build in artifacts:
        message = {
            "schema_version": "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": artifact.id,
            "attempt_id": f"att_{new_ulid()}",
            "queue": "ingest",
        }
        candidate = _candidate(session, message, build.workspace_id, "artifact", artifact.id, now)
        if candidate:
            rows.append(candidate)

    runs = session.execute(
        select(AnalysisRun, Occurrence)
        .join(Occurrence, Occurrence.id == AnalysisRun.occurrence_id)
        .where(AnalysisRun.status.in_(["UPLOADED", "QUEUED"]))
        .order_by(AnalysisRun.id)
    ).all()
    for run, occurrence in runs:
        message = analysis_task_message(session, run)
        candidate = _candidate(
            session,
            message,
            occurrence.workspace_id,
            "analysis_run",
            run.id,
            now,
        )
        if candidate:
            rows.append(candidate)
    rows.sort(key=lambda item: str(item["cursor"]))
    return rows


def _candidate(
    session: Session,
    message: dict[str, Any],
    workspace_id: str,
    target_type: str,
    target_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    identity = task_identity(message)
    execution = session.get(
        TaskExecution,
        {"task_type": identity.task_type, "logical_key": identity.logical_key},
    )
    if execution is not None and _active(execution, now):
        return None
    intent = session.scalar(
        select(TaskIntent).where(
            TaskIntent.task_type == identity.task_type,
            TaskIntent.logical_key == identity.logical_key,
        )
    )
    if intent is not None and intent.state in {"pending", "publishing"}:
        return None
    action = "create" if intent is None else "reopen"
    canonical_message = dict(intent.message) if intent is not None else message
    return {
        "cursor": f"{identity.task_type}:{target_id}",
        "task_type": identity.task_type,
        "target_type": target_type,
        "target_id": target_id,
        "workspace_id": workspace_id,
        "attempt_id": canonical_message["attempt_id"],
        "action": action,
        "_message": canonical_message,
    }


def _active(execution: TaskExecution, now: datetime) -> bool:
    if execution.outcome != "running" or execution.lease_until is None:
        return False
    lease = execution.lease_until
    if lease.tzinfo is None:
        lease = lease.replace(tzinfo=UTC)
    comparison = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return lease > comparison
