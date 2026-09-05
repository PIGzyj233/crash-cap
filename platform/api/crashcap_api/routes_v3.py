from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from .errors import ApiError
from .ids import new_id
from .models import ArtifactEntry, CatalogFile, Occurrence, OccurrenceVersionAudit, Upload
from .response_contracts import ERROR_RESPONSES
from .response_models import (
    ArtifactEntryResponse,
    ArtifactPageResponse,
    OccurrenceVersionResponse,
    UploadCompletionResponse,
    UploadInitResponse,
)
from .routes import DispatcherDep, SessionDep, SettingsDep, StoreDep
from .schemas import OccurrenceVersionPatch, UploadComplete, UploadV3Init
from .services.uploads import complete_upload, initialize_upload, upload_completion_view

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)


@router.post("/uploads:init", response_model=UploadInitResponse, status_code=201)
def initialize_v3_upload(
    body: UploadV3Init, request: Request, session: SessionDep, store: StoreDep
) -> dict[str, Any]:
    _upload, response = initialize_upload(
        session,
        store,
        workspace_id=body.workspace_id,
        file_kind=body.file_kind,
        filename=body.filename,
        size=body.size,
        sha256_hint=body.sha256,
        capture_profile=None,
        reported_at=None,
        request=request,
        version=body.version,
        source=body.source,
    )
    return response


@router.post("/uploads/{upload_id}:complete", response_model=UploadCompletionResponse)
def complete_v3_upload(
    upload_id: str,
    body: UploadComplete,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    return complete_upload(
        session,
        store,
        dispatcher,
        settings,
        upload_id=upload_id,
        multipart_upload_id=body.multipart_upload_id,
        parts=[part.model_dump() for part in body.parts],
        request=request,
    )


@router.get("/uploads/{upload_id}", response_model=UploadCompletionResponse)
def get_v3_upload(upload_id: str, session: SessionDep) -> dict[str, Any]:
    upload = session.get(Upload, upload_id)
    if upload is None:
        raise ApiError("NOT_FOUND", "Upload was not found", status_code=404)
    return upload_completion_view(session, upload)


@router.get("/artifacts", response_model=ArtifactPageResponse)
def list_v3_artifacts(
    session: SessionDep,
    workspace_id: str | None = None,
    version: str | None = None,
    filename: str | None = None,
    availability: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
) -> dict[str, Any]:
    statement = (
        select(ArtifactEntry, CatalogFile)
        .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
        .where(ArtifactEntry.workspace_id == workspace_id)
    )
    if version is not None:
        statement = statement.where(ArtifactEntry.version == version)
    if filename is not None:
        statement = statement.where(func.lower(ArtifactEntry.name).contains(filename.casefold()))
    if availability is not None:
        statement = statement.where(ArtifactEntry.availability == availability)
    if cursor is not None:
        statement = statement.where(ArtifactEntry.id < cursor)
    rows = session.execute(statement.order_by(ArtifactEntry.id.desc()).limit(limit + 1)).all()
    page, more = rows[:limit], len(rows) > limit
    return {
        "items": [
            {
                "id": entry.id,
                "file_id": file.id,
                "workspace_id": entry.workspace_id,
                "name": entry.name,
                "version": entry.version,
                "kind": entry.kind,
                "sha256": file.raw_sha256,
                "size": file.raw_size,
                "code_id": file.code_id,
                "debug_id": file.debug_id,
                "availability": entry.availability,
                "source": entry.source,
                "created_at": entry.created_at.isoformat(),
            }
            for entry, file in page
        ],
        "next_cursor": page[-1][0].id if more and page else None,
    }


@router.get("/artifacts/{artifact_id}", response_model=ArtifactEntryResponse)
def get_v3_artifact(artifact_id: str, session: SessionDep) -> dict[str, Any]:
    row = session.execute(
        select(ArtifactEntry, CatalogFile)
        .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
        .where(ArtifactEntry.id == artifact_id)
    ).one_or_none()
    if row is None:
        raise ApiError("NOT_FOUND", "Artifact was not found", status_code=404)
    entry, file = row
    return {
        "id": entry.id,
        "file_id": file.id,
        "workspace_id": entry.workspace_id,
        "name": entry.name,
        "version": entry.version,
        "kind": entry.kind,
        "sha256": file.raw_sha256,
        "size": file.raw_size,
        "code_id": file.code_id,
        "debug_id": file.debug_id,
        "availability": entry.availability,
        "source": entry.source,
        "created_at": entry.created_at.isoformat(),
    }


@router.patch("/occurrences/{occurrence_id}/version", response_model=OccurrenceVersionResponse)
def patch_occurrence_version(
    occurrence_id: str, body: OccurrenceVersionPatch, session: SessionDep
) -> dict[str, Any]:
    occurrence = session.scalar(
        select(Occurrence).where(Occurrence.id == occurrence_id).with_for_update()
    )
    if occurrence is None:
        raise ApiError("NOT_FOUND", "Occurrence was not found", status_code=404)
    old_version = occurrence.version
    occurrence.version = body.version
    changed_at = datetime.now(UTC)
    session.add(
        OccurrenceVersionAudit(
            id=new_id("ova"),
            occurrence_id=occurrence.id,
            old_version=old_version,
            new_version=body.version,
            source="manual",
            created_at=changed_at,
        )
    )
    session.commit()
    return {
        "occurrence_id": occurrence.id,
        "version": occurrence.version,
        "updated_at": changed_at.isoformat(),
    }
