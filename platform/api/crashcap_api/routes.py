from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .build_publications import (
    FINGERPRINT_VERSION,
    prepare_publication,
    publication_status_view,
)
from .config import Settings
from .contracts import validate_contract
from .errors import ApiError
from .ids import new_id, new_ulid
from .in_app import is_system_module, resolve_in_app
from .metrics import (
    BUILD_FINGERPRINT_CONFLICTS,
    BUILD_PUBLICATION_BYTES,
    BUILD_PUBLICATIONS,
)
from .models import (
    AnalysisRun,
    AnalysisSummary,
    Artifact,
    Build,
    BuildArtifactExpectation,
    BuildModule,
    BuildPublication,
    CrashGroup,
    DumpBlob,
    GroupMembership,
    Occurrence,
    OperationLog,
    Upload,
    Workspace,
)
from .object_keys import manifest_key
from .producers import PRODUCER_MATRIX, producer_matrix_view
from .queueing import TaskDispatcher
from .response_contracts import (
    CANONICAL_MODULES_RESPONSE,
    CANONICAL_RESPONSE,
    CANONICAL_THREADS_RESPONSE,
    ERROR_RESPONSES,
    SSE_RESPONSE,
    EventStreamResponse,
)
from .response_models import (
    ArtifactDeliveryInitResponse,
    ArtifactProducerResponse,
    ArtifactResponse,
    BatchReprocessResponse,
    BuildCiStatusResponse,
    BuildPublicationStatusResponse,
    BuildResponse,
    ErrorEnvelopeResponse,
    GroupDetailResponse,
    GroupSummaryResponse,
    InAppRulesResponse,
    InAppRulesUpdateResponse,
    OccurrenceResponse,
    OverviewResponse,
    PresignedDownloadResponse,
    ProducerResponse,
    QueuedTaskResponse,
    ReprocessResponse,
    RetryDispatchResponse,
    SymbolHealthResponse,
    UploadCompletionResponse,
    UploadInitResponse,
    WorkspaceResponse,
)
from .schemas import (
    ArtifactDeliveryInit,
    ArtifactUploadInit,
    BuildCreate,
    BuildPublicationCreate,
    DumpUploadInit,
    GroupPatch,
    InAppRulesUpdate,
    OccurrenceTimePatch,
    ReprocessRequest,
    SymbolBatchReprocessRequest,
    UploadComplete,
    WorkspaceCreate,
)
from .services.analysis import analysis_task_message, create_analysis_run
from .services.artifact_blobs import (
    bind_verified_blobs,
    delivery_label,
    initialize_artifact_delivery,
)
from .services.common import latest_run, operation_log, require_row
from .services.symbol_projection import (
    current_missing_occurrences,
    missing_symbol_rows,
    module_missing_counts,
    occurrence_ids_for_symbol_filters,
    symbol_health_rows,
)
from .services.uploads import complete_upload, initialize_upload, upload_completion_view
from .storage import ObjectStore, put_json
from .task_handoff import (
    publish_after_commit,
    reindex_logical_key,
    request_task_redelivery,
    stage_task_message,
)

router = APIRouter(prefix="/api/v1", responses=ERROR_RESPONSES)


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


def _build_identity_conflicts(build: Build, body: BuildCreate) -> list[str]:
    immutable = {
        "version": body.version,
        "build_number": body.build_number,
        "commit_sha": body.commit_sha,
        "channel": body.channel,
        "architecture": body.architecture,
        "toolchain": body.toolchain,
    }
    return [name for name, value in immutable.items() if getattr(build, name) != value]


def _assert_build_identity_compatible(build: Build, body: BuildCreate) -> None:
    conflicts = _build_identity_conflicts(build, body)
    if conflicts:
        raise ApiError(
            "CONFLICT",
            "producer_build_id is already bound to different immutable Build metadata",
            status_code=409,
            details={"conflicting_fields": conflicts},
        )


def _require_build_publications_enabled(settings: Settings) -> None:
    if not settings.build_publications_enabled:
        raise ApiError(
            "BUILD_PUBLICATIONS_DISABLED",
            "Build Publications are not enabled in this environment",
            status_code=404,
        )


