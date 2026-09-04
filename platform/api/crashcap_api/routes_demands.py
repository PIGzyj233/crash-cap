"""Demand status and explicit, idempotent restart of exhausted analysis cycles."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .errors import ApiError
from .frozen_inputs import digest
from .ids import new_ulid
from .models import AnalysisDemand, AnalysisDemandRestart, utcnow
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep, SettingsDep
from .services.analysis_demands import DemandError, restart_exhausted_demand
from .services.common import operation_log
from .services.demand_queries import demand_status
from .services.symbol_catalog import lock_catalog

router = APIRouter(prefix="/api/v2", responses=ERROR_RESPONSES)


class DemandStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demand_id: str
    occurrence_id: str
    state: Literal[
        "preparing",
        "coalescing",
        "queued",
        "running",
        "updated",
        "retained",
        "needs_review",
        "retry_wait",
        "retry_exhausted",
        "cannot_recompute",
        "paused",
    ]
    generation: int = Field(ge=0, le=9007199254740991)
    retry_attempt: int = Field(ge=0, le=9007199254740991)
    change_sequence: int = Field(default=0, ge=0, le=9007199254740991)
    run_id: str | None
    reason: str | None
    not_before: datetime | None
    current_run_id: str | None = None
    withdrawn_basis_pair_ids: list[str] | None = None


@router.get(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand",
    response_model=DemandStatusResponse | None,
)
def get_analysis_demand(
    workspace_id: str, occurrence_id: str, session: SessionDep, settings: SettingsDep
) -> DemandStatusResponse | None:
    result = demand_status(session, workspace_id=workspace_id, occurrence_id=occurrence_id)
    response = DemandStatusResponse.model_validate(result) if result is not None else None
    if (
        response is not None
        and settings.automatic_analysis_paused
        and response.state in {"preparing", "coalescing", "retry_wait"}
    ):
        return response.model_copy(update={"state": "paused", "not_before": None})
    return response


class DemandRestartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    idempotency_key: str = Field(min_length=1, max_length=200, pattern=r"\S")
    expected_generation: int = Field(ge=0, le=9007199254740991)
    expected_sequence: int = Field(ge=0, le=9007199254740991)
    rationale: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class DemandRestartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restart_id: str
    demand_id: str
    occurrence_id: str
    generation: int
    change_sequence: int
    state: Literal["preparing"]


@router.post(
    "/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand/restarts",
    response_model=DemandRestartResponse,
    status_code=202,
)
def restart_analysis_demand(
    workspace_id: str,
    occurrence_id: str,
    body: DemandRestartRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> DemandRestartResponse:
    # The shared catalog fence serializes requests with event fanout and planning.
    lock_catalog(session)
    demand = session.scalar(
        select(AnalysisDemand)
        .where(
            AnalysisDemand.workspace_id == workspace_id,
            AnalysisDemand.occurrence_id == occurrence_id,
        )
        .with_for_update()
    )
    if demand is None:
        raise ApiError("DEMAND_NOT_FOUND", "Analysis demand not found", status_code=404)
    value = body.model_dump(mode="json")
    request_hash = digest(value)
    existing = session.scalar(
        select(AnalysisDemandRestart).where(
            AnalysisDemandRestart.demand_id == demand.id,
            AnalysisDemandRestart.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_sha256 != request_hash or existing.request != value:
            raise ApiError(
                "IDEMPOTENCY_CONFLICT",
                "Restart key was used for a different request",
                status_code=409,
            )
        return DemandRestartResponse.model_validate(existing.response)
    try:
        demand = restart_exhausted_demand(
            session,
            settings,
            demand.id,
            workspace_id=workspace_id,
            expected_generation=body.expected_generation,
            expected_sequence=body.expected_sequence,
            now=utcnow(),
        )
    except DemandError as error:
        code = str(error)
        raise ApiError(
            code,
            "Analysis demand cannot be restarted",
            status_code=410 if code == "DUMP_UNAVAILABLE" else 409,
        ) from error
    response = DemandRestartResponse(
        restart_id="drs_" + new_ulid(),
        demand_id=demand.id,
        occurrence_id=occurrence_id,
        generation=demand.generation,
        change_sequence=demand.change_sequence,
        state="preparing",
    )
    session.add(
        AnalysisDemandRestart(
            id=response.restart_id,
            demand_id=demand.id,
            idempotency_key=body.idempotency_key,
            request_sha256=request_hash,
            request=value,
            response=response.model_dump(mode="json"),
        )
    )
    operation_log(
        session,
        action="analysis_demand.restart",
        target_type="analysis_demand_restart",
        target_id=response.restart_id,
        workspace_id=workspace_id,
        request=request,
        details={
            "demand_id": demand.id,
            "request_sha256": request_hash,
            "generation": demand.generation,
            "change_sequence": demand.change_sequence,
        },
    )
    session.commit()
    return response
