"""Review existing reports without rewriting their original selection decisions."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import validate_contract
from .errors import ApiError
from .frozen_inputs import canonical_bytes
from .models import Occurrence, ResultReview
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep, SettingsDep, StoreDep
from .services.current_decisions import parse_evidence_json
from .services.result_reviews import (
    commit_result_review,
    prepare_result_review,
    read_review_object,
    validate_review_audit,
)

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)
REVIEW_PATH = "/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReviewBasisReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    review_id: str = Field(min_length=1, max_length=100)
    evidence_sha256: Sha256


class ResultReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["result-review-request-v1"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    current_run_id: str = Field(min_length=1, max_length=100)
    candidate_run_id: str = Field(min_length=1, max_length=100)
    current_canonical_sha256: Sha256
    candidate_canonical_sha256: Sha256
    cause: Literal["engine_upgrade", "role_change", "evidence_correction"]
    reviewed_by: str = Field(min_length=1, max_length=200, pattern=r"\S")
    rationale: str = Field(min_length=1, max_length=4000, pattern=r"\S")
    basis_reviews: list[ReviewBasisReference] = Field(max_length=200)


class ResultReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    occurrence_id: str
    current_run_id: str
    candidate_run_id: str
    request: ResultReviewRequest
    request_sha256: str
    audit_sha256: str
    cause: Literal["engine_upgrade", "role_change", "evidence_correction"]
    decision: Literal["promote", "retain", "incomparable", "correct"]
    reason: str
    created_at: datetime


class ResultReviewPage(BaseModel):
    items: list[ResultReviewResponse]
    next_cursor: str | None


class ProviderBasisView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    pair_id: str
    qualification_version: int
    state: Literal["active", "withdrawn"]
    reason: str
    object_key: str
    sha256: Sha256


class ResultReviewAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["result-review-audit-v1"]
    review_id: str
    occurrence_id: str
    request: ResultReviewRequest
    request_sha256: Sha256
    created_at: datetime
    current_evidence: dict[str, JsonValue]
    candidate_evidence: dict[str, JsonValue]
    provider_basis: list[ProviderBasisView]


def _require_occurrence(session: Session, workspace_id: str, occurrence_id: str) -> None:
    occurrence = session.get(Occurrence, occurrence_id)
    if occurrence is None or occurrence.workspace_id != workspace_id:
        raise ApiError("NOT_FOUND", "Occurrence was not found in this Workspace", status_code=404)


@router.get(REVIEW_PATH, response_model=ResultReviewPage)
def list_result_reviews(
    workspace_id: str,
    occurrence_id: str,
    session: SessionDep,
    cursor: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
) -> ResultReviewPage:
    _require_occurrence(session, workspace_id, occurrence_id)
    query = select(ResultReview).where(ResultReview.occurrence_id == occurrence_id)
    if cursor is not None:
        query = query.where(ResultReview.id < cursor)
    rows = list(session.scalars(query.order_by(ResultReview.id.desc()).limit(limit + 1)))
    return ResultReviewPage(
        items=[ResultReviewResponse.model_validate(row) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get(REVIEW_PATH + "/{review_id}", response_model=ResultReviewResponse)
def get_result_review(
    workspace_id: str, occurrence_id: str, review_id: str, session: SessionDep
) -> ResultReviewResponse:
    _require_occurrence(session, workspace_id, occurrence_id)
    row = session.get(ResultReview, review_id)
    if row is None or row.occurrence_id != occurrence_id:
        raise ApiError("NOT_FOUND", "Review was not found for this Occurrence", status_code=404)
    return ResultReviewResponse.model_validate(row)


@router.get(
    REVIEW_PATH + "/{review_id}/evidence",
    responses={200: {"model": ResultReviewAudit}},
)
def get_result_review_evidence(
    workspace_id: str,
    occurrence_id: str,
    review_id: str,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> Response:
    _require_occurrence(session, workspace_id, occurrence_id)
    row = session.get(ResultReview, review_id)
    if row is None or row.occurrence_id != occurrence_id:
        raise ApiError("NOT_FOUND", "Review was not found for this Occurrence", status_code=404)
    key, sha = row.audit_object_key, row.audit_sha256
    expected = {
        "review_id": row.id,
        "occurrence_id": row.occurrence_id,
        "request": row.request,
        "request_sha256": row.request_sha256,
        "current_evidence": row.current_evidence,
        "candidate_evidence": row.candidate_evidence,
    }
    session.rollback()
    try:
        payload = read_review_object(store, key, sha)
    except (OSError, BotoCoreError, ClientError) as exc:
        raise ApiError(
            "STORAGE_ERROR", "Review evidence is temporarily unavailable", status_code=503
        ) from exc
    audit = parse_evidence_json(payload, "result review audit")
    validate_review_audit(audit, settings.schema_root)
    if any(audit[field] != value for field, value in expected.items()):
        raise ApiError(
            "REVIEW_AUDIT_INVALID", "Audit differs from its review record", status_code=409
        )
    # Historical audit reads do not requalify providers against today's catalog.
    return Response(content=payload, media_type="application/json")


@router.post(REVIEW_PATH, response_model=ResultReviewResponse)
def submit_result_review(
    workspace_id: str,
    occurrence_id: str,
    body: ResultReviewRequest,
    request: Request,
    settings: SettingsDep,
    store: StoreDep,
) -> ResultReviewResponse:
    if not settings.result_reviews_enabled:
        raise ApiError("QUALIFICATION_PENDING", "Result reviews are disabled", status_code=503)
    payload = body.model_dump()
    validate_contract(
        payload,
        settings.schema_root / "drafts/qa-symbol-import/result-review-request-v1.schema.json",
        "result review request",
    )
    request_sha = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    sessions = request.app.state.database.sessions

    def replay() -> ResultReviewResponse | None:
        # A completed request must be recoverable even after Current or storage changes.
        with sessions() as session:
            _require_occurrence(session, workspace_id, occurrence_id)
            row = session.scalar(
                select(ResultReview).where(
                    ResultReview.occurrence_id == occurrence_id,
                    ResultReview.idempotency_key == body.idempotency_key,
                )
            )
            if row is None:
                return None
            if row.request_sha256 != request_sha:
                raise ApiError(
                    "IDEMPOTENCY_CONFLICT",
                    "Review key was used for another request",
                    status_code=409,
                )
            return ResultReviewResponse.model_validate(row)

    existing = replay()
    if existing is not None:
        return existing
    try:
        prepared = prepare_result_review(
            sessions, store, occurrence_id, payload, schema_root=settings.schema_root
        )
    except (ApiError, OSError, BotoCoreError, ClientError) as exc:
        # Another identical request may have completed between lookup and preparation.
        existing = replay()
        if existing is not None:
            return existing
        if isinstance(exc, ApiError):
            raise
        raise ApiError(
            "STORAGE_ERROR", "Review evidence is temporarily unavailable", status_code=503
        ) from exc
    with sessions.begin() as session:
        _require_occurrence(session, workspace_id, occurrence_id)
        row = commit_result_review(session, prepared, settings)
        return ResultReviewResponse.model_validate(row)
