"""Bounded report history with persisted Current selection decisions."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator
from sqlalchemy import select

from .errors import ApiError
from .models import AnalysisRun, CurrentDecision, Occurrence
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)


class HistoryDecision(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    observed_current_run_id: str | None
    rule_version: str
    decision: Literal["promote", "retain", "incomparable", "correct"]
    reason: str
    retry_recommended: bool


class AnalysisHistoryEntry(BaseModel):
    id: str
    status: str
    schema_version: str
    started_at: datetime | None
    finished_at: datetime | None
    report_available: bool
    error_code: str | None
    selection: HistoryDecision | None

    @field_validator("started_at", "finished_at")
    @classmethod
    def normalize_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AnalysisHistoryPage(BaseModel):
    current_run_id: str | None
    items: list[AnalysisHistoryEntry]
    next_cursor: str | None


class EvidenceDifference(BaseModel):
    path: str
    before: JsonValue
    after: JsonValue


class EvidenceDifferencePage(BaseModel):
    candidate_run_id: str
    selection: HistoryDecision
    items: list[EvidenceDifference]
    total: int
    next_offset: int | None


@router.get(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history/{run_id}/differences",
    response_model=EvidenceDifferencePage,
)
def get_analysis_differences(
    workspace_id: str,
    occurrence_id: str,
    run_id: str,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> EvidenceDifferencePage:
    occurrence = session.get(Occurrence, occurrence_id)
    if occurrence is None or occurrence.workspace_id != workspace_id:
        raise ApiError("NOT_FOUND", "Occurrence was not found in this Workspace", status_code=404)
    decision = session.get(CurrentDecision, run_id)
    if decision is None or decision.occurrence_id != occurrence_id:
        raise ApiError("NOT_FOUND", "No recorded selection decision for this Run", status_code=404)
    total = len(decision.differences)
    return EvidenceDifferencePage(
        candidate_run_id=run_id,
        selection=HistoryDecision.model_validate(decision),
        items=[
            EvidenceDifference.model_validate(item)
            for item in decision.differences[offset : offset + limit]
        ],
        total=total,
        next_offset=offset + limit if offset + limit < total else None,
    )


@router.get(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-history",
    response_model=AnalysisHistoryPage,
)
def list_analysis_history(
    workspace_id: str,
    occurrence_id: str,
    session: SessionDep,
    cursor: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> AnalysisHistoryPage:
    occurrence = session.get(Occurrence, occurrence_id)
    if occurrence is None or occurrence.workspace_id != workspace_id:
        raise ApiError("NOT_FOUND", "Occurrence was not found in this Workspace", status_code=404)
    query = select(AnalysisRun).where(AnalysisRun.occurrence_id == occurrence_id)
    if cursor is not None:
        query = query.where(AnalysisRun.id < cursor)
    runs = list(session.scalars(query.order_by(AnalysisRun.id.desc()).limit(limit + 1)))
    page = runs[:limit]
    decisions = {
        row.candidate_run_id: row
        for row in session.scalars(
            select(CurrentDecision).where(
                CurrentDecision.occurrence_id == occurrence_id,
                CurrentDecision.candidate_run_id.in_([run.id for run in page]),
            )
        )
    }
    return AnalysisHistoryPage(
        current_run_id=occurrence.current_run_id,
        items=[
            AnalysisHistoryEntry(
                id=run.id,
                status=run.status,
                schema_version=run.schema_version,
                started_at=run.started_at,
                finished_at=run.finished_at,
                report_available=bool(run.result_object_key),
                error_code=run.error_code,
                selection=HistoryDecision.model_validate(decisions[run.id])
                if run.id in decisions
                else None,
            )
            for run in page
        ],
        next_cursor=page[-1].id if len(runs) > limit else None,
    )
