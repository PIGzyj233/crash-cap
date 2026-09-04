"""Read-only provenance for provider review of catalog candidates."""

import hashlib
import json
from typing import Literal

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from .errors import ApiError
from .models import CatalogPair, CatalogPairOrigin, CatalogPairReview
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep, SettingsDep, StoreDep
from .services.symbol_catalog import CatalogError, review_pair

router = APIRouter(prefix="/api/v2/symbol-catalog", responses=ERROR_RESPONSES)


class CatalogReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    state: Literal["active", "withdrawn"]
    reason: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=256)
    evidence: str = Field(min_length=1, max_length=32000)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("reason", "reviewer", "evidence", "idempotency_key")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Review fields must not be blank")
        return value


class CatalogReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pair_id: str
    qualification_version: int
    state: Literal["active", "withdrawn"]
    reason: str
    evidence_sha256: str


class CatalogReviewPage(BaseModel):
    items: list[CatalogReviewResponse]
    next_version: int | None


class CatalogReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["catalog-provider-review-v1"]
    pair_id: str
    expected_version: int
    state: Literal["active", "withdrawn"]
    reason: str
    reviewer: str
    evidence: str


@router.get("/pairs/{pair_id}/reviews", response_model=CatalogReviewPage)
def list_pair_reviews(
    pair_id: str,
    session: SessionDep,
    before_version: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
) -> CatalogReviewPage:
    if session.get(CatalogPair, pair_id) is None:
        raise ApiError("NOT_FOUND", "Catalog pair was not found", status_code=404)
    query = select(CatalogPairReview).where(CatalogPairReview.pair_id == pair_id)
    if before_version is not None:
        query = query.where(CatalogPairReview.qualification_version < before_version)
    rows = list(
        session.scalars(
            query.order_by(CatalogPairReview.qualification_version.desc()).limit(limit + 1)
        )
    )
    return CatalogReviewPage(
        items=[CatalogReviewResponse.model_validate(row) for row in rows[:limit]],
        next_version=rows[limit - 1].qualification_version if len(rows) > limit else None,
    )


@router.get("/pairs/{pair_id}/reviews/{review_id}/evidence", response_model=CatalogReviewEvidence)
def get_review_evidence(
    pair_id: str,
    review_id: str,
    session: SessionDep,
    store: StoreDep,
) -> CatalogReviewEvidence:
    review = session.get(CatalogPairReview, review_id)
    if review is None or review.pair_id != pair_id:
        raise ApiError("NOT_FOUND", "Review was not found for this pair", status_code=404)
    key, sha = review.evidence_object_key, review.evidence_sha256
    expected = (review.pair_id, review.qualification_version - 1, review.state, review.reason)
    session.rollback()
    payload = bytearray()
    try:
        for chunk in store.stream(key):
            if len(payload) + len(chunk) > 160000:
                raise ApiError(
                    "CONFLICT", "Review evidence exceeds the supported size", status_code=409
                )
            payload.extend(chunk)
    except (OSError, BotoCoreError, ClientError) as exc:
        raise ApiError(
            "STORAGE_ERROR", "Review evidence is temporarily unavailable", status_code=503
        ) from exc
    if hashlib.sha256(payload).hexdigest() != sha:
        raise ApiError("STORAGE_ERROR", "Review evidence integrity check failed", status_code=503)
    try:
        evidence = CatalogReviewEvidence.model_validate_json(payload)
    except ValidationError as exc:
        raise ApiError(
            "CONFLICT", "Review evidence format is not supported", status_code=409
        ) from exc
    if (evidence.pair_id, evidence.expected_version, evidence.state, evidence.reason) != expected:
        raise ApiError(
            "STORAGE_ERROR", "Review evidence does not match its record", status_code=503
        )
    return evidence


