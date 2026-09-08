"""Enqueue and inspect cache-only Windows PDB fetches."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import ApiError
from .identity import current_principal
from .ids import new_ulid
from .models import AnalysisRun, Occurrence, PublicSymbolJob, PublicSymbolRequest
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep, SettingsDep
from .services.common import operation_log
from .task_handoff import stage_task_message

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)


class PublicSymbolJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"\S")


class PublicSymbolJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    items: list[dict[str, JsonValue]]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _occurrence(
    session: Session, workspace_id: str, occurrence_id: str, *, lock: bool = False
) -> Occurrence:
    query = select(Occurrence).where(
        Occurrence.id == occurrence_id, Occurrence.workspace_id == workspace_id
    )
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise ApiError("NOT_FOUND", "Occurrence was not found in this Workspace", status_code=404)
    return row


@router.get(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/public-symbol-jobs",
    response_model=PublicSymbolJobResponse | None,
)
def get_public_symbol_job(
    workspace_id: str, occurrence_id: str, session: SessionDep
) -> PublicSymbolJob | None:
    _occurrence(session, workspace_id, occurrence_id)
    return session.scalar(
        select(PublicSymbolJob)
        .where(PublicSymbolJob.occurrence_id == occurrence_id)
        .order_by(PublicSymbolJob.created_at.desc(), PublicSymbolJob.id.desc())
        .limit(1)
    )


@router.post(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/public-symbol-jobs",
    response_model=PublicSymbolJobResponse,
    status_code=202,
)
def create_public_symbol_job(
    workspace_id: str,
    occurrence_id: str,
    body: PublicSymbolJobRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> PublicSymbolJob:
    occurrence = _occurrence(session, workspace_id, occurrence_id, lock=True)
    prior = session.get(PublicSymbolRequest, (occurrence_id, body.idempotency_key))
    if prior is not None:
        existing = session.get(PublicSymbolJob, prior.job_id)
        assert existing is not None
        return existing
    active = session.scalar(
        select(PublicSymbolJob).where(
            PublicSymbolJob.occurrence_id == occurrence_id,
            PublicSymbolJob.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        session.add(
            PublicSymbolRequest(
                occurrence_id=occurrence_id, idempotency_key=body.idempotency_key, job_id=active.id
            )
        )
        session.commit()
        return active
    source = (
        session.get(AnalysisRun, occurrence.current_run_id) if occurrence.current_run_id else None
    )
    if source is None:
        source = session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.occurrence_id == occurrence_id, AnalysisRun.schema_version == "2.0")
            .order_by(AnalysisRun.id.desc())
            .limit(1)
        )
    if source is None or not source.run_spec:
        raise ApiError(
            "PUBLIC_SYMBOL_EVIDENCE_UNAVAILABLE",
            "尚无可用的模块检查结果，请等待输入检查完成",
            status_code=409,
        )
    row = PublicSymbolJob(
        id=f"psj_{new_ulid()}",
        workspace_id=workspace_id,
        occurrence_id=occurrence_id,
        source_run_id=source.id,
        idempotency_key=body.idempotency_key,
        requested_by_user_id=current_principal.get().user_id,
        status="queued",
        items=[],
    )
    session.add(row)
    session.flush()
    session.add(
        PublicSymbolRequest(
            occurrence_id=occurrence_id, idempotency_key=body.idempotency_key, job_id=row.id
        )
    )
    stage_task_message(
        session,
        settings,
        {
            "schema_version": "1.2",
            "task_type": "fetch_public_symbols",
            "job_id": row.id,
            "attempt_id": f"att_{new_ulid()}",
            "queue": "public-symbols",
            "request_id": request.state.request_id,
        },
    )
    operation_log(
        session,
        action="public_symbols.request",
        target_type="public_symbol_job",
        target_id=row.id,
        workspace_id=workspace_id,
        request=request,
        details={"source_run_id": source.id, "cache_only": True},
    )
    session.commit()
    return row
