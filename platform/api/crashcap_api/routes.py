from __future__ import annotations

import asyncio
import json
import statistics
from collections import Counter
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .canonical_reader import require_canonical_version
from .config import Settings
from .errors import ApiError
from .ids import new_id
from .in_app import is_system_module
from .models import (
    AnalysisRun,
    AnalysisSummary,
    CrashGroup,
    DumpBlob,
    GroupMembership,
    Occurrence,
    Upload,
    Workspace,
)
from .queueing import TaskDispatcher
from .response_contracts import (
    ERROR_RESPONSES,
    SSE_RESPONSE,
    EventStreamResponse,
)
from .response_models import (
    BatchReprocessResponse,
    ErrorEnvelopeResponse,
    GroupDetailResponse,
    GroupSummaryResponse,
    InAppRulesResponse,
    InAppRulesUpdateResponse,
    OccurrenceListPageResponse,
    OccurrenceResponse,
    OverviewResponse,
    PlatformOverviewResponse,
    PresignedDownloadResponse,
    ReprocessResponse,
    SymbolHealthResponse,
    WorkspaceResponse,
)
from .schemas import (
    GroupPatch,
    InAppRulesUpdate,
    OccurrenceTimePatch,
    SymbolBatchReprocessRequest,
    WorkspaceCreate,
)
from .services.common import latest_run, operation_log, require_row
from .services.occurrence_queries import (
    MAX_CURSOR_LENGTH,
    OccurrenceFilters,
    OccurrenceProjection,
    WorkspaceOccurrenceAggregate,
    aggregate_occurrences,
    list_occurrence_projections,
    normalized_query,
    resolve_time_window,
)
from .services.symbol_projection import (
    current_missing_occurrences,
    missing_symbol_rows,
    symbol_health_rows,
)
from .storage import ObjectStore

router = APIRouter(prefix="/api/v3", responses=ERROR_RESPONSES)


def session_dependency(request: Request) -> Generator[Session, None, None]:
    with request.app.state.database.sessions() as session:
        session.info["symbol_projection_mode"] = request.app.state.settings.symbol_projection_mode
        yield session