@router.post("/pairs/{pair_id}/reviews", response_model=CatalogReviewResponse)
def submit_pair_review(
    pair_id: str,
    body: CatalogReviewRequest,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> CatalogReviewResponse:
    if not settings.catalog_reviews_enabled:
        raise ApiError("FEATURE_DISABLED", "Catalog review writes are disabled", status_code=409)
    if session.get(CatalogPair, pair_id) is None:
        raise ApiError("NOT_FOUND", "Catalog pair was not found", status_code=404)
    # End the read transaction before object I/O; review_pair rechecks the version
    # under the catalog lock. Evidence is immutable and content-addressed.
    session.rollback()
    evidence = json.dumps(
        {
            "schema_version": "catalog-provider-review-v1",
            "pair_id": pair_id,
            **body.model_dump(exclude={"idempotency_key"}),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sha256 = hashlib.sha256(evidence).hexdigest()
    key = f"catalog-review-evidence/{sha256}.json"
    hasher = hashlib.sha256()
    size = 0
    try:
        store.put_bytes(key, evidence, "application/json")
        for chunk in store.stream(key):
            size += len(chunk)
            if size > len(evidence):
                raise ApiError("STORAGE_ERROR", "Review evidence readback failed", status_code=503)
            hasher.update(chunk)
    except (OSError, BotoCoreError, ClientError) as exc:
        raise ApiError(
            "STORAGE_ERROR", "Review evidence could not be saved and verified", status_code=503
        ) from exc
    if size != len(evidence) or hasher.hexdigest() != sha256:
        raise ApiError("STORAGE_ERROR", "Review evidence readback failed", status_code=503)
    try:
        review = review_pair(
            session,
            pair_id,
            expected_version=body.expected_version,
            state=body.state,
            reason=body.reason,
            evidence_object_key=key,
            evidence_sha256=sha256,
            idempotency_key=body.idempotency_key,
        )
        session.commit()
    except CatalogError as exc:
        session.rollback()
        raise ApiError("CONFLICT", str(exc), status_code=409) from exc
    return CatalogReviewResponse.model_validate(review)


class CatalogOriginView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    origin_type: Literal["import_item", "build_artifacts", "publication"]
    origin_key: str
    source_workspace_id: str | None
    build_id: str | None
    import_id: str | None = None
    source_label: str | None = None


class CatalogPairOrigins(BaseModel):
    pair_id: str
    code_id: str
    debug_id: str
    architecture: str
    state: Literal["active", "withdrawn"]
    qualification_version: int
    items: list[CatalogOriginView]
    next_cursor: str | None


@router.get("/pairs/{pair_id}/origins", response_model=CatalogPairOrigins)
def get_pair_origins(
    pair_id: str,
    session: SessionDep,
    cursor: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
) -> CatalogPairOrigins:
    pair = session.get(CatalogPair, pair_id)
    if pair is None:
        raise ApiError("NOT_FOUND", "Catalog pair was not found", status_code=404)
    query = select(CatalogPairOrigin).where(CatalogPairOrigin.pair_id == pair_id)
    if cursor is not None:
        query = query.where(CatalogPairOrigin.id > cursor)
    rows = list(session.scalars(query.order_by(CatalogPairOrigin.id).limit(limit + 1)))
    state = pair.state
    if state not in ("active", "withdrawn"):
        raise ApiError("INTERNAL_ERROR", "Catalog pair state is invalid", status_code=500)
    return CatalogPairOrigins(
        pair_id=pair.id,
        code_id=pair.code_id,
        debug_id=pair.debug_id,
        architecture=pair.architecture,
        state="active" if state == "active" else "withdrawn",
        qualification_version=pair.qualification_version,
        items=[
            CatalogOriginView.model_validate(row).model_copy(
                update={
                    "import_id": row.details.get("import_id")
                    if row.origin_type == "import_item"
                    and isinstance(row.details.get("import_id"), str)
                    else None,
                    "source_label": row.details.get("source_label")
                    if isinstance(row.details.get("source_label"), str)
                    else None,
                }
            )
            for row in rows[:limit]
        ],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )
