"""Manual submission labels and bounded, Workspace-scoped verified history."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select

from .errors import ApiError
from .models import Occurrence, OccurrenceSubmission
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    upload_id: str
    label: str | None
    batch: str | None
    source: str
    filename: str
    version: str | None
    submitted_at: datetime
    verified_at: datetime

    @field_validator("submitted_at", "verified_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        # SQLite drops timezone metadata; persisted timestamps are UTC.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SubmissionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SubmissionResponse]
    next_cursor: str | None


@router.get(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/submissions",
    response_model=SubmissionPage,
)
def list_submissions(
    workspace_id: str,
    occurrence_id: str,
    session: SessionDep,
    cursor: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> SubmissionPage:
    occurrence = session.get(Occurrence, occurrence_id)
    if occurrence is None or occurrence.workspace_id != workspace_id:
        raise ApiError("NOT_FOUND", "Occurrence was not found in this Workspace", status_code=404)
    query = select(OccurrenceSubmission).where(
        OccurrenceSubmission.occurrence_id == occurrence_id,
        OccurrenceSubmission.verified_at.is_not(None),
    )
    if cursor is not None:
        query = query.where(OccurrenceSubmission.upload_id > cursor)
    rows = list(session.scalars(query.order_by(OccurrenceSubmission.upload_id).limit(limit + 1)))
    return SubmissionPage(
        items=[SubmissionResponse.model_validate(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].upload_id if len(rows) > limit else None,
    )
