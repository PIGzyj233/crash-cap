"""Manual submission labels and bounded, Workspace-scoped verified history."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from .errors import ApiError
from .models import Occurrence, OccurrenceSubmission
from .response_contracts import ERROR_RESPONSES
from .response_models import UploadInitResponse
from .routes import SessionDep, SettingsDep, StoreDep
from .schemas import DumpUploadInit
from .services.uploads import create_upload_record, presigned_upload_response

router = APIRouter(prefix="/api/v2", responses=ERROR_RESPONSES)


class SubmissionUploadInit(DumpUploadInit):
    label: str | None = Field(default=None, min_length=1, max_length=256)
    batch: str | None = Field(default=None, min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=512)


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    upload_id: str
    label: str | None
    batch: str | None
    source: str
    filename: str
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


@router.post(
    "/workspaces/{workspace_id}/uploads",
    status_code=201,
    response_model=UploadInitResponse,
    response_model_exclude_unset=True,
)
def initialize_submission(
    workspace_id: str,
    body: SubmissionUploadInit,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> dict[str, Any]:
    if not settings.automatic_analysis_enabled:
        raise ApiError("FEATURE_DISABLED", "QA submission uploads are disabled", status_code=409)
    upload = create_upload_record(
        session,
        workspace_id=workspace_id,
        build_id=None,
        file_kind="dmp",
        filename=body.filename,
        size=body.size,
        sha256_hint=body.sha256,
        capture_profile=body.capture_profile,
        reported_build_id=body.reported_build_id,
        reported_at=body.reported_at,
        request=request,
    )
    session.add(
        OccurrenceSubmission(
            upload_id=upload.id,
            label=body.label,
            batch=body.batch,
            source=body.source,
            filename=upload.original_filename,
            submitted_at=upload.uploaded_at,
        )
    )
    session.commit()
    return presigned_upload_response(store, upload)


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
