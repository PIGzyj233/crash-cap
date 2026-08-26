from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError
from ..ids import new_id, new_ulid
from ..in_app import resolve_in_app
from ..models import AnalysisRun, Artifact, Build, BuildModule, DumpBlob, Occurrence, Workspace
from ..task_handoff import stage_task_message


@dataclass(frozen=True)
class RunCreation:
    run: AnalysisRun
    created: bool
    message: dict[str, Any] | None


def analysis_task_message(session: Session, run: AnalysisRun) -> dict[str, Any]:
    occurrence = session.get(Occurrence, run.occurrence_id)
    blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
    if occurrence is None or blob is None:
        raise ApiError(
            "CONFLICT", "Analysis Run references incomplete platform state", status_code=409
        )
    if blob.deleted_at is not None:
        raise ApiError("RAW_BLOB_EXPIRED", "raw Dump Blob has expired", status_code=410)
    if blob.size > 256 * 1024 * 1024:
        raise ApiError("DUMP_TOO_LARGE", "dump exceeds 256MiB Phase 1 limit", status_code=413)
    return {
        "schema_version": "1.0",
        "task_type": "analyze_occurrence",
        "run_id": run.id,
        "attempt_id": f"att_{new_ulid()}",
        "queue": "dump-small" if blob.size <= 64 * 1024 * 1024 else "dump-large",
    }


def analysis_idempotency_key(
    *,
    occurrence_id: str,
    resolved_build_id: str | None,
    symbol_inventory_version: int,
    core_image_digest: str,
    symbolicator_version: str,
    normalization_version: str,
    grouping_version: str,
    in_app_rule_version: int,
    artifact_selection_version: str,
    force_salt: str | None,
) -> str:
    parts = (
        occurrence_id,
        resolved_build_id or "-",
        str(symbol_inventory_version),
        core_image_digest,
        symbolicator_version,
        normalization_version,
        grouping_version,
        str(in_app_rule_version),
        artifact_selection_version,
        force_salt or "-",
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def create_analysis_run(
    session: Session,
    settings: Settings,
    occurrence: Occurrence,
    *,
    force: bool = False,
    reported_build_id: str | None = None,
    capture_profile: str | None = None,
    request_id: str | None = None,
) -> RunCreation:
    workspace = session.get(Workspace, occurrence.workspace_id)
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    if workspace is None or blob is None:
        raise ApiError(
            "CONFLICT", "Occurrence references incomplete platform state", status_code=409
        )
    if blob.deleted_at is not None:
        raise ApiError("RAW_BLOB_EXPIRED", "raw Dump Blob has expired", status_code=410)

    effective_reported_build = reported_build_id or occurrence.reported_build_id
    if effective_reported_build is not None:
        build = session.get(Build, effective_reported_build)
        if build is None or build.workspace_id != occurrence.workspace_id:
            raise ApiError(
                "VALIDATION",
                "reported Build must belong to the Occurrence Workspace",
                status_code=422,
            )

    resolved_build = effective_reported_build
    resolution_method = "reported" if effective_reported_build else "unresolved"
    force_salt = secrets.token_hex(16) if force else None
    key = analysis_idempotency_key(
        occurrence_id=occurrence.id,
        resolved_build_id=resolved_build,
        symbol_inventory_version=workspace.symbol_inventory_version,
        core_image_digest=settings.core_image_digest,
        symbolicator_version=settings.symbolicator_version,
        normalization_version=settings.normalization_version,
        grouping_version=settings.grouping_version,
        in_app_rule_version=workspace.in_app_rule_version,
        artifact_selection_version=settings.artifact_selection_version,
        force_salt=force_salt,
    )
    existing = session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == key))
    if existing is not None:
        return RunCreation(existing, False, None)

    run_id = new_id("run")
    artifacts = _artifact_snapshot(session, occurrence.workspace_id)
    builds = _build_snapshot(session, occurrence.workspace_id)
    spec: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "occurrence_id": occurrence.id,
        "workspace_id": occurrence.workspace_id,
        "blob": {
            "id": blob.id,
            "sha256": blob.sha256,
            "size": blob.size,
            "object_key": blob.object_key,
        },
        "capture_profile": capture_profile,
        "reported_build_id": effective_reported_build,
        "resolved_build_id": resolved_build,
        "resolution_method": resolution_method,
        "artifacts": artifacts,
        "builds": builds,
        "core_image_digest": settings.core_image_digest,
        "symbolicator_version": settings.symbolicator_version,
        "normalization_version": settings.normalization_version,
        "grouping_version": settings.grouping_version,
        "symbol_inventory_version": workspace.symbol_inventory_version,
        "in_app_rule_version": workspace.in_app_rule_version,
        "in_app_rules": workspace.in_app_rules,
        "artifact_selection_version": settings.artifact_selection_version,
        "force_salt": force_salt,
    }
    run = AnalysisRun(
        id=run_id,
        occurrence_id=occurrence.id,
        run_spec=spec,
        reported_build_id=effective_reported_build,
        resolved_build_id=resolved_build,
        resolution_method=resolution_method,
        resolution_evidence={"candidate_build_ids": [resolved_build] if resolved_build else []},
        core_version="1.0.0",
        core_image_digest=settings.core_image_digest,
        symbolicator_version=settings.symbolicator_version,
        schema_version="1.0",
        grouping_version=settings.grouping_version,
        normalization_version=settings.normalization_version,
        symbol_inventory_version=workspace.symbol_inventory_version,
        idempotency_key=key,
        status="UPLOADED",
        assembly_mode=settings.canonical_assembly_mode,
    )
    try:
        # The preflight SELECT is an optimization, not the concurrency guard.
        # Keep the UNIQUE idempotency key authoritative and contain a losing
        # concurrent INSERT in a savepoint so the outer request transaction
        # remains usable when we return the winner.
        with session.begin_nested():
            session.add(run)
            session.flush()
    except IntegrityError:
        existing = session.scalar(select(AnalysisRun).where(AnalysisRun.idempotency_key == key))
        if existing is None:
            raise
        return RunCreation(existing, False, None)
    message = analysis_task_message(session, run)
    if request_id:
        message["request_id"] = request_id
    return RunCreation(run, True, stage_task_message(session, settings, message))


