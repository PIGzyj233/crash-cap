from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .contracts import validate_contract
from .errors import ApiError
from .ids import new_id, new_ulid
from .models import (
    AnalysisRun,
    AnalysisSummary,
    Artifact,
    Build,
    BuildModule,
    CrashGroup,
    DumpBlob,
    GroupMembership,
    MissingSymbol,
    Occurrence,
    OperationLog,
    Upload,
    Workspace,
)
from .object_keys import manifest_key
from .queueing import TaskDispatcher
from .schemas import (
    ArtifactUploadInit,
    BuildCreate,
    DumpUploadInit,
    GroupPatch,
    OccurrenceTimePatch,
    ReprocessRequest,
    UploadComplete,
    WorkspaceCreate,
)
from .services.analysis import create_analysis_run
from .services.common import (
    active_missing_occurrences,
    latest_run,
    missing_symbol_key,
    operation_log,
    require_row,
)
from .services.uploads import complete_upload, initialize_upload, upload_completion_view
from .storage import ObjectStore, put_json

router = APIRouter(prefix="/api/v1")


def session_dependency(request: Request) -> Generator[Session, None, None]:
    with request.app.state.database.sessions() as session:
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


@router.post("/workspaces", status_code=201)
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


@router.get("/workspaces")
def list_workspaces(session: SessionDep) -> list[dict[str, Any]]:
    return [
        _workspace_view(row)
        for row in session.scalars(select(Workspace).order_by(Workspace.created_at, Workspace.id))
    ]


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, session: SessionDep) -> dict[str, Any]:
    return _workspace_view(require_row(session, Workspace, workspace_id, "Workspace"))


