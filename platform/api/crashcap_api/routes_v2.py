"""Compatible result reads installed before the global-symbol writer rollout."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .canonical_reader import READER_VERSIONS, require_canonical_version
from .errors import ApiError
from .ids import new_ulid
from .models import AnalysisRun, Occurrence, utcnow
from .response_contracts import (
    CANONICAL_V2_RESPONSE,
    ERROR_RESPONSES,
    canonical_section_v2_response,
)
from .routes import SessionDep, SettingsDep, StoreDep, _load_canonical, _resolve_analysis_run
from .services.common import operation_log, require_row
from .services.workspace_policies import declare_workspace_module_role
from .task_handoff import create_task_intent

router = APIRouter(prefix="/api/v2", responses=ERROR_RESPONSES)


class CapabilitiesResponse(BaseModel):
    reader_versions: list[str]
    enabled_writes: list[str]
    pause_reason: str | None


@router.get("/capabilities", response_model=CapabilitiesResponse)
def capabilities(settings: SettingsDep) -> CapabilitiesResponse:
    enabled = []
    if settings.catalog_reviews_enabled:
        enabled.append("catalog_reviews")
    if settings.result_reviews_enabled:
        enabled.append("result_reviews")
    if settings.automatic_analysis_enabled:
        enabled.append("submission_labels")
        if not settings.automatic_analysis_paused:
            enabled.append("analysis_demand_restarts")
    if settings.symbol_imports_enabled:
        enabled.append("symbol_imports")
    if settings.workspace_module_roles_enabled:
        enabled.append("workspace_module_roles")
    return CapabilitiesResponse(
        reader_versions=list(READER_VERSIONS),
        enabled_writes=enabled,
        pause_reason=None if enabled else "qualification_pending",
    )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModuleIdentity(StrictModel):
    code_id: str = Field(min_length=9, max_length=24)
    debug_id: str = Field(min_length=33, max_length=43)
    architecture: Literal["x86_64"]


class ModuleRoleRequest(StrictModel):
    identity: ModuleIdentity
    role: Literal["owned", "dependency"]


class ModuleRoleResponse(StrictModel):
    workspace_id: str
    version: int
    identity: ModuleIdentity
    role: Literal["owned", "dependency"]
    changed: bool
    fanout_attempt_id: str | None


@router.post(
    "/workspaces/{workspace_id}/module-roles",
    response_model=ModuleRoleResponse,
    status_code=201,
    responses={200: {"model": ModuleRoleResponse}},
)
def post_module_role(
    workspace_id: str,
    body: ModuleRoleRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> ModuleRoleResponse:
    if not settings.workspace_module_roles_enabled:
        raise ApiError(
            "QUALIFICATION_PENDING", "Workspace module role writes are disabled", status_code=503
        )
    try:
        declaration = declare_workspace_module_role(
            session,
            workspace_id,
            body.identity.model_dump(),
            body.role,
            now=utcnow(),
        )
    except ValueError as error:
        raise ApiError("VALIDATION", str(error), status_code=422) from error
    attempt_id = None
    if declaration.changed:
        attempt_id = "wra_" + new_ulid()
        create_task_intent(
            session,
            {
                "schema_version": "1.2",
                "task_type": "dispatch_workspace_role",
                "workspace_id": workspace_id,
                "role_version": declaration.version,
                "attempt_id": attempt_id,
                "queue": "ingest",
                "request_id": request.state.request_id,
            },
            settings.schema_root,
        )
        operation_log(
            session,
            action="workspace.module_role.declare",
            target_type="workspace",
            target_id=workspace_id,
            workspace_id=workspace_id,
            request=request,
            details={
                "version": declaration.version,
                "identity": declaration.identity,
                "role": declaration.role,
                "fanout_attempt_id": attempt_id,
            },
        )
    session.commit()
    response.status_code = 201 if declaration.changed else 200
    return ModuleRoleResponse(
        workspace_id=workspace_id,
        version=declaration.version,
        identity=ModuleIdentity.model_validate(declaration.identity),
        role=body.role,
        changed=declaration.changed,
        fanout_attempt_id=attempt_id,
    )


def _stream_run(run: AnalysisRun, store: StoreDep) -> StreamingResponse:
    require_canonical_version(run, READER_VERSIONS)
    # The existing resolver verifies availability and Occurrence ownership.
    assert run.result_object_key is not None
    return StreamingResponse(store.stream(run.result_object_key), media_type="application/json")


@router.get(
    "/occurrences/{occurrence_id}/analysis", response_model=None, responses=CANONICAL_V2_RESPONSE
)
def get_analysis(
    occurrence_id: str, session: SessionDep, store: StoreDep, run_id: str | None = None
) -> StreamingResponse:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    return _stream_run(_resolve_analysis_run(session, occurrence, run_id), store)


@router.get("/runs/{run_id}/analysis", response_model=None, responses=CANONICAL_V2_RESPONSE)
def get_run_analysis(run_id: str, session: SessionDep, store: StoreDep) -> StreamingResponse:
    run = require_row(session, AnalysisRun, run_id, "Analysis Run")
    occurrence = require_row(session, Occurrence, run.occurrence_id, "Occurrence")
    return _stream_run(_resolve_analysis_run(session, occurrence, run_id), store)


@router.get(
    "/occurrences/{occurrence_id}/threads",
    response_model=None,
    responses=canonical_section_v2_response("Thread"),
)
def get_threads(
    occurrence_id: str, session: SessionDep, store: StoreDep, run_id: str | None = None
) -> list[dict[str, Any]]:
    value = _load_canonical(session, store, occurrence_id, run_id, READER_VERSIONS)
    return cast(list[dict[str, Any]], value["threads"])


@router.get(
    "/occurrences/{occurrence_id}/modules",
    response_model=None,
    responses=canonical_section_v2_response("Module"),
)
def get_modules(
    occurrence_id: str, session: SessionDep, store: StoreDep, run_id: str | None = None
) -> list[dict[str, Any]]:
    value = _load_canonical(session, store, occurrence_id, run_id, READER_VERSIONS)
    return cast(list[dict[str, Any]], value["modules"])