def _artifact_snapshot(session: Session, workspace_id: str) -> list[dict[str, Any]]:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        return []
    rows = session.execute(
        select(Artifact, Build, BuildModule)
        .join(Build, Build.id == Artifact.build_id)
        .outerjoin(BuildModule, BuildModule.id == Artifact.module_id)
        .where(Build.workspace_id == workspace_id, Artifact.verification_status == "verified")
        .order_by(Artifact.id)
    ).all()
    return [
        {
            "artifact_id": artifact.id,
            "build_id": build.id,
            "module_id": module.id if module else None,
            "kind": artifact.kind,
            "logical_name": artifact.logical_name,
            "sha256": artifact.sha256,
            "size": artifact.size,
            "object_key": artifact.object_key,
            "code_id": artifact.code_id,
            "debug_id": artifact.debug_id,
            "role": module.role if module else None,
            "code_file": module.code_file if module else None,
            "debug_file": module.debug_file if module else None,
            "in_app": resolve_in_app(module.code_file, module.role, workspace.in_app_rules)
            if module
            else False,
            "ingest_metadata": artifact.ingest_metadata,
            "source_bundle_config": build.source_bundle_config
            if artifact.kind == "source_bundle"
            else None,
        }
        for artifact, build, module in rows
    ]


def _build_snapshot(session: Session, workspace_id: str) -> list[dict[str, Any]]:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        return []
    builds = session.scalars(
        select(Build).where(Build.workspace_id == workspace_id).order_by(Build.id)
    ).all()
    result = []
    for build in builds:
        modules = session.scalars(
            select(BuildModule).where(BuildModule.build_id == build.id).order_by(BuildModule.id)
        ).all()
        result.append(
            {
                "build_id": build.id,
                "version": build.version,
                "modules": [
                    {
                        "module_id": module.id,
                        "code_id": module.code_id,
                        "debug_id": module.debug_id,
                        "role": module.role,
                        "code_file": module.code_file,
                        "in_app": resolve_in_app(
                            module.code_file, module.role, workspace.in_app_rules
                        ),
                    }
                    for module in modules
                ],
            }
        )
    return result