def _assert_publication_idempotency(
    publication: BuildPublication,
    build: Build,
    body: BuildPublicationCreate,
    content_fingerprint: str,
) -> None:
    conflicts: list[str] = []
    if build.content_fingerprint != content_fingerprint:
        conflicts.append("content_fingerprint")
    if publication.git_revision != body.git.revision:
        conflicts.append("git.revision")
    if publication.git_worktree_state != body.git.worktree_state:
        conflicts.append("git.worktree_state")
    if conflicts:
        BUILD_FINGERPRINT_CONFLICTS.labels(body.origin).inc()
        raise ApiError(
            "PUBLICATION_IDEMPOTENCY_CONFLICT",
            "client_publication_id is already bound to a different Publication payload",
            status_code=409,
            details={"conflicting_fields": conflicts},
        )


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


@router.post(
    "/workspaces/{workspace_id}/build-publications",
    status_code=201,
    response_model=BuildPublicationStatusResponse,
)
def create_build_publication(
    workspace_id: str,
    body: BuildPublicationCreate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    _require_build_publications_enabled(settings)
    require_row(session, Workspace, workspace_id, "Workspace")
    prepared = prepare_publication(body, settings)

    existing_publication = session.scalar(
        select(BuildPublication).where(
            BuildPublication.workspace_id == workspace_id,
            BuildPublication.origin == body.origin,
            BuildPublication.client_publication_id == body.client_publication_id,
        )
    )
    if existing_publication is not None:
        existing_build = require_row(session, Build, existing_publication.build_id, "Build")
        _assert_publication_idempotency(
            existing_publication, existing_build, body, prepared.content_fingerprint
        )
        existing_publication.last_seen_at = datetime.now(UTC)
        messages = bind_verified_blobs(session, store, settings, existing_build)
        session.commit()
        for message in messages:
            publish_after_commit(session, settings, dispatcher, message)
        BUILD_PUBLICATIONS.labels(body.origin, "idempotent_reuse").inc()
        return publication_status_view(session, existing_build, existing_publication)

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        lock_keys = sorted(
            {
                f"publication:{workspace_id}:{body.origin}:{body.client_publication_id}",
                f"content:{workspace_id}:{FINGERPRINT_VERSION}:{prepared.content_fingerprint}",
            }
        )
        for lock_key in lock_keys:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": lock_key},
            )
        # The first lookup happened before the transaction-scoped locks. A
        # concurrent winner may now exist, so repeat the idempotency decision.
        existing_publication = session.scalar(
            select(BuildPublication).where(
                BuildPublication.workspace_id == workspace_id,
                BuildPublication.origin == body.origin,
                BuildPublication.client_publication_id == body.client_publication_id,
            )
        )
        if existing_publication is not None:
            concurrent_build = require_row(session, Build, existing_publication.build_id, "Build")
            _assert_publication_idempotency(
                existing_publication, concurrent_build, body, prepared.content_fingerprint
            )
            existing_publication.last_seen_at = datetime.now(UTC)
            messages = bind_verified_blobs(session, store, settings, concurrent_build)
            session.commit()
            for message in messages:
                publish_after_commit(session, settings, dispatcher, message)
            BUILD_PUBLICATIONS.labels(body.origin, "concurrent_reuse").inc()
            return publication_status_view(session, concurrent_build, existing_publication)
    build = session.scalar(
        select(Build).where(
            Build.workspace_id == workspace_id,
            Build.fingerprint_version == FINGERPRINT_VERSION,
            Build.content_fingerprint == prepared.content_fingerprint,
        )
    )
    build_created = build is None
    if build is None:
        manifest = prepared.manifest
        build = Build(
            id=new_id("bld"),
            workspace_id=workspace_id,
            version=str(manifest["version"]),
            build_number=manifest.get("build_number"),
            commit_sha=manifest.get("commit"),
            channel=manifest.get("channel"),
            architecture="x86_64",
            toolchain=manifest.get("toolchain"),
            producer="msvc",
            producer_build_id=None,
            manifest_schema_version=prepared.schema_version,
            source_bundle_config=None,
            identity_mode="content_v1",
            fingerprint_version=FINGERPRINT_VERSION,
            content_fingerprint=prepared.content_fingerprint,
        )
        session.add(build)
        session.flush()
        modules: dict[str, BuildModule] = {}
        for item in prepared.modules:
            module = BuildModule(
                id=new_id("mod"),
                build_id=build.id,
                code_file=item["code_file"],
                debug_file=item["debug_file"],
                role=item["role"],
                code_id=None,
                debug_id=None,
            )
            session.add(module)
            modules[module.code_file.casefold()] = module
        session.flush()
        for item in prepared.artifacts:
            module = modules[str(item["module_code_file"]).casefold()]
            session.add(
                BuildArtifactExpectation(
                    build_id=build.id,
                    module_id=module.id,
                    kind=item["kind"],
                    logical_name=item["logical_name"],
                    normalized_name=str(item["logical_name"]).casefold(),
                    size=item["size"],
                    sha256=item["sha256"],
                )
            )
        key = manifest_key(workspace_id, build.id)
        put_json(store, key, prepared.manifest)
        build.manifest_object_key = key

    publication = BuildPublication(
        id=new_id("pub"),
        workspace_id=workspace_id,
        build_id=build.id,
        origin=body.origin,
        client_publication_id=body.client_publication_id,
        client_version=body.client_version,
        git_revision=body.git.revision,
        git_worktree_state=body.git.worktree_state,
    )
    session.add(publication)
    session.flush()
    messages = bind_verified_blobs(session, store, settings, build)
    operation_log(
        session,
        action="build_publication.register",
        target_type="build_publication",
        target_id=publication.id,
        workspace_id=workspace_id,
        request=request,
        result="build_created" if build_created else "build_reused",
        details={
            "build_id": build.id,
            "origin": body.origin,
            "fingerprint_version": FINGERPRINT_VERSION,
        },
    )
    session.commit()
    for message in messages:
        publish_after_commit(session, settings, dispatcher, message)
    BUILD_PUBLICATIONS.labels(
        body.origin, "build_created" if build_created else "build_reused"
    ).inc()
    status = publication_status_view(session, build, publication)
    missing_names = {item["logical_name"].casefold() for item in status["missing_artifacts"]}
    for item in prepared.artifacts:
        outcome = (
            "upload_required"
            if str(item["logical_name"]).casefold() in missing_names
            else "deduplicated"
        )
        BUILD_PUBLICATION_BYTES.labels(body.origin, outcome).inc(int(item["size"]))
    return status


