from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from .models import Workspace
from .response_contracts import ERROR_RESPONSES
from .response_models import (
    ArtifactDetailResponse,
    ArtifactPageResponse,
    SymbolIssueDetailResponse,
    SymbolIssuePageResponse,
)
from .routes import SessionDep
from .services import workspace_browser as browser
from .services.common import require_row

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=2048)]
TextFilter = Annotated[str | None, Query(max_length=200)]
Availability = Literal[
    "waiting_for_pair",
    "symbols_available",
    "identity_conflict",
    "no_debug_identity",
    "storage_unavailable",
]


@router.get("/workspaces/{workspace_id}/symbol-issues", response_model=SymbolIssuePageResponse)
def list_symbol_issues(
    workspace_id: str,
    session: SessionDep,
    q: TextFilter = None,
    limit: Limit = 30,
    cursor: Cursor = None,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return browser.symbol_issues(session, workspace_id, q=q, limit=limit, cursor=cursor)


@router.get(
    "/workspaces/{workspace_id}/symbol-issues/{issue_id}",
    response_model=SymbolIssueDetailResponse,
)
def get_symbol_issue(
    workspace_id: str,
    issue_id: str,
    session: SessionDep,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return browser.symbol_issue_detail(session, workspace_id, issue_id)


@router.get("/workspaces/{workspace_id}/artifacts", response_model=ArtifactPageResponse)
def list_workspace_artifacts(
    workspace_id: str,
    session: SessionDep,
    origin: Literal["all", "workspace", "public"] = "all",
    uploaded_by_user_id: TextFilter = None,
    filename: TextFilter = None,
    version: TextFilter = None,
    kind: Literal["pe", "pdb"] | None = None,
    availability: Availability | None = None,
    symbol_issue_id: TextFilter = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return browser.artifact_page(
        session,
        workspace_id,
        origin=origin,
        uploaded_by_user_id=uploaded_by_user_id,
        filename=filename,
        version=version,
        kind=kind,
        state=availability,
        issue_id=symbol_issue_id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/workspaces/{workspace_id}/artifacts/{artifact_id}",
    response_model=ArtifactDetailResponse,
)
def get_workspace_artifact(
    workspace_id: str,
    artifact_id: str,
    session: SessionDep,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return browser.artifact_detail(session, workspace_id, artifact_id)


@router.get("/public/artifacts", response_model=ArtifactPageResponse)
def list_public_artifacts(
    session: SessionDep,
    uploaded_by_user_id: TextFilter = None,
    filename: TextFilter = None,
    version: TextFilter = None,
    kind: Literal["pe", "pdb"] | None = None,
    availability: Availability | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> dict[str, Any]:
    return browser.artifact_page(
        session,
        None,
        uploaded_by_user_id=uploaded_by_user_id,
        filename=filename,
        version=version,
        kind=kind,
        state=availability,
        limit=limit,
        cursor=cursor,
    )


@router.get("/public/artifacts/{artifact_id}", response_model=ArtifactDetailResponse)
def get_public_artifact(artifact_id: str, session: SessionDep) -> dict[str, Any]:
    return browser.artifact_detail(session, None, artifact_id)