@router.post("/workspaces/{workspace_id}/builds", status_code=201)
def create_build(
    workspace_id: str,
    body: BuildCreate,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    build = Build(
        id=new_id("bld"),
        workspace_id=workspace_id,
        version=body.version,
        build_number=body.build_number,
        commit_sha=body.commit_sha,
        channel=body.channel,
        architecture=body.architecture,
        toolchain=body.toolchain,
    )
    session.add(build)
    operation_log(
        session,
        action="build.create",
        target_type="build",
        target_id=build.id,
        workspace_id=workspace_id,
        request=request,
        details={"version": body.version},
    )
    session.commit()
    return _build_view(session, build)


@router.get("/workspaces/{workspace_id}/builds")
def list_builds(
    workspace_id: str,
    session: SessionDep,
    version: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    query = select(Build).where(Build.workspace_id == workspace_id)
    if version:
        query = query.where(Build.version == version)
    if cursor:
        query = query.where(Build.id > cursor)
    builds = session.scalars(query.order_by(Build.id).limit(limit)).all()
    return [_build_view(session, build) for build in builds]


@router.get("/builds/{build_id}")
def get_build(build_id: str, session: SessionDep) -> dict[str, Any]:
    return _build_view(session, require_row(session, Build, build_id, "Build"))


@router.put("/builds/{build_id}/manifest")
def put_manifest(
    build_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    validate_contract(
        body, settings.schema_root / "build-manifest-v1.schema.json", "Build Manifest"
    )
    if body["architecture"] != "x86_64":
        raise ApiError("VALIDATION", "Phase 1 accepts only x86_64 Build Manifests", status_code=422)
    if body["version"] != build.version:
        raise ApiError(
            "VALIDATION",
            "Manifest version must equal the Build display version",
            status_code=422,
        )
    incoming_modules = body["modules"]
    code_names = [item["code_file"].casefold() for item in incoming_modules]
    debug_names = [item["debug_file"].casefold() for item in incoming_modules]
    if len(code_names) != len(set(code_names)) or len(debug_names) != len(set(debug_names)):
        raise ApiError(
            "VALIDATION", "Manifest module filenames must be unique within a Build", status_code=422
        )
    existing = session.scalars(
        select(BuildModule).where(BuildModule.build_id == build.id).order_by(BuildModule.id)
    ).all()
    if existing:
        old_shape = {(row.code_file, row.debug_file, row.role) for row in existing}
        new_shape = {
            (str(item["code_file"]), str(item["debug_file"]), str(item["role"]))
            for item in incoming_modules
        }
        if old_shape != new_shape:
            raise ApiError(
                "CONFLICT",
                "Manifest shape is immutable after initial registration",
                status_code=409,
            )
    else:
        for item in incoming_modules:
            # Producer IDs remain untrusted hints and are intentionally discarded.
            session.add(
                BuildModule(
                    id=new_id("mod"),
                    build_id=build.id,
                    code_file=item["code_file"],
                    debug_file=item["debug_file"],
                    role=item["role"],
                    code_id=None,
                    debug_id=None,
                )
            )
    key = manifest_key(build.workspace_id, build.id)
    put_json(store, key, body)
    build.manifest_object_key = key
    operation_log(
        session,
        action="manifest.put",
        target_type="build",
        target_id=build.id,
        workspace_id=build.workspace_id,
        request=request,
        details={"module_count": len(incoming_modules)},
    )
    session.commit()
    return _build_view(session, build)


@router.post("/builds/{build_id}/artifacts/uploads:init", status_code=201)
def init_artifact_upload(
    build_id: str,
    body: ArtifactUploadInit,
    request: Request,
    session: SessionDep,
    store: StoreDep,
) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    _upload, response = initialize_upload(
        session,
        store,
        workspace_id=build.workspace_id,
        build_id=build.id,
        file_kind=body.file_kind,
        filename=body.filename,
        size=body.size,
        sha256_hint=body.sha256,
        capture_profile=None,
        reported_build_id=None,
        reported_at=None,
        request=request,
    )
    return response


@router.post("/workspaces/{workspace_id}/dumps/uploads:init", status_code=201)
def init_dump_upload(
    workspace_id: str,
    body: DumpUploadInit,
    request: Request,
    session: SessionDep,
    store: StoreDep,
) -> dict[str, Any]:
    _upload, response = initialize_upload(
        session,
        store,
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
    return response


@router.post("/uploads/{upload_id}/complete")
def finish_upload(
    upload_id: str,
    request: Request,
    session: SessionDep,
    store: StoreDep,
    dispatcher: DispatcherDep,
    body: UploadComplete = Body(default_factory=UploadComplete),
) -> dict[str, Any]:
    return complete_upload(
        session,
        store,
        dispatcher,
        upload_id=upload_id,
        multipart_upload_id=body.multipart_upload_id,
        parts=[part.model_dump() for part in body.parts],
        request=request,
    )


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, session: SessionDep) -> dict[str, Any]:
    upload = require_row(session, Upload, upload_id, "Upload")
    return upload_completion_view(session, upload)


@router.get("/builds/{build_id}/symbols")
def list_artifacts(build_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Build, build_id, "Build")
    return [
        _artifact_view(row)
        for row in session.scalars(
            select(Artifact).where(Artifact.build_id == build_id).order_by(Artifact.created_at)
        )
    ]


@router.post("/workspaces/{workspace_id}/symbols/reindex", status_code=202)
def reindex_symbols(
    workspace_id: str,
    request: Request,
    session: SessionDep,
    dispatcher: DispatcherDep,
    build_id: str | None = Body(default=None, embed=True),
) -> dict[str, Any]:
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    if workspace is None:
        raise ApiError("NOT_FOUND", "Workspace was not found", status_code=404)
    if build_id:
        build = require_row(session, Build, build_id, "Build")
        if build.workspace_id != workspace_id:
            raise ApiError("VALIDATION", "Build is outside this Workspace", status_code=422)
    idempotency_key = hashlib.sha256(
        f"{workspace_id}\n{build_id or '-'}\n{workspace.symbol_inventory_version}".encode()
    ).hexdigest()
    requests = session.scalars(
        select(OperationLog)
        .where(
            OperationLog.workspace_id == workspace_id,
            OperationLog.action == "symbols.reindex.request",
        )
        .order_by(OperationLog.id.desc())
        .limit(100)
    )
    for previous in requests:
        details = previous.details or {}
        if details.get("idempotency_key") == idempotency_key:
            return {
                "status": "QUEUED",
                "attempt_id": details["attempt_id"],
                "created": False,
            }
    message = {
        "schema_version": "1.0",
        "task_type": "reindex_symbols",
        "workspace_id": workspace_id,
        "build_id": build_id,
        "attempt_id": f"att_{new_ulid()}",
        "queue": "ingest",
        "request_id": request.state.request_id,
    }
    if build_id is None:
        message.pop("build_id")
    operation_log(
        session,
        action="symbols.reindex.request",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        request=request,
        details={
            "build_id": build_id,
            "symbol_inventory_version": workspace.symbol_inventory_version,
            "idempotency_key": idempotency_key,
            "attempt_id": message["attempt_id"],
        },
    )
    dispatcher.enqueue(message)
    session.commit()
    return {"status": "QUEUED", "attempt_id": message["attempt_id"], "created": True}


@router.get("/occurrences/{occurrence_id}")
def get_occurrence(occurrence_id: str, session: SessionDep) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    blob = require_row(session, DumpBlob, occurrence.dump_blob_id, "Dump Blob")
    current = (
        session.get(AnalysisRun, occurrence.current_run_id) if occurrence.current_run_id else None
    )
    latest = latest_run(session, occurrence.id)
    membership = session.get(GroupMembership, occurrence.id)
    group = session.get(CrashGroup, membership.group_id) if membership else None
    return {
        "id": occurrence.id,
        "workspace_id": occurrence.workspace_id,
        "blob": _blob_view(blob),
        "reported_build_id": occurrence.reported_build_id,
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


@router.patch("/occurrences/{occurrence_id}/time")
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


@router.get("/occurrences/{occurrence_id}/analysis")
def get_analysis(
    occurrence_id: str,
    session: SessionDep,
    store: StoreDep,
    run_id: str | None = None,
) -> StreamingResponse:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    run = _resolve_analysis_run(session, occurrence, run_id)
    result_key = run.result_object_key
    if result_key is None:
        raise ApiError("CONFLICT", "Analysis result is not available", status_code=409)
    return StreamingResponse(store.stream(result_key), media_type="application/json")


@router.get("/occurrences/{occurrence_id}/threads")
def get_threads(
    occurrence_id: str,
    session: SessionDep,
    store: StoreDep,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    canonical = _load_canonical(session, store, occurrence_id, run_id)
    return cast(list[dict[str, Any]], canonical["threads"])


@router.get("/occurrences/{occurrence_id}/modules")
def get_modules(
    occurrence_id: str,
    session: SessionDep,
    store: StoreDep,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    canonical = _load_canonical(session, store, occurrence_id, run_id)
    return cast(list[dict[str, Any]], canonical["modules"])


@router.post("/occurrences/{occurrence_id}/reprocess", status_code=202)
def reprocess(
    occurrence_id: str,
    body: ReprocessRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    previous = latest_run(session, occurrence.id)
    capture_profile = previous.run_spec.get("capture_profile") if previous else None
    creation = create_analysis_run(
        session,
        settings,
        occurrence,
        force=body.force,
        reported_build_id=body.reported_build_id,
        capture_profile=capture_profile,
    )
    operation_log(
        session,
        action="occurrence.reprocess",
        target_type="analysis_run",
        target_id=creation.run.id,
        workspace_id=occurrence.workspace_id,
        request=request,
        result="created" if creation.created else "idempotent_replay",
        details={"force": body.force, "reported_build_id": body.reported_build_id},
    )
    session.commit()
    if creation.message:
        creation.message["request_id"] = request.state.request_id
        dispatcher.enqueue(creation.message)
    response = _run_view(creation.run)
    response["created"] = creation.created
    return response


@router.get("/workspaces/{workspace_id}/overview")
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
        select(Occurrence, AnalysisRun, AnalysisSummary, Build)
        .join(AnalysisRun, AnalysisRun.id == Occurrence.current_run_id)
        .join(AnalysisSummary, AnalysisSummary.analysis_run_id == AnalysisRun.id)
        .outerjoin(Build, Build.id == AnalysisSummary.resolved_build_id)
        .where(
            Occurrence.workspace_id == workspace_id,
            Occurrence.occurred_at >= window_start,
            Occurrence.occurred_at <= window_end,
        )
    ).all()
    crash_rows = [row for row in rows if row[2].crash_type == "crash"]
    versions = Counter((build.version if build else None) for _, _, _, build in crash_rows)
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
                    [occurrence.id for occurrence, _, _, _ in crash_rows]
                ),
                GroupMembership.analysis_run_id == Occurrence.current_run_id,
            )
        ).all()
        occurrence_by_id = {occurrence.id: occurrence for occurrence, _, _, _ in crash_rows}
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
        for _, run, _, _ in rows
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
        for _, _, summary, _ in rows
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
        "unclassified": sum(occ.id not in classified_ids for occ, _, _, _ in crash_rows),
        "versions": [
            {"version": version, "count": count}
            for version, count in sorted(versions.items(), key=lambda item: str(item[0]))
        ],
        "top_groups": [_group_window_view(group, group_occurrences[group.id]) for group in groups],
        "symbol_completeness": statistics.fmean(completeness) if completeness else 0.0,
        "failure_rate": failures / len(current_runs) if current_runs else 0.0,
        "average_analysis_duration_ms": statistics.fmean(durations) if durations else 0.0,
        "hang_captures": sum(summary.crash_type == "hang" for _, _, summary, _ in rows),
        "unknown_captures": sum(summary.crash_type == "unknown" for _, _, summary, _ in rows),
        "rejected_uploads": int(rejected),
    }


@router.get("/workspaces/{workspace_id}/groups")
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


@router.get("/groups/{group_id}")
def get_group(group_id: str, session: SessionDep) -> dict[str, Any]:
    group = require_row(session, CrashGroup, group_id, "Crash Group")
    return _group_detail_view(session, group)


@router.patch("/groups/{group_id}")
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


@router.post("/groups/{group_id}/merge")
@router.post("/groups/{group_id}/split")
def unsupported_group_edit(group_id: str, session: SessionDep) -> None:
    require_row(session, CrashGroup, group_id, "Crash Group")
    raise ApiError("NOT_IMPLEMENTED", "merge/split is deferred to Phase 3", status_code=501)


@router.get("/workspaces/{workspace_id}/symbols/health")
def symbol_health(workspace_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    modules = session.execute(
        select(BuildModule, Build)
        .join(Build, Build.id == BuildModule.build_id)
        .where(Build.workspace_id == workspace_id)
        .order_by(BuildModule.code_file)
    ).all()
    rows = []
    active = active_missing_occurrences(session, workspace_id)
    for module, _build in modules:
        artifacts = session.scalars(select(Artifact).where(Artifact.module_id == module.id)).all()
        statuses = {artifact.verification_status for artifact in artifacts}
        if "pdb_mismatch" in statuses or "pe_mismatch" in statuses:
            status = "mismatch"
        elif {"pe", "pdb"}.issubset(
            {artifact.kind for artifact in artifacts if artifact.verification_status == "verified"}
        ):
            status = "matched"
        else:
            status = "missing"
        missing = session.scalar(
            select(MissingSymbol).where(
                MissingSymbol.workspace_id == workspace_id,
                MissingSymbol.code_id.is_not_distinct_from(module.code_id),
                MissingSymbol.debug_id.is_not_distinct_from(module.debug_id),
            )
        )
        rows.append(
            {
                "code_file": module.code_file,
                "debug_file": module.debug_file,
                "code_id": module.code_id,
                "debug_id": module.debug_id,
                "status": status,
                "affected_occurrence_count": missing.affected_occurrence_count if missing else 0,
                "first_seen": (missing.first_seen if missing else module.created_at).isoformat(),
                "last_seen": (missing.last_seen if missing else module.created_at).isoformat(),
                "occurrence_ids": sorted(
                    active.get(
                        missing_symbol_key(
                            {
                                "code_file": module.code_file,
                                "code_id": module.code_id,
                                "debug_file": module.debug_file,
                                "debug_id": module.debug_id,
                            }
                        ),
                        set(),
                    )
                ),
            }
        )
    return rows


@router.get("/workspaces/{workspace_id}/symbols/missing")
def missing_symbols(workspace_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    active = active_missing_occurrences(session, workspace_id)
    return [
        {
            "code_file": row.code_file,
            "debug_file": row.debug_file,
            "code_id": row.code_id,
            "debug_id": row.debug_id,
            "status": _missing_symbol_status(session, workspace_id, row),
            "affected_occurrence_count": row.affected_occurrence_count,
            "first_seen": row.first_seen.isoformat(),
            "last_seen": row.last_seen.isoformat(),
            "occurrence_ids": sorted(
                active.get(
                    missing_symbol_key(
                        {
                            "code_file": row.code_file,
                            "code_id": row.code_id,
                            "debug_file": row.debug_file,
                            "debug_id": row.debug_id,
                        }
                    ),
                    set(),
                )
            ),
        }
        for row in session.scalars(
            select(MissingSymbol)
            .where(MissingSymbol.workspace_id == workspace_id, MissingSymbol.status == "open")
            .order_by(MissingSymbol.last_seen.desc())
        )
    ]


def _missing_symbol_status(session: Session, workspace_id: str, row: MissingSymbol) -> str:
    query = (
        select(Artifact.id)
        .join(Build, Build.id == Artifact.build_id)
        .where(
            Build.workspace_id == workspace_id,
            Artifact.verification_status.in_(["pdb_mismatch", "pe_mismatch"]),
            Artifact.debug_id.is_not_distinct_from(row.debug_id),
            Artifact.code_id.is_not_distinct_from(row.code_id),
        )
    )
    if row.debug_id is None and row.debug_file:
        query = query.where(func.lower(Artifact.logical_name) == row.debug_file.lower())
    return "mismatch" if session.scalar(query.limit(1)) is not None else "missing"


@router.get("/occurrences/{occurrence_id}/download")
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


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(
    artifact_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> dict[str, Any]:
    artifact = require_row(session, Artifact, artifact_id, "Artifact")
    build = require_row(session, Build, artifact.build_id, "Build")
    if not settings.raw_download_enabled:
        raise ApiError("RAW_DOWNLOAD_DISABLED", "raw binary download is disabled", status_code=403)
    url = store.presign_get(artifact.object_key)
    operation_log(
        session,
        action="raw.download",
        target_type="artifact",
        target_id=artifact.id,
        workspace_id=build.workspace_id,
        request=request,
    )
    session.commit()
    return {
        "url": url,
        "expires_at": (
            datetime.now(UTC) + timedelta(seconds=settings.presign_get_ttl_seconds)
        ).isoformat(),
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
        "created_at": row.created_at.isoformat(),
    }


def _build_view(session: Session, build: Build) -> dict[str, Any]:
    modules = session.scalars(
        select(BuildModule).where(BuildModule.build_id == build.id).order_by(BuildModule.id)
    ).all()
    artifacts = session.scalars(
        select(Artifact).where(Artifact.build_id == build.id).order_by(Artifact.created_at)
    ).all()
    groups = session.scalars(
        select(CrashGroup).where(
            or_(CrashGroup.first_build_id == build.id, CrashGroup.last_build_id == build.id)
        )
    ).all()
    artifact_counts = Counter(item.module_id for item in artifacts)
    active_missing = active_missing_occurrences(session, build.workspace_id)
    return {
        "id": build.id,
        "workspace_id": build.workspace_id,
        "version": build.version,
        "build_number": build.build_number,
        "commit_sha": build.commit_sha,
        "channel": build.channel,
        "architecture": build.architecture,
        "toolchain": build.toolchain,
        "manifest_object_key": build.manifest_object_key,
        "created_at": build.created_at.isoformat(),
        "modules": [
            {
                "id": module.id,
                "code_file": module.code_file,
                "debug_file": module.debug_file,
                "role": module.role,
                "code_id": module.code_id,
                "debug_id": module.debug_id,
                "in_app": module.role in {"entrypoint", "owned"},
                "artifact_count": artifact_counts[module.id],
                "missing_occurrence_count": len(
                    active_missing.get(
                        missing_symbol_key(
                            {
                                "code_file": module.code_file,
                                "code_id": module.code_id,
                                "debug_file": module.debug_file,
                                "debug_id": module.debug_id,
                            }
                        ),
                        set(),
                    )
                ),
            }
            for module in modules
        ],
        "artifacts": [_artifact_view(item) for item in artifacts],
        "groups": [_group_top_view(group) for group in groups],
    }


def _artifact_view(row: Artifact) -> dict[str, Any]:
    return {
        "id": row.id,
        "module_id": row.module_id,
        "kind": row.kind,
        "logical_name": row.logical_name,
        "sha256": row.sha256,
        "size": row.size,
        "code_id": row.code_id,
        "debug_id": row.debug_id,
        "verification_status": row.verification_status,
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
        "resolution_method": run.resolution_method,
        "resolved_build_id": run.resolved_build_id,
        "quality_score": run.quality_score,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": duration,
        "error_code": run.error_code,
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
        "first_build_id": group.first_build_id,
        "last_build_id": group.last_build_id,
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
        select(Build.id, Build.version, func.count())
        .join(AnalysisSummary, AnalysisSummary.resolved_build_id == Build.id)
        .join(GroupMembership, GroupMembership.analysis_run_id == AnalysisSummary.analysis_run_id)
        .where(GroupMembership.group_id == group.id)
        .group_by(Build.id, Build.version)
    ).all()
    result = _group_top_view(group)
    result.update(
        {
            "representative_stack": representative.crashing_frames if representative else [],
            "build_distribution": [
                {"build_id": build_id, "version": version, "count": count}
                for build_id, version, count in distribution
            ],
            "occurrence_ids": [row.occurrence_id for row in memberships],
        }
    )
    return result


def _load_canonical(
    session: Session, store: ObjectStore, occurrence_id: str, run_id: str | None
) -> dict[str, Any]:
    occurrence = require_row(session, Occurrence, occurrence_id, "Occurrence")
    run = _resolve_analysis_run(session, occurrence, run_id)
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
