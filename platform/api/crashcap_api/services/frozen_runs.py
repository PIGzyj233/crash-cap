"""Atomically adopt already prepared frozen evidence as a durable 1.1 Run.

All object reads and expensive preparation happen before this layer. The adoption
transaction only rechecks bounded database metadata, validates detached bytes, and
commits the Demand target, immutable Run, and TaskIntent together.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..frozen_inputs import digest, frozen_run_key, verify_frozen_run
from ..ids import new_id, new_ulid
from ..models import (
    AnalysisDemand,
    AnalysisRun,
    DumpBlob,
    DumpInspection,
    Occurrence,
    TaskIntent,
    Workspace,
)
from ..task_handoff import create_task_intent
from .analysis_demands import freeze_target, require, retry_is_due
from .symbol_catalog import lock_catalog
from .workspace_builds import WorkspaceBuildSnapshot, snapshot_workspace_builds
from .workspace_policies import WorkspacePolicySnapshot, snapshot_workspace_policies


@dataclass(frozen=True)
class FrozenRunPreparation:
    expected_sequence: int
    cause: str
    manifest: dict[str, Any]
    manifest_bytes: bytes
    manifest_object_key: str
    inspect_bytes: bytes
    build_snapshot: WorkspaceBuildSnapshot
    policy_snapshot: WorkspacePolicySnapshot
    policy_snapshots: dict[str, Any]
    source_bundle_locations: list[dict[str, Any]]
    retained_manifest_bytes: bytes | None = None


@dataclass(frozen=True)
class FrozenRunCreation:
    run: AnalysisRun
    intent: TaskIntent
    created: bool


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


def _same_build_snapshot(left: WorkspaceBuildSnapshot, right: WorkspaceBuildSnapshot) -> bool:
    return (
        left.workspace_id,
        left.reported_build_id,
        left.metadata,
    ) == (
        right.workspace_id,
        right.reported_build_id,
        right.metadata,
    )


def _same_policy_snapshot(left: WorkspacePolicySnapshot, right: WorkspacePolicySnapshot) -> bool:
    return (
        left.workspace_id,
        left.in_app_rule_version,
        left.module_role_version,
        left.rules,
        left.declarations,
        left.bundles,
    ) == (
        right.workspace_id,
        right.in_app_rule_version,
        right.module_role_version,
        right.rules,
        right.declarations,
        right.bundles,
    )


def _context(
    settings: Settings,
    workspace_id: str,
    reported_build_id: str | None,
    capture_profile: str | None,
    policies: dict[str, Any],
) -> dict[str, Any]:
    require(settings.frozen_symbolicator_image_digest is not None, "FROZEN_ENGINE_PINS_MISSING")
    return {
        "schema_version": "analysis-context-v2",
        "workspace_id": workspace_id,
        "reported_build_id": reported_build_id,
        **{f"{key}_sha256": digest(value) for key, value in policies.items()},
        "capture_profile": capture_profile,
        "core_image_digest": settings.core_image_digest,
        "symbolicator_image_digest": settings.frozen_symbolicator_image_digest,
        "symbolicator_version": settings.symbolicator_version,
        "source_bundle_policy_version": "source-bundle-v1.0",
        "normalization_version": settings.normalization_version,
        "grouping_version": "group-v1.1",
        "inspector_version": "inspect-v0.1",
        "canonical_version": "1.1",
        "selection_version": "pair-selection-v1",
    }


def adopt_frozen_run(
    session: Session,
    settings: Settings,
    demand_id: str,
    prepared: FrozenRunPreparation,
    *,
    now: datetime,
    request_id: str | None = None,
) -> FrozenRunCreation:
    """Commit one frozen target, Run and strict outbox receipt as a unit."""
    require(settings.frozen_analysis_enabled, "FROZEN_ANALYSIS_DISABLED")
    require(settings.task_handoff_mode == "outbox", "FROZEN_ANALYSIS_REQUIRES_OUTBOX")
    require(settings.task_receipt_mode == "strict", "FROZEN_ANALYSIS_REQUIRES_STRICT_RECEIPTS")
    lock_catalog(session)
    demand = session.scalar(
        select(AnalysisDemand)
        .where(AnalysisDemand.id == demand_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(demand is not None and demand.inspection_id is not None, "INSPECTION_REQUIRED")
    assert demand is not None and demand.inspection_id is not None
    if demand.state == "retry_wait":
        require(retry_is_due(demand, now=now), "RETRY_NOT_DUE")
    require(demand.change_sequence == prepared.expected_sequence, "STALE_DEMAND_PLAN")
    inspection = session.get(DumpInspection, demand.inspection_id, populate_existing=True)
    occurrence = session.get(Occurrence, demand.occurrence_id, populate_existing=True)
    require(inspection is not None and occurrence is not None, "FROZEN_ANALYSIS_TARGET_MISSING")
    assert inspection is not None and occurrence is not None
    blob = session.get(DumpBlob, occurrence.dump_blob_id, populate_existing=True)
    workspace = session.get(Workspace, demand.workspace_id, populate_existing=True)
    require(blob is not None and workspace is not None, "FROZEN_ANALYSIS_TARGET_MISSING")
    assert blob is not None and workspace is not None

    captured = [row["identity"] for row in inspection.modules]
    current_builds = snapshot_workspace_builds(
        session,
        demand.workspace_id,
        captured,
        reported_build_id=occurrence.reported_build_id,
        limits=prepared.build_snapshot.limits,
    )
    require(_same_build_snapshot(current_builds, prepared.build_snapshot), "STALE_WORKSPACE_BUILDS")
    current_policy = snapshot_workspace_policies(session, current_builds)
    require(
        _same_policy_snapshot(current_policy, prepared.policy_snapshot),
        "STALE_WORKSPACE_POLICY",
    )

    context = _context(
        settings,
        demand.workspace_id,
        occurrence.reported_build_id,
        blob.capture_profile,
        prepared.policy_snapshots,
    )
    context_sha256 = digest(context)
    require(
        hashlib.sha256(prepared.manifest_bytes).hexdigest() == digest(prepared.manifest),
        "MANIFEST_STORED_BYTES_MISMATCH",
    )
    target = freeze_target(
        session,
        demand.id,
        expected_sequence=prepared.expected_sequence,
        manifest=prepared.manifest,
        manifest_object_key=prepared.manifest_object_key,
        context_sha256=context_sha256,
        cause=prepared.cause,
        schema_root=settings.schema_root / "drafts/qa-symbol-import",
        now=now,
    )
    manifest_bytes = prepared.manifest_bytes
    if hashlib.sha256(manifest_bytes).hexdigest() != target.manifest_sha256:
        manifest_bytes = prepared.retained_manifest_bytes or b""
    require(
        hashlib.sha256(manifest_bytes).hexdigest() == target.manifest_sha256,
        "MANIFEST_STORED_BYTES_MISMATCH",
    )
    require(
        hashlib.sha256(prepared.inspect_bytes).hexdigest() == inspection.object_sha256,
        "INSPECT_STORED_BYTES_MISMATCH",
    )
    run_id = new_id("run")
    run_spec: dict[str, Any] = {
        "schema_version": "analysis-run-v2",
        "run_id": run_id,
        "occurrence_id": occurrence.id,
        "demand_id": demand.id,
        "demand_generation": target.generation,
        "retry_attempt": demand.retry_attempt,
        "reason": target.cause,
        "dump": {"sha256": blob.sha256.lower(), "object_key": blob.object_key, "size": blob.size},
        "result_facts": {
            "dump": {
                "blob_id": blob.id,
                "sha256": blob.sha256.lower(),
                "kind": blob.dump_kind,
                "size": blob.size,
                "capture_profile": blob.capture_profile,
                "dump_timestamp": json.loads(prepared.inspect_bytes)["dump"].get("timestamp"),
                "reported_at": _iso(occurrence.reported_at),
                "uploaded_at": _iso(occurrence.uploaded_at),
                "occurred_at": _iso(occurrence.occurred_at),
                "time_source": occurrence.time_source,
            }
        },
        "policy_snapshots": prepared.policy_snapshots,
        "source_bundle_locations": prepared.source_bundle_locations,
        "inspect": {"object_key": inspection.object_key, "sha256": inspection.object_sha256},
        "resolution_manifest": {
            "object_key": target.manifest_object_key,
            "sha256": target.manifest_sha256,
        },
        "resolution_evidence_fingerprint": target.resolution_fingerprint,
        "context": context,
        "context_sha256": context_sha256,
        "idempotency_key": "0" * 64,
    }
    run_spec["idempotency_key"] = frozen_run_key(run_spec)
    verify_frozen_run(
        run_spec,
        manifest_bytes=manifest_bytes,
        inspect_bytes=prepared.inspect_bytes,
        observed_dump_sha256=blob.sha256.lower(),
        observed_dump_size=blob.size,
        schema_root=settings.schema_root / "drafts/qa-symbol-import",
    )
    existing = session.scalar(
        select(AnalysisRun).where(AnalysisRun.idempotency_key == run_spec["idempotency_key"])
    )
    if existing is not None:
        intent = session.scalar(
            select(TaskIntent).where(
                TaskIntent.task_type == "analyze_frozen_run",
                TaskIntent.logical_key == existing.id,
            )
        )
        require(intent is not None, "FROZEN_RUN_INTENT_MISSING")
        assert intent is not None
        return FrozenRunCreation(existing, intent, False)

    run = AnalysisRun(
        id=run_id,
        occurrence_id=occurrence.id,
        demand_id=demand.id,
        demand_generation=target.generation,
        retry_attempt=demand.retry_attempt,
        run_spec=run_spec,
        reported_build_id=occurrence.reported_build_id,
        resolved_build_id=None,
        resolution_method="unresolved",
        resolution_evidence={"candidate_build_ids": []},
        core_version="frozen-v1",
        core_image_digest=settings.core_image_digest,
        symbolicator_version=settings.symbolicator_version,
        schema_version="1.1",
        grouping_version="group-v1.1",
        normalization_version=settings.normalization_version,
        symbol_inventory_version=workspace.symbol_inventory_version,
        idempotency_key=run_spec["idempotency_key"],
        status="QUEUED",
        inspect_object_key=inspection.object_key,
        analysis_context=context,
        assembly_mode="core-final",
    )
    session.add(run)
    session.flush()
    message: dict[str, Any] = {
        "schema_version": "1.2",
        "task_type": "analyze_frozen_run",
        "run_id": run.id,
        "attempt_id": f"att_{new_ulid()}",
        "queue": "dump-small" if blob.size <= 64 * 1024 * 1024 else "dump-large",
    }
    if request_id:
        message["request_id"] = request_id
    intent = create_task_intent(session, message, settings.schema_root)
    demand.state = "queued"
    demand.not_before = now
    demand.updated_at = now
    session.flush()
    return FrozenRunCreation(run, intent, True)