def settings_dependency(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def store_dependency(request: Request) -> ObjectStore:
    return cast(ObjectStore, request.app.state.store)


def dispatcher_dependency(request: Request) -> TaskDispatcher:
    return cast(TaskDispatcher, request.app.state.dispatcher)


SessionDep = Annotated[Session, Depends(session_dependency)]
SettingsDep = Annotated[Settings, Depends(settings_dependency)]
StoreDep = Annotated[ObjectStore, Depends(store_dependency)]
DispatcherDep = Annotated[TaskDispatcher, Depends(dispatcher_dependency)]


@router.post("/workspaces", status_code=201, response_model=WorkspaceResponse)
def create_workspace(
    body: WorkspaceCreate, request: Request, session: SessionDep
) -> dict[str, Any]:
    if session.scalar(select(Workspace).where(Workspace.name == body.name)):
        raise ApiError("CONFLICT", "Workspace name already exists", status_code=409)
    workspace = Workspace(
        id=new_id("wsp"),
        name=body.name,
        display_name=body.display_name or body.name,
        retention_days=body.retention_days,
    )
    session.add(workspace)
    # The audit row references the workspace. Flush the parent first because
    # these models intentionally do not carry ORM relationships that SQLAlchemy
    # could otherwise use to infer insert order.
    session.flush()
    operation_log(
        session,
        action="workspace.create",
        target_type="workspace",
        target_id=workspace.id,
        workspace_id=workspace.id,
        request=request,
    )
    session.commit()
    return _workspace_view(workspace)


@router.get("/workspaces", response_model=list[WorkspaceResponse])
def list_workspaces(session: SessionDep) -> list[dict[str, Any]]:
    return [
        _workspace_view(row)
        for row in session.scalars(select(Workspace).order_by(Workspace.created_at, Workspace.id))
    ]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(workspace_id: str, session: SessionDep) -> dict[str, Any]:
    return _workspace_view(require_row(session, Workspace, workspace_id, "Workspace"))


@router.get("/platform/overview", response_model=PlatformOverviewResponse)
def platform_overview(
    session: SessionDep,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> dict[str, Any]:
    window_start, window_end = resolve_time_window(from_, to, default_days=7, max_days=90)
    workspaces = session.scalars(
        select(Workspace).order_by(Workspace.created_at, Workspace.id)
    ).all()
    aggregates = aggregate_occurrences(session, window_start=window_start, window_end=window_end)
    recent = list_occurrence_projections(
        session,
        OccurrenceFilters(from_=window_start, to=window_end),
        limit=10,
    )
    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "workspace_count": len(workspaces),
        "attention": {
            "in_progress": sum(item.in_progress for item in aggregates.values()),
            "latest_attempt_failed": sum(
                item.latest_attempt_failed for item in aggregates.values()
            ),
            "unclassified_crashes": sum(item.unclassified_crashes for item in aggregates.values()),
            "symbol_affected_occurrences": sum(
                item.symbol_affected_occurrences for item in aggregates.values()
            ),
        },
        "workspaces": [
            _platform_workspace_view(workspace, aggregates.get(workspace.id))
            for workspace in workspaces
        ],
        "recent_occurrences": [_occurrence_projection_view(item) for item in recent.items],
    }


@router.get(
    "/workspaces/{workspace_id}/occurrences",
    response_model=OccurrenceListPageResponse,
)
def list_occurrences(
    workspace_id: str,
    session: SessionDep,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    crash_type: Literal["crash", "hang", "unknown", "no_current"] | None = None,
    latest_status: Literal[
        "UPLOADED",
        "VALIDATING",
        "INSPECTED",
        "MATCHING_SYMBOLS",
        "WAITING_FOR_SYMBOLS",
        "SYMBOLS_READY",
        "QUEUED",
        "ANALYZING",
        "NORMALIZING",
        "GROUPING",
        "COMPLETE",
        "PARTIAL",
        "FAILED",
        "REJECTED",
        "CANCELLED",
        "TIMEOUT",
        "OOM",
    ]
    | None = None,
    version: str | None = Query(default=None, max_length=200),
    test_label: str | None = Query(default=None, max_length=200),
    test_batch: str | None = Query(default=None, max_length=200),
    grouping: Literal["exact", "unclassified"] | None = None,
    q: str | None = Query(default=None, max_length=128),
    cursor: str | None = Query(default=None, max_length=MAX_CURSOR_LENGTH),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    window_start: datetime | None = None
    window_end: datetime | None = None
    if from_ is not None or to is not None:
        window_start, window_end = resolve_time_window(from_, to, default_days=366, max_days=366)
    filters = OccurrenceFilters(
        workspace_id=workspace_id,
        from_=window_start,
        to=window_end,
        crash_type=crash_type,
        latest_status=latest_status,
        version=version,
        test_label=test_label,
        test_batch=test_batch,
        grouping=grouping,
        q=normalized_query(q),
    )
    page = list_occurrence_projections(session, filters, limit=limit, cursor=cursor)
    return {
        "items": [_occurrence_projection_view(item) for item in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/occurrences/{occurrence_id}", response_model=OccurrenceResponse)
def get_occurrence(occurrence_id: str, session: SessionDep) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    blob = require_row(session, DumpBlob, occurrence.dump_blob_id, "Dump Blob")
    current = (
        session.get(AnalysisRun, occurrence.current_run_id) if occurrence.current_run_id else None
    )
    if current is not None and current.occurrence_id != occurrence.id:
        current = None
    latest = latest_run(session, occurrence.id)
    membership = session.get(GroupMembership, occurrence.id)
    group = None
    if current is not None and membership is not None and membership.analysis_run_id == current.id:
        candidate_group = session.get(CrashGroup, membership.group_id)
        if candidate_group is not None and candidate_group.workspace_id == occurrence.workspace_id:
            group = candidate_group
    return {
        "id": occurrence.id,
        "workspace_id": occurrence.workspace_id,
        "blob": _blob_view(blob),
        "version": occurrence.version,
        "dump_timestamp": occurrence.dump_timestamp.isoformat()
        if occurrence.dump_timestamp
        else None,
        "reported_at": occurrence.reported_at.isoformat() if occurrence.reported_at else None,
        "occurred_at": occurrence.occurred_at.isoformat(),
        "uploaded_at": occurrence.uploaded_at.isoformat(),
        "time_source": occurrence.time_source,
        "current_analysis": _run_view(current) if current else None,
        "latest_attempt": _run_view(latest) if latest else None,
        "group": _group_top_view(group) if group else None,
    }


@router.patch("/occurrences/{occurrence_id}/time", response_model=OccurrenceResponse)
def patch_occurrence_time(
    occurrence_id: str,
    body: OccurrenceTimePatch,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    previous = occurrence.occurred_at
    occurrence.occurred_at = body.occurred_at
    occurrence.time_source = "manual"
    operation_log(
        session,
        action="occurrence.time.correct",
        target_type="occurrence",
        target_id=occurrence.id,
        workspace_id=occurrence.workspace_id,
        request=request,
        details={"previous": previous.isoformat(), "current": body.occurred_at.isoformat()},
    )
    session.commit()
    return get_occurrence(occurrence_id, session)


def _resolve_analysis_run(
    session: Session, occurrence: Occurrence, run_id: str | None
) -> AnalysisRun:
    selected_id = run_id or occurrence.current_run_id
    if selected_id is None:
        raise ApiError("NOT_FOUND", "Occurrence has no completed analysis", status_code=404)
    run = require_row(session, AnalysisRun, selected_id, "Analysis Run")
    if run.occurrence_id != occurrence.id:
        raise ApiError("NOT_FOUND", "Analysis Run is outside this Occurrence", status_code=404)
    if not run.result_object_key:
        raise ApiError("CONFLICT", "Analysis result is not available", status_code=409)
    return run


@router.post(
    "/occurrences/{occurrence_id}/reprocess", status_code=202, response_model=ReprocessResponse
)
def reprocess(occurrence_id: str, request: Request, session: SessionDep) -> dict[str, Any]:
    from .services.analysis import request_analysis

    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    demand = request_analysis(session, occurrence)
    operation_log(
        session,
        action="occurrence.reprocess",
        target_type="occurrence",
        target_id=occurrence.id,
        workspace_id=occurrence.workspace_id,
        request=request,
    )
    session.commit()
    return {"demand_id": demand.id, "status": demand.state, "created": True}


@router.get("/workspaces/{workspace_id}/overview", response_model=OverviewResponse)
def workspace_overview(
    workspace_id: str,
    session: SessionDep,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    window_end = to or datetime.now(UTC)
    window_start = from_ or window_end - timedelta(days=30)
    rows = session.execute(
        select(Occurrence, AnalysisRun, AnalysisSummary)
        .join(AnalysisRun, AnalysisRun.id == Occurrence.current_run_id)
        .join(AnalysisSummary, AnalysisSummary.analysis_run_id == AnalysisRun.id)
        .where(
            Occurrence.workspace_id == workspace_id,
            Occurrence.occurred_at >= window_start,
            Occurrence.occurred_at <= window_end,
        )
    ).all()
    crash_rows = [row for row in rows if row[2].crash_type == "crash"]
    versions = Counter(occurrence.version for occurrence, _, _ in crash_rows)
    # Group statistics are a projection of the same current-run/window rows as
    # the crash count.  The stored group occurrence_count is intentionally not
    # used here: it is workspace-wide and includes occurrences outside this
    # dashboard window (and could otherwise include a historical membership).
    group_occurrences: dict[str, list[Occurrence]] = {}
    if crash_rows:
        current_memberships = session.execute(
            select(GroupMembership, CrashGroup)
            .join(CrashGroup, CrashGroup.id == GroupMembership.group_id)
            .join(Occurrence, Occurrence.id == GroupMembership.occurrence_id)
            .where(
                GroupMembership.occurrence_id.in_(
                    [occurrence.id for occurrence, _, _ in crash_rows]
                ),
                GroupMembership.analysis_run_id == Occurrence.current_run_id,
            )
        ).all()
        occurrence_by_id = {occurrence.id: occurrence for occurrence, _, _ in crash_rows}
        for membership, _group in current_memberships:
            occurrence = occurrence_by_id.get(membership.occurrence_id)
            if occurrence is not None:
                group_occurrences.setdefault(membership.group_id, []).append(occurrence)
    group_ids = set(group_occurrences)
    group_rows = (
        session.scalars(select(CrashGroup).where(CrashGroup.id.in_(group_ids))).all()
        if group_ids
        else []
    )
    groups = sorted(
        group_rows,
        key=lambda group: (
            -len(group_occurrences[group.id]),
            -max(item.occurred_at for item in group_occurrences[group.id]).timestamp(),
            group.id,
        ),
    )[:10]
    classified_ids = {
        occurrence.id for occurrences in group_occurrences.values() for occurrence in occurrences
    }
    exact_group_count = sum(group.group_type == "exact" for group in group_rows)
    durations = [
        (run.finished_at - run.started_at).total_seconds() * 1000
        for _, run, _ in rows
        if run.started_at and run.finished_at
    ]
    current_runs = session.scalars(
        select(AnalysisRun)
        .join(Occurrence, Occurrence.id == AnalysisRun.occurrence_id)
        .where(
            Occurrence.workspace_id == workspace_id,
            Occurrence.current_run_id == AnalysisRun.id,
            Occurrence.occurred_at >= window_start,
            Occurrence.occurred_at <= window_end,
        )
    ).all()
    failures = sum(run.status in {"FAILED", "TIMEOUT", "OOM"} for run in current_runs)
    completeness = [
        summary.artifact_completeness
        for _, _, summary in rows
        if summary.artifact_completeness is not None
    ]
    rejected = (
        session.scalar(
            select(func.count())
            .select_from(Upload)
            .where(
                Upload.workspace_id == workspace_id,
                Upload.file_kind == "dmp",
                Upload.verification_status == "REJECTED",
                Upload.uploaded_at >= window_start,
                Upload.uploaded_at <= window_end,
            )
        )
        or 0
    )
    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "crash_occurrences": len(crash_rows),
        "exact_groups": int(exact_group_count or 0),
        "unclassified": sum(occ.id not in classified_ids for occ, _, _ in crash_rows),
        "versions": [
            {"version": version, "count": count}
            for version, count in sorted(versions.items(), key=lambda item: str(item[0]))
        ],
        "top_groups": [_group_window_view(group, group_occurrences[group.id]) for group in groups],
        "symbol_completeness": statistics.fmean(completeness) if completeness else 0.0,
        "failure_rate": failures / len(current_runs) if current_runs else 0.0,
        "average_analysis_duration_ms": statistics.fmean(durations) if durations else 0.0,
        "hang_captures": sum(summary.crash_type == "hang" for _, _, summary in rows),
        "unknown_captures": sum(summary.crash_type == "unknown" for _, _, summary in rows),
        "rejected_uploads": int(rejected),
    }


@router.get("/workspaces/{workspace_id}/groups", response_model=list[GroupSummaryResponse])
def list_groups(
    workspace_id: str,
    session: SessionDep,
    status: str | None = None,
    group_type: str | None = None,
    q: str | None = None,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    query = select(CrashGroup).where(CrashGroup.workspace_id == workspace_id)
    if status:
        query = query.where(CrashGroup.status == status)
    if group_type:
        query = query.where(CrashGroup.group_type == group_type)
    if q:
        query = query.where(or_(CrashGroup.title.ilike(f"%{q}%"), CrashGroup.fingerprint == q))
    if cursor:
        query = query.where(CrashGroup.id > cursor)
    return [
        _group_top_view(group)
        for group in session.scalars(query.order_by(CrashGroup.id).limit(200))
    ]


@router.get(
    "/groups/{group_id}", response_model=GroupDetailResponse, response_model_exclude_unset=True
)
def get_group(group_id: str, session: SessionDep) -> dict[str, Any]:
    group = require_row(session, CrashGroup, group_id, "Crash Group")
    return _group_detail_view(session, group)


@router.patch(
    "/groups/{group_id}", response_model=GroupDetailResponse, response_model_exclude_unset=True
)
def patch_group(
    group_id: str,
    body: GroupPatch,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    group = require_row(session, CrashGroup, group_id, "Crash Group")
    changes = body.model_dump(exclude_unset=True)
    if "issue_url" in changes and changes["issue_url"] is not None:
        changes["issue_url"] = str(changes["issue_url"])
    for key, value in changes.items():
        setattr(group, key, value)
    operation_log(
        session,
        action="group.patch",
        target_type="crash_group",
        target_id=group.id,
        workspace_id=group.workspace_id,
        request=request,
        details={"fields": sorted(changes)},
    )
    session.commit()
    return _group_detail_view(session, group)


@router.post("/groups/{group_id}/merge", status_code=501, response_model=ErrorEnvelopeResponse)
@router.post("/groups/{group_id}/split", status_code=501, response_model=ErrorEnvelopeResponse)
def unsupported_group_edit(group_id: str, session: SessionDep) -> None:
    require_row(session, CrashGroup, group_id, "Crash Group")
    raise ApiError("NOT_IMPLEMENTED", "merge/split is deferred to Phase 3", status_code=501)


@router.get("/workspaces/{workspace_id}/symbols/health", response_model=list[SymbolHealthResponse])
def symbol_health(workspace_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return symbol_health_rows(session, workspace_id)


@router.get("/workspaces/{workspace_id}/symbols/missing", response_model=list[SymbolHealthResponse])
def missing_symbols(workspace_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    return missing_symbol_rows(session, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/symbols/reprocess",
    status_code=202,
    response_model=BatchReprocessResponse,
)
def batch_reprocess_symbols(
    workspace_id: str, body: SymbolBatchReprocessRequest, request: Request, session: SessionDep
) -> dict[str, Any]:
    from .services.analysis import request_analysis

    require_row(session, Workspace, workspace_id, "Workspace")
    selected = set(body.occurrence_ids)
    if not selected:
        selected = {
            oid
            for ids in current_missing_occurrences(session, workspace_id).values()
            for oid in ids
        }
    occurrences = session.scalars(
        select(Occurrence).where(
            Occurrence.workspace_id == workspace_id, Occurrence.id.in_(selected)
        )
    ).all()
    if len(occurrences) != len(selected):
        raise ApiError(
            "VALIDATION", "one or more Occurrences are outside this Workspace", status_code=422
        )
    demands = [request_analysis(session, occurrence) for occurrence in occurrences]
    operation_log(
        session,
        action="symbols.reprocess.batch",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        request=request,
        details={"affected_occurrence_count": len(occurrences)},
    )
    session.commit()
    return {
        "workspace_id": workspace_id,
        "affected_occurrence_count": len(occurrences),
        "demand_ids": [d.id for d in demands],
        "occurrence_ids": sorted(selected),
    }


@router.get("/workspaces/{workspace_id}/in-app-rules", response_model=InAppRulesResponse)
def get_in_app_rules(workspace_id: str, session: SessionDep) -> dict[str, Any]:
    workspace = require_row(session, Workspace, workspace_id, "Workspace")
    return {
        "workspace_id": workspace.id,
        "version": workspace.in_app_rule_version,
        **workspace.in_app_rules,
    }


@router.put(
    "/workspaces/{workspace_id}/in-app-rules",
    response_model=InAppRulesUpdateResponse,
    response_model_exclude_unset=True,
)
def update_in_app_rules(
    workspace_id: str, body: InAppRulesUpdate, request: Request, session: SessionDep
) -> dict[str, Any]:
    from .services.analysis import request_analysis
    from .services.symbol_catalog import lock_catalog

    lock_catalog(session)
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise ApiError("NOT_FOUND", "Workspace was not found", status_code=404)
    denied = sorted(name for name in body.include_modules if is_system_module(name))
    if denied:
        raise ApiError(
            "VALIDATION",
            "system-module deny floor cannot be overridden",
            status_code=422,
            details={"denied_modules": denied},
        )
    demands = []
    next_rules = body.model_dump()
    if next_rules != workspace.in_app_rules:
        workspace.in_app_rules = next_rules
        workspace.in_app_rule_version += 1
        for occurrence in session.scalars(
            select(Occurrence)
            .where(Occurrence.workspace_id == workspace_id)
            .order_by(Occurrence.id)
        ):
            blob = session.get(DumpBlob, occurrence.dump_blob_id)
            if (
                blob
                and blob.deleted_at is None
                and (
                    blob.expires_at is None
                    or blob.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
                )
            ):
                demands.append(request_analysis(session, occurrence, cause="role_change"))
        operation_log(
            session,
            action="workspace.in_app_rules.update",
            target_type="workspace",
            target_id=workspace_id,
            workspace_id=workspace_id,
            request=request,
            details={"rule_version": workspace.in_app_rule_version},
        )
    session.commit()
    return {
        "workspace_id": workspace.id,
        "version": workspace.in_app_rule_version,
        **workspace.in_app_rules,
        "demand_ids": [d.id for d in demands],
    }


@router.get(
    "/occurrences/{occurrence_id}/events",
    response_model=None,
    response_class=EventStreamResponse,
    responses=SSE_RESPONSE,
)
async def occurrence_events(occurrence_id: str, request: Request) -> StreamingResponse:
    database = request.app.state.database

    async def stream() -> Any:
        previous_id: str | None = None
        from .analysis_states import TERMINAL_STATES

        terminal = TERMINAL_STATES
        for tick in range(1800):
            if await request.is_disconnected():
                return
            with database.sessions() as event_session:
                occurrence = event_session.get(Occurrence, occurrence_id)
                if occurrence is None:
                    yield 'event: error\ndata: {"code":"NOT_FOUND"}\n\n'
                    return
                run = latest_run(event_session, occurrence.id)
                if run is not None:
                    event_id = f"{run.id}:{run.status}"
                    if event_id != previous_id:
                        payload = {
                            "occurrence_id": occurrence.id,
                            "run": _run_view(run),
                            "current_run_id": occurrence.current_run_id,
                        }
                        yield (
                            f"id: {event_id}\n"
                            "event: analysis-progress\n"
                            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
                        )
                        previous_id = event_id
                    if run.status in terminal:
                        return
            if tick % 15 == 14:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/occurrences/{occurrence_id}/download", response_model=PresignedDownloadResponse)
def download_dump(
    occurrence_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    if not settings.raw_download_enabled:
        raise ApiError("RAW_DOWNLOAD_DISABLED", "raw binary download is disabled", status_code=403)
    blob = require_row(session, DumpBlob, occurrence.dump_blob_id, "Dump Blob")
    if blob.deleted_at:
        raise ApiError("RAW_BLOB_EXPIRED", "raw Dump Blob has expired", status_code=410)
    url = store.presign_get(blob.object_key)
    operation_log(
        session,
        action="raw.download",
        target_type="dump_blob",
        target_id=blob.id,
        workspace_id=occurrence.workspace_id,
        request=request,
    )
    session.commit()
    return {
        "url": url,
        "expires_at": (
            datetime.now(UTC) + timedelta(seconds=settings.presign_get_ttl_seconds)
        ).isoformat(),
    }


def _occurrence_projection_view(row: OccurrenceProjection) -> dict[str, Any]:
    summary = row.summary
    return {
        "id": row.occurrence.id,
        "version": row.occurrence.version,
        "workspace_id": row.occurrence.workspace_id,
        "occurred_at": row.occurrence.occurred_at.isoformat(),
        "uploaded_at": row.occurrence.uploaded_at.isoformat(),
        "time_source": row.occurrence.time_source,
        "current_analysis": _run_view(row.current_analysis)
        if row.current_analysis is not None
        else None,
        "latest_attempt": _run_view(row.latest_attempt) if row.latest_attempt is not None else None,
        "summary": {
            "crash_type": summary.crash_type,
            "exception_code": summary.exception_code,
            "exception_name": summary.exception_name,
            "access_type": summary.access_type,
            "fault_module": summary.fault_module,
            "top_function": summary.top_function,
            "version": row.occurrence.version,
        }
        if summary is not None and row.current_analysis is not None
        else None,
        "group": _group_top_view(row.group) if row.group is not None else None,
    }


def _platform_workspace_view(
    workspace: Workspace, aggregate: WorkspaceOccurrenceAggregate | None
) -> dict[str, Any]:
    return {
        "workspace": _workspace_view(workspace),
        "occurrence_count": aggregate.occurrence_count if aggregate is not None else 0,
        "attention_count": aggregate.attention_count if aggregate is not None else 0,
        "last_occurrence_at": (
            aggregate.last_occurrence_at.isoformat()
            if aggregate is not None and aggregate.last_occurrence_at is not None
            else None
        ),
    }


def _workspace_view(row: Workspace) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name,
        "platform": row.platform,
        "default_architecture": row.default_architecture,
        "retention_days": row.retention_days,
        "symbol_inventory_version": row.symbol_inventory_version,
        "in_app_rule_version": row.in_app_rule_version,
        "in_app_rules": row.in_app_rules,
        "created_at": row.created_at.isoformat(),
    }


def _blob_view(row: DumpBlob) -> dict[str, Any]:
    return {
        "id": row.id,
        "sha256": row.sha256,
        "size": row.size,
        "dump_kind": row.dump_kind,
        "verification_status": row.verification_status.lower(),
        "uploaded_at": row.uploaded_at.isoformat(),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
    }


def _run_view(run: AnalysisRun) -> dict[str, Any]:
    duration = None
    if run.started_at and run.finished_at:
        duration = (run.finished_at - run.started_at).total_seconds() * 1000
    return {
        "id": run.id,
        "status": run.status,
        "quality_score": run.quality_score,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": duration,
        "error_code": run.error_code,
        "error_detail": run.error_detail,
    }


def _group_top_view(group: CrashGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "workspace_id": group.workspace_id,
        "group_type": group.group_type,
        "fingerprint": group.fingerprint,
        "title": group.title,
        "status": group.status,
        "owner": group.owner,
        "issue_url": group.issue_url,
        "occurrence_count": group.occurrence_count,
        "first_seen": group.first_seen.isoformat(),
        "last_seen": group.last_seen.isoformat(),
    }


def _group_window_view(group: CrashGroup, occurrences: list[Occurrence]) -> dict[str, Any]:
    """Render group metadata with a window-scoped current-membership count."""
    view = _group_top_view(group)
    view["occurrence_count"] = len(occurrences)
    view["first_seen"] = min(item.occurred_at for item in occurrences).isoformat()
    view["last_seen"] = max(item.occurred_at for item in occurrences).isoformat()
    return view


def _group_detail_view(session: Session, group: CrashGroup) -> dict[str, Any]:
    memberships = session.scalars(
        select(GroupMembership).where(GroupMembership.group_id == group.id)
    ).all()
    representative = (
        session.get(AnalysisSummary, group.representative_run_id)
        if group.representative_run_id
        else None
    )
    distribution = session.execute(
        select(Occurrence.version, func.count())
        .join(GroupMembership, GroupMembership.occurrence_id == Occurrence.id)
        .where(
            GroupMembership.group_id == group.id,
            GroupMembership.analysis_run_id == Occurrence.current_run_id,
        )
        .group_by(Occurrence.version)
    ).all()
    result = _group_top_view(group)
    result.update(
        {
            "representative_stack": representative.crashing_frames if representative else [],
            "version_distribution": [
                {"version": version, "count": count} for version, count in distribution
            ],
            "occurrence_ids": [row.occurrence_id for row in memberships],
        }
    )
    return result


def _load_canonical(
    session: Session,
    store: ObjectStore,
    occurrence_id: str,
    run_id: str | None,
    versions: tuple[str, ...] = ("2.0",),
) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    run = _resolve_analysis_run(session, occurrence, run_id)
    require_canonical_version(run, versions)
    result_key = run.result_object_key
    if result_key is None:
        raise ApiError("CONFLICT", "Analysis result is not available", status_code=409)
    chunks = []
    total = 0
    for chunk in store.stream(result_key):
        total += len(chunk)
        if total > 64 * 1024 * 1024:
            raise ApiError(
                "CONFLICT",
                "section query exceeds the 64MiB bounded-read limit; stream the Canonical result",
                status_code=409,
            )
        chunks.append(chunk)
    return cast(dict[str, Any], json.loads(b"".join(chunks)))