@router.get(
    "/build-publications/{publication_id}",
    response_model=BuildPublicationStatusResponse,
)
def get_build_publication(
    publication_id: str,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_build_publications_enabled(settings)
    publication = require_row(session, BuildPublication, publication_id, "Build Publication")
    build = require_row(session, Build, publication.build_id, "Build")
    return publication_status_view(session, build, publication)


@router.get(
    "/builds/{build_id}/publication-status",
    response_model=BuildPublicationStatusResponse,
)
def get_build_publication_status(
    build_id: str,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_build_publications_enabled(settings)
    build = require_row(session, Build, build_id, "Build")
    return publication_status_view(session, build)


@router.post(
    "/workspaces/{workspace_id}/builds",
    status_code=201,
    response_model=BuildResponse,
    response_model_exclude_unset=True,
)
def create_build(
    workspace_id: str,
    body: BuildCreate,
    request: Request,
    session: SessionDep,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    if body.producer and body.producer_build_id:
        existing = session.scalar(
            select(Build).where(
                Build.workspace_id == workspace_id,
                Build.producer == body.producer,
                Build.producer_build_id == body.producer_build_id,
            )
        )
        if existing is not None:
            _assert_build_identity_compatible(existing, body)
            return _build_view(session, existing)
    build = Build(
        id=new_id("bld"),
        workspace_id=workspace_id,
        version=body.version,
        build_number=body.build_number,
        commit_sha=body.commit_sha,
        channel=body.channel,
        architecture=body.architecture,
        toolchain=body.toolchain,
        producer=body.producer,
        producer_build_id=body.producer_build_id,
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
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if not body.producer or not body.producer_build_id:
            raise
        winner = session.scalar(
            select(Build).where(
                Build.workspace_id == workspace_id,
                Build.producer == body.producer,
                Build.producer_build_id == body.producer_build_id,
            )
        )
        if winner is None:
            raise
        _assert_build_identity_compatible(winner, body)
        return _build_view(session, winner)
    return _build_view(session, build)


@router.get(
    "/workspaces/{workspace_id}/builds",
    response_model=list[BuildResponse],
    response_model_exclude_unset=True,
)
def list_builds(
    workspace_id: str,
    session: SessionDep,
    version: str | None = None,
    producer: str | None = None,
    producer_build_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    require_row(session, Workspace, workspace_id, "Workspace")
    query = select(Build).where(Build.workspace_id == workspace_id)
    if version:
        query = query.where(Build.version == version)
    if producer:
        query = query.where(Build.producer == producer)
    if producer_build_id:
        query = query.where(Build.producer_build_id == producer_build_id)
    if cursor:
        query = query.where(Build.id > cursor)
    builds = session.scalars(query.order_by(Build.id).limit(limit)).all()
    return [_build_view(session, build) for build in builds]


@router.get("/builds/{build_id}", response_model=BuildResponse, response_model_exclude_unset=True)
def get_build(build_id: str, session: SessionDep) -> dict[str, Any]:
    return _build_view(session, require_row(session, Build, build_id, "Build"))


@router.put(
    "/builds/{build_id}/manifest",
    response_model=BuildResponse,
    response_model_exclude_unset=True,
)
def put_manifest(
    build_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    if build.identity_mode == "content_v1":
        if build.sealed_at is not None:
            raise ApiError(
                "BUILD_SEALED",
                "A sealed content Build cannot change its Manifest",
                status_code=409,
            )
        raise ApiError(
            "CONTENT_BUILD_MANAGED_BY_PUBLICATION",
            "A content Build Manifest is registered atomically with its Publication",
            status_code=409,
        )
    raw_schema_version = body.get("schema_version")
    schema_version = raw_schema_version if isinstance(raw_schema_version, str) else ""
    schema_name = {
        "1.0": "build-manifest-v1.schema.json",
        "2.0": "build-manifest-v2.schema.json",
    }.get(schema_version)
    if schema_name is None:
        raise ApiError("VALIDATION", "Manifest schema_version must be 1.0 or 2.0", status_code=422)
    validate_contract(body, settings.schema_root / schema_name, "Build Manifest")
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
    if build.manifest_schema_version and (
        build.manifest_schema_version != schema_version
        or build.source_bundle_config != body.get("source_bundle")
    ):
        raise ApiError(
            "CONFLICT",
            "Manifest contract version and source-bundle descriptor are immutable "
            "after registration",
            status_code=409,
        )
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
    build.manifest_schema_version = str(schema_version)
    build.source_bundle_config = body.get("source_bundle")
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


@router.post(
    "/builds/{build_id}/artifacts/uploads:init",
    status_code=201,
    response_model=UploadInitResponse,
    response_model_exclude_unset=True,
)
def init_artifact_upload(
    build_id: str,
    body: ArtifactUploadInit,
    request: Request,
    session: SessionDep,
    store: StoreDep,
) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    if build.identity_mode == "content_v1":
        if build.sealed_at is not None:
            raise ApiError(
                "BUILD_SEALED",
                "A sealed content Build cannot accept more Artifacts",
                status_code=409,
            )
        if body.file_kind == "source_bundle":
            raise ApiError(
                "UNEXPECTED_ARTIFACT",
                "Publication v1 accepts only declared PE/PDB Artifacts",
                status_code=422,
            )
        if body.sha256 is None:
            raise ApiError(
                "EXPECTED_ARTIFACT_HASH_REQUIRED",
                "Content Build uploads require the declared SHA-256",
                status_code=422,
            )
        expected = session.scalar(
            select(BuildArtifactExpectation).where(
                BuildArtifactExpectation.build_id == build.id,
                BuildArtifactExpectation.kind == body.file_kind,
                BuildArtifactExpectation.normalized_name == body.filename.casefold(),
            )
        )
        if expected is None:
            raise ApiError(
                "UNEXPECTED_ARTIFACT",
                "Artifact is absent from the Build expectation inventory",
                status_code=422,
                details={"kind": body.file_kind, "logical_name": body.filename},
            )
        conflicts: list[str] = []
        if expected.size != body.size:
            conflicts.append("size")
        if expected.sha256.lower() != body.sha256.lower():
            conflicts.append("sha256")
        if conflicts:
            raise ApiError(
                "ARTIFACT_CONTENT_MISMATCH",
                "Artifact upload declaration differs from the expected content",
                status_code=422,
                details={"conflicting_fields": conflicts},
            )
    if body.file_kind == "source_bundle":
        source_config = build.source_bundle_config or {}
        if build.manifest_schema_version != "2.0" or not source_config:
            raise ApiError(
                "VALIDATION",
                "source bundle upload requires an accepted Build Manifest v2 descriptor",
                status_code=422,
            )
        if body.filename.casefold() != str(source_config.get("archive", "")).casefold():
            raise ApiError(
                "VALIDATION",
                "source bundle filename must match manifest source_bundle.archive",
                status_code=422,
            )
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


@router.post(
    "/builds/{build_id}/artifacts/deliveries:init",
    status_code=201,
    response_model=ArtifactDeliveryInitResponse,
    response_model_exclude_unset=True,
)
def init_artifact_delivery(
    build_id: str,
    body: ArtifactDeliveryInit,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    return initialize_artifact_delivery(
        session,
        store,
        dispatcher,
        settings,
        build=build,
        file_kind=body.file_kind,
        filename=body.filename,
        size=body.size,
        sha256=body.sha256,
        request=request,
    )


@router.post(
    "/workspaces/{workspace_id}/dumps/uploads:init",
    status_code=201,
    response_model=UploadInitResponse,
    response_model_exclude_unset=True,
)
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


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=UploadCompletionResponse,
    response_model_exclude_unset=True,
)
def finish_upload(
    upload_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
    dispatcher: DispatcherDep,
    body: UploadComplete = Body(default_factory=UploadComplete),
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


@router.get(
    "/uploads/{upload_id}",
    response_model=UploadCompletionResponse,
    response_model_exclude_unset=True,
)
def get_upload(upload_id: str, session: SessionDep) -> dict[str, Any]:
    upload = require_row(session, Upload, upload_id, "Upload")
    return upload_completion_view(session, upload)


@router.get("/ci/producers", response_model=list[ProducerResponse])
def ci_producer_matrix() -> list[dict[str, Any]]:
    return producer_matrix_view()


@router.get("/artifact-producers", response_model=list[ArtifactProducerResponse])
def artifact_producer_matrix(settings: SettingsDep) -> list[dict[str, Any]]:
    return [
        {
            **row,
            "publication_contracts": ["1.0"],
            "minimum_client_version": "1.0.0",
            "build_publications_enabled": settings.build_publications_enabled,
            "artifact_delivery_contracts": (
                ["artifact-delivery-v1"]
                if settings.artifact_blob_dedup_mode == "active"
                else []
            ),
        }
        for row in producer_matrix_view()
    ]


@router.get("/builds/{build_id}/ci-status", response_model=BuildCiStatusResponse)
def build_ci_status(build_id: str, session: SessionDep) -> dict[str, Any]:
    build = require_row(session, Build, build_id, "Build")
    modules = session.scalars(
        select(BuildModule).where(BuildModule.build_id == build.id).order_by(BuildModule.id)
    ).all()
    artifacts = session.scalars(
        select(Artifact).where(Artifact.build_id == build.id).order_by(Artifact.created_at)
    ).all()
    missing: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for module in modules:
        module_artifacts = [artifact for artifact in artifacts if artifact.module_id == module.id]
        for kind, logical_name in (("pe", module.code_file), ("pdb", module.debug_file)):
            candidates = [artifact for artifact in module_artifacts if artifact.kind == kind]
            has_verified = any(
                artifact.verification_status == "verified" for artifact in candidates
            )
            if not has_verified:
                missing.append({"module_id": module.id, "kind": kind, "logical_name": logical_name})
                rejected.extend(
                    {
                        "artifact_id": artifact.id,
                        "logical_name": artifact.logical_name,
                        "status": artifact.verification_status,
                    }
                    for artifact in candidates
                    if artifact.verification_status not in {"pending", "verified"}
                )
    source_status = "not_declared"
    if build.source_bundle_config:
        source_artifacts = [artifact for artifact in artifacts if artifact.kind == "source_bundle"]
        source_status = (
            "verified"
            if any(artifact.verification_status == "verified" for artifact in source_artifacts)
            else "pending"
            if any(artifact.verification_status == "pending" for artifact in source_artifacts)
            else "missing_or_rejected"
        )
    producer = PRODUCER_MATRIX.get(build.producer or "", {"status": "unregistered"})
    return {
        "build_id": build.id,
        "manifest_schema_version": build.manifest_schema_version,
        "producer": build.producer,
        "producer_status": producer["status"],
        "manifest_present": bool(build.manifest_object_key),
        "module_count": len(modules),
        "missing_artifacts": missing,
        "rejected_artifacts": rejected,
        "source_bundle_status": source_status,
        "ready": bool(
            build.manifest_object_key
            and modules
            and not missing
            and not rejected
            and source_status in {"not_declared", "verified"}
        ),
    }


@router.get(
    "/builds/{build_id}/symbols",
    response_model=list[ArtifactResponse],
    response_model_exclude_unset=True,
)
def list_artifacts(build_id: str, session: SessionDep) -> list[dict[str, Any]]:
    require_row(session, Build, build_id, "Build")
    return [
        _artifact_view(row)
        for row in session.scalars(
            select(Artifact).where(Artifact.build_id == build_id).order_by(Artifact.created_at)
        )
    ]


@router.post(
    "/workspaces/{workspace_id}/symbols/reindex",
    status_code=202,
    response_model=QueuedTaskResponse,
)
def reindex_symbols(
    workspace_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
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
    message = stage_task_message(
        session,
        settings,
        message,
        logical_key_override=reindex_logical_key(
            workspace_id,
            build_id,
            workspace.symbol_inventory_version,
        ),
    )
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
    session.commit()
    publish_after_commit(session, settings, dispatcher, message)
    return {"status": "QUEUED", "attempt_id": message["attempt_id"], "created": True}


@router.get("/occurrences/{occurrence_id}", response_model=OccurrenceResponse)
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


@router.get(
    "/occurrences/{occurrence_id}/analysis",
    response_model=None,
    responses=CANONICAL_RESPONSE,
)
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


@router.get(
    "/occurrences/{occurrence_id}/threads",
    response_model=None,
    responses=CANONICAL_THREADS_RESPONSE,
)
def get_threads(
    occurrence_id: str,
    session: SessionDep,
    store: StoreDep,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    canonical = _load_canonical(session, store, occurrence_id, run_id)
    return cast(list[dict[str, Any]], canonical["threads"])


@router.get(
    "/occurrences/{occurrence_id}/modules",
    response_model=None,
    responses=CANONICAL_MODULES_RESPONSE,
)
def get_modules(
    occurrence_id: str,
    session: SessionDep,
    store: StoreDep,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    canonical = _load_canonical(session, store, occurrence_id, run_id)
    return cast(list[dict[str, Any]], canonical["modules"])


@router.post(
    "/occurrences/{occurrence_id}/reprocess",
    status_code=202,
    response_model=ReprocessResponse,
)
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
        request_id=request.state.request_id,
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
    publish_after_commit(session, settings, dispatcher, creation.message)
    response = _run_view(creation.run)
    response["created"] = creation.created
    return response


@router.post(
    "/analysis-runs/{run_id}/retry-dispatch",
    status_code=202,
    response_model=RetryDispatchResponse,
)
def retry_analysis_dispatch(
    run_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    run = require_row(session, AnalysisRun, run_id, "Analysis Run")
    if run.status != "UPLOADED":
        raise ApiError(
            "CONFLICT",
            "only an UPLOADED Analysis Run can be safely re-dispatched",
            status_code=409,
        )
    occurrence = require_row(session, Occurrence, run.occurrence_id, "Occurrence")
    message = analysis_task_message(session, run)
    message["request_id"] = request.state.request_id
    dispatch_state = "legacy"
    should_publish = True
    if settings.task_handoff_mode != "legacy":
        decision = request_task_redelivery(session, message, settings.schema_root)
        message = decision.message
        dispatch_state = decision.dispatch_state
        should_publish = decision.dispatch_state in {"pending", "reopened"}
    operation_log(
        session,
        action="analysis.dispatch.retry",
        target_type="analysis_run",
        target_id=run.id,
        workspace_id=occurrence.workspace_id,
        request=request,
        details={
            "attempt_id": message["attempt_id"],
            "queue": message["queue"],
            "dispatch_state": dispatch_state,
        },
    )
    session.commit()
    if should_publish:
        publish_after_commit(session, settings, dispatcher, message)
    return {
        "run_id": run.id,
        "status": run.status,
        "attempt_id": message["attempt_id"],
        "dispatch_state": dispatch_state,
    }


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
    workspace_id: str,
    body: SymbolBatchReprocessRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
    require_row(session, Workspace, workspace_id, "Workspace")
    active = current_missing_occurrences(session, workspace_id)
    selected: set[str] = set(body.occurrence_ids)
    modules_query = (
        select(BuildModule, Build)
        .join(Build, Build.id == BuildModule.build_id)
        .where(Build.workspace_id == workspace_id)
    )
    if body.build_id:
        build = require_row(session, Build, body.build_id, "Build")
        if build.workspace_id != workspace_id:
            raise ApiError("VALIDATION", "Build is outside this Workspace", status_code=422)
        modules_query = modules_query.where(Build.id == body.build_id)
    if body.module_id:
        module = require_row(session, BuildModule, body.module_id, "Build Module")
        module_build = require_row(session, Build, module.build_id, "Build")
        if module_build.workspace_id != workspace_id:
            raise ApiError("VALIDATION", "Module is outside this Workspace", status_code=422)
        modules_query = modules_query.where(BuildModule.id == body.module_id)
    if body.build_id or body.module_id:
        selected.update(
            occurrence_ids_for_symbol_filters(
                session,
                workspace_id,
                [module for module, _build in session.execute(modules_query)],
            )
        )
    if not body.build_id and not body.module_id and not body.occurrence_ids:
        selected.update(occurrence_id for values in active.values() for occurrence_id in values)

    occurrences = session.scalars(
        select(Occurrence).where(
            Occurrence.workspace_id == workspace_id,
            Occurrence.id.in_(selected or {"__none__"}),
        )
    ).all()
    if len(occurrences) != len(selected):
        raise ApiError(
            "VALIDATION", "one or more Occurrences are outside this Workspace", status_code=422
        )
    messages: list[dict[str, Any]] = []
    run_ids: list[str] = []
    for occurrence in occurrences:
        previous = latest_run(session, occurrence.id)
        creation = create_analysis_run(
            session,
            settings,
            occurrence,
            capture_profile=previous.run_spec.get("capture_profile") if previous else None,
            request_id=request.state.request_id,
        )
        if creation.created:
            run_ids.append(creation.run.id)
            if creation.message:
                messages.append(creation.message)
    operation_log(
        session,
        action="symbols.reprocess.batch",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        request=request,
        details={
            "build_id": body.build_id,
            "module_id": body.module_id,
            "affected_occurrence_count": len(occurrences),
            "created_run_count": len(run_ids),
        },
    )
    session.commit()
    for message in messages:
        publish_after_commit(session, settings, dispatcher, message)
    return {
        "workspace_id": workspace_id,
        "affected_occurrence_count": len(occurrences),
        "created_run_count": len(run_ids),
        "occurrence_ids": sorted(selected),
        "run_ids": run_ids,
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
    workspace_id: str,
    body: InAppRulesUpdate,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    dispatcher: DispatcherDep,
) -> dict[str, Any]:
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
    next_rules = body.model_dump()
    if next_rules == workspace.in_app_rules:
        return {
            "workspace_id": workspace.id,
            "version": workspace.in_app_rule_version,
            **workspace.in_app_rules,
            "created_run_count": 0,
        }
    workspace.in_app_rules = next_rules
    workspace.in_app_rule_version += 1
    messages: list[dict[str, Any]] = []
    run_ids: list[str] = []
    for occurrence in session.scalars(
        select(Occurrence).where(Occurrence.workspace_id == workspace_id).order_by(Occurrence.id)
    ):
        previous = latest_run(session, occurrence.id)
        creation = create_analysis_run(
            session,
            settings,
            occurrence,
            capture_profile=previous.run_spec.get("capture_profile") if previous else None,
            request_id=request.state.request_id,
        )
        if creation.created:
            run_ids.append(creation.run.id)
            if creation.message:
                messages.append(creation.message)
    operation_log(
        session,
        action="workspace.in_app_rules.update",
        target_type="workspace",
        target_id=workspace_id,
        workspace_id=workspace_id,
        request=request,
        details={
            "rule_version": workspace.in_app_rule_version,
            "created_run_count": len(run_ids),
        },
    )
    session.commit()
    for message in messages:
        publish_after_commit(session, settings, dispatcher, message)
    return {
        "workspace_id": workspace.id,
        "version": workspace.in_app_rule_version,
        **workspace.in_app_rules,
        "created_run_count": len(run_ids),
        "run_ids": run_ids,
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


@router.get("/artifacts/{artifact_id}/download", response_model=PresignedDownloadResponse)
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
        "in_app_rule_version": row.in_app_rule_version,
        "in_app_rules": row.in_app_rules,
        "created_at": row.created_at.isoformat(),
    }


def _build_view(session: Session, build: Build) -> dict[str, Any]:
    workspace = require_row(session, Workspace, build.workspace_id, "Workspace")
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
    missing_counts = module_missing_counts(session, build.workspace_id, modules)
    return {
        "id": build.id,
        "workspace_id": build.workspace_id,
        "version": build.version,
        "build_number": build.build_number,
        "commit_sha": build.commit_sha,
        "channel": build.channel,
        "architecture": build.architecture,
        "toolchain": build.toolchain,
        "producer": build.producer,
        "producer_build_id": build.producer_build_id,
        "manifest_object_key": build.manifest_object_key,
        "manifest_schema_version": build.manifest_schema_version,
        "source_bundle_config": build.source_bundle_config,
        "identity_mode": build.identity_mode,
        "fingerprint_version": build.fingerprint_version,
        "content_fingerprint": build.content_fingerprint,
        "sealed_at": build.sealed_at.isoformat() if build.sealed_at else None,
        "created_at": build.created_at.isoformat(),
        "modules": [
            {
                "id": module.id,
                "code_file": module.code_file,
                "debug_file": module.debug_file,
                "role": module.role,
                "code_id": module.code_id,
                "debug_id": module.debug_id,
                "in_app": resolve_in_app(module.code_file, module.role, workspace.in_app_rules),
                "artifact_count": artifact_counts[module.id],
                "missing_occurrence_count": missing_counts[module.id],
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
        "artifact_blob_id": row.artifact_blob_id,
        "delivery": delivery_label(
            row.materialization_source, blob_backed=row.artifact_blob_id is not None
        ),
        "ingest_metadata": row.ingest_metadata,
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
