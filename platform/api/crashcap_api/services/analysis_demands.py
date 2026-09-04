"""Persistent preparation and exact identity fanout; callers own short transactions.

All mutations acquire the catalog commit fence before demand rows. Object I/O and
Core calls happen outside this module. No function creates or mutates a Run or Current.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..contracts import load_validator
from ..evidence_comparison import ComparisonDecision
from ..frozen_inputs import (
    INSPECTOR_VERSION,
    digest,
    normalize_identity,
    resolution_fingerprint,
    verify_selection,
)
from ..ids import new_ulid
from ..models import (
    AnalysisDemand,
    AnalysisDemandTarget,
    AnalysisEventCursor,
    CatalogChange,
    DumpBlob,
    DumpInspection,
    DumpSymbolReference,
    Occurrence,
    Workspace,
    WorkspaceModuleRole,
)
from .symbol_catalog import lock_catalog


class DemandError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise DemandError(reason)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _live(blob: DumpBlob, now: datetime) -> bool:
    return (
        blob.verification_status == "ACCEPTED"
        and blob.deleted_at is None
        and (blob.expires_at is None or _utc(blob.expires_at) > now)
    )


def _demand(session: Session, demand_id: str) -> AnalysisDemand:
    result = session.scalar(
        select(AnalysisDemand)
        .where(AnalysisDemand.id == demand_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(result is not None, "DEMAND_NOT_FOUND")
    assert result is not None
    return result


def restart_exhausted_demand(
    session: Session,
    settings: Settings,
    demand_id: str,
    *,
    workspace_id: str,
    expected_generation: int,
    expected_sequence: int,
    now: datetime,
) -> AnalysisDemand:
    """Request a new manual cycle; the caller owns authorization, audit and commit."""
    require(settings.automatic_analysis_enabled, "AUTOMATIC_ANALYSIS_DISABLED")
    require(not settings.automatic_analysis_paused, "AUTOMATIC_ANALYSIS_PAUSED")
    now = _utc(now)
    lock_catalog(session)
    demand = _demand(session, demand_id)
    require(demand.workspace_id == workspace_id, "DEMAND_NOT_FOUND")
    require(
        (demand.generation, demand.change_sequence) == (expected_generation, expected_sequence),
        "STALE_DEMAND",
    )
    require(demand.state == "retry_exhausted", "DEMAND_NOT_EXHAUSTED")
    occurrence = session.get(Occurrence, demand.occurrence_id)
    require(occurrence is not None, "OCCURRENCE_NOT_FOUND")
    assert occurrence is not None
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    require(blob is not None and blob.workspace_id == workspace_id, "DUMP_SCOPE_MISMATCH")
    assert blob is not None
    require(_live(blob, now), "DUMP_UNAVAILABLE")
    demand.change_sequence += 1
    demand.state, demand.reason = "preparing", "manual"
    demand.not_before = demand.updated_at = now
    demand.first_event_at = demand.last_event_at = None
    session.flush()
    return demand


def ensure_demand(session: Session, occurrence_id: str, *, now: datetime) -> AnalysisDemand:
    """Idempotently persist preparation before inspect; no fabricated frozen Run."""
    now = _utc(now)
    lock_catalog(session)
    occurrence = session.get(Occurrence, occurrence_id)
    require(occurrence is not None, "OCCURRENCE_NOT_FOUND")
    assert occurrence is not None
    existing = session.scalar(
        select(AnalysisDemand).where(AnalysisDemand.occurrence_id == occurrence_id)
    )
    if existing is not None:
        return existing
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    require(
        blob is not None and blob.workspace_id == occurrence.workspace_id, "DUMP_SCOPE_MISMATCH"
    )
    assert blob is not None
    live = _live(blob, now)
    demand = AnalysisDemand(
        id="dmd_" + new_ulid(),
        occurrence_id=occurrence.id,
        workspace_id=occurrence.workspace_id,
        state="preparing" if live else "cannot_recompute",
        reason="new_dump" if live else "DUMP_UNAVAILABLE",
        not_before=now,
        created_at=now,
        updated_at=now,
    )
    session.add(demand)
    session.flush()
    return demand


@dataclass(frozen=True)
class InspectionEvidence:
    dump_sha256: str
    dump_size: int
    inspector_version: str
    inspector_provenance: str
    object_key: str
    object_sha256: str
    modules: tuple[dict[str, Any], ...]


def inspection_evidence(
    data: bytes,
    *,
    dump_sha256: str,
    dump_size: int,
    inspector_version: str,
    inspector_provenance: str,
    object_key: str,
) -> InspectionEvidence:
    """Project a trusted actual Core inspect after independent Dump hash verification."""
    require(bool(object_key and inspector_provenance), "INSPECTION_PROVENANCE_MISSING")
    require(inspector_version == INSPECTOR_VERSION, "UNSUPPORTED_INSPECTOR_VERSION")
    require(re.fullmatch(r"[0-9a-f]{64}", dump_sha256) is not None, "INVALID_DUMP_SHA")
    value = json.loads(data)
    require(isinstance(value, dict), "INVALID_INSPECT")
    require(value.get("schema_version") == "0.1", "UNSUPPORTED_INSPECT_VERSION")
    require(value.get("dump", {}).get("size") == dump_size > 0, "INSPECT_DUMP_SIZE_MISMATCH")
    require(
        value.get("process", {}).get("architecture") == "x86_64", "UNSUPPORTED_DUMP_ARCHITECTURE"
    )
    rows = value.get("modules")
    require(isinstance(rows, list), "INSPECT_MODULES_MISSING")
    modules = []
    for index, module in enumerate(rows):
        require(isinstance(module, dict), "INVALID_INSPECT_MODULE")
        identity = normalize_identity({**module, "architecture": "x86_64"})
        modules.append({"module_index": index, "identity": identity})
    return InspectionEvidence(
        dump_sha256,
        dump_size,
        inspector_version,
        inspector_provenance,
        object_key,
        hashlib.sha256(data).hexdigest(),
        tuple(modules),
    )


def register_inspection(
    session: Session, demand_id: str, evidence: InspectionEvidence, *, now: datetime
) -> DumpInspection | None:
    require(evidence.inspector_version == INSPECTOR_VERSION, "UNSUPPORTED_INSPECTOR_VERSION")
    require(bool(evidence.inspector_provenance), "INSPECTION_PROVENANCE_MISSING")
    now = _utc(now)
    watermark = lock_catalog(session)
    demand = _demand(session, demand_id)
    occurrence = session.get(Occurrence, demand.occurrence_id)
    assert occurrence is not None
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    assert blob is not None
    if not _live(blob, now):
        demand.state, demand.reason, demand.updated_at = "cannot_recompute", "DUMP_UNAVAILABLE", now
        return None
    require(
        (blob.sha256.lower(), blob.size) == (evidence.dump_sha256, evidence.dump_size),
        "INSPECTION_DUMP_MISMATCH",
    )
    inspection_id = digest(
        [
            "dump-inspection-v2",
            blob.workspace_id,
            blob.sha256.lower(),
            evidence.inspector_version,
            evidence.inspector_provenance,
        ]
    )
    inspection = session.get(DumpInspection, inspection_id)
    if inspection is None:
        inspection = DumpInspection(
            id=inspection_id,
            dump_blob_id=blob.id,
            dump_sha256=evidence.dump_sha256,
            dump_size=evidence.dump_size,
            inspector_version=evidence.inspector_version,
            inspector_provenance=evidence.inspector_provenance,
            object_key=evidence.object_key,
            object_sha256=evidence.object_sha256,
            modules=list(evidence.modules),
            created_at=now,
        )
        session.add(inspection)
        session.flush()
    else:
        require(
            inspection.object_sha256 == evidence.object_sha256
            and inspection.modules == list(evidence.modules)
            and inspection.dump_blob_id == blob.id,
            "INSPECTOR_VERSION_PRODUCED_DIFFERENT_EVIDENCE",
        )
    if demand.inspection_id == inspection.id:
        return inspection
    session.execute(
        delete(DumpSymbolReference).where(DumpSymbolReference.occurrence_id == occurrence.id)
    )
    for module in inspection.modules:
        session.add(
            DumpSymbolReference(
                occurrence_id=occurrence.id,
                module_index=module["module_index"],
                inspection_id=inspection.id,
                **module["identity"],
            )
        )
    demand.inspection_id = inspection.id
    # Events committed before registration are covered by the pending full plan.
    # Events committed later see these references. Both sides take the same fence.
    demand.index_revision = watermark.revision
    demand.change_sequence += 1
    demand.state, demand.not_before, demand.updated_at = "preparing", now, now
    session.flush()
    return inspection


def _note_change(
    session: Session, demand: AnalysisDemand, *, now: datetime, cause: str = "symbol_refresh"
) -> None:
    occurrence = session.get(Occurrence, demand.occurrence_id)
    assert occurrence is not None
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    assert blob is not None
    demand.change_sequence += 1
    demand.updated_at = now
    if not _live(blob, now):
        demand.state, demand.reason, demand.not_before = (
            "cannot_recompute",
            "DUMP_UNAVAILABLE",
            None,
        )
        return
    first = _utc(demand.first_event_at) if demand.first_event_at else now
    demand.first_event_at, demand.last_event_at = first, now
    # New dumps remain immediately eligible while refresh traffic coalesces.
    if demand.generation > 0:
        demand.not_before = min(now + timedelta(seconds=30), first + timedelta(seconds=60))
        if demand.state not in {"running", "paused"}:
            demand.state = "coalescing"
        demand.reason = cause


@dataclass(frozen=True)
class DemandSettlement:
    state: str
    retry_attempt: int
    not_before: datetime | None


def settle_demand_after_planning_failure(
    session: Session,
    demand_id: str,
    *,
    cause: str,
    error_code: str,
    settings: Settings,
    now: datetime,
) -> DemandSettlement:
    """Back off planner/environment failures without creating an unbounded loop."""

    now = _utc(now)
    demand = _demand(session, demand_id)
    occurrence = session.get(Occurrence, demand.occurrence_id)
    blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
    if blob is None:
        demand.state = "cannot_recompute"
        demand.reason = "DUMP_UNAVAILABLE"
        demand.not_before = None
    else:
        _settle_runtime_failure(
            demand,
            blob,
            cause=cause,
            error_code=error_code,
            phase="planning",
            retryable=True,
            settings=settings,
            now=now,
        )
    demand.updated_at = now
    return DemandSettlement(demand.state, demand.retry_attempt, demand.not_before)


def settle_demand_after_execution_failure(
    demand: AnalysisDemand,
    blob: DumpBlob,
    *,
    cause: str,
    error_code: str,
    retryable: bool,
    settings: Settings,
    now: datetime,
) -> DemandSettlement:
    now = _utc(now)
    pending = _pending_change(demand)
    _settle_runtime_failure(
        demand,
        blob,
        cause=cause,
        error_code=error_code,
        phase="execution",
        retryable=retryable,
        settings=settings,
        now=now,
    )
    _restore_pending_change(demand, blob, pending, now)
    demand.updated_at = now
    return DemandSettlement(demand.state, demand.retry_attempt, demand.not_before)


def _settle_runtime_failure(
    demand: AnalysisDemand,
    blob: DumpBlob,
    *,
    cause: str,
    error_code: str,
    phase: str,
    retryable: bool,
    settings: Settings,
    now: datetime,
) -> None:
    if not _live(blob, now):
        demand.state = "cannot_recompute"
        demand.reason = "DUMP_UNAVAILABLE"
        demand.not_before = None
    elif not retryable:
        demand.state = "needs_review"
        demand.reason = f"{phase}_failed:{cause}:{error_code}"
        demand.not_before = None
    elif demand.retry_attempt + 1 >= settings.analysis_max_attempts:
        demand.state = "retry_exhausted"
        demand.reason = f"{phase}_retry_exhausted:{cause}:{error_code}"
        demand.not_before = None
    else:
        delay = min(
            settings.analysis_retry_max_seconds,
            settings.analysis_retry_base_seconds * (2**demand.retry_attempt),
        )
        demand.retry_attempt += 1
        demand.state = "retry_wait"
        demand.reason = f"{phase}_retry:{cause}:{error_code}"
        demand.not_before = now + timedelta(seconds=delay)


def _pending_change(demand: AnalysisDemand) -> tuple[str, datetime | None] | None:
    if (
        demand.generation > 0
        and demand.change_sequence > demand.planned_sequence
        and demand.first_event_at is not None
    ):
        return demand.reason, demand.not_before
    return None


def _restore_pending_change(
    demand: AnalysisDemand,
    blob: DumpBlob,
    pending: tuple[str, datetime | None] | None,
    now: datetime,
) -> None:
    if pending is None or not _live(blob, now):
        return
    demand.state = "coalescing"
    demand.reason = pending[0]
    demand.not_before = pending[1] or now


def retry_is_due(demand: AnalysisDemand, *, now: datetime) -> bool:
    return demand.not_before is not None and _utc(demand.not_before) <= _utc(now)


def settle_demand_after_comparison(
    demand: AnalysisDemand,
    blob: DumpBlob,
    decision: ComparisonDecision,
    *,
    promoted: bool,
    settings: Settings,
    now: datetime,
) -> DemandSettlement:
    """Apply one fenced comparison outcome with a finite retry budget."""

    now = _utc(now)
    pending = _pending_change(demand)
    if decision.retry:
        if not _live(blob, now):
            demand.state = "cannot_recompute"
            demand.reason = "DUMP_UNAVAILABLE"
            demand.not_before = None
        elif demand.retry_attempt + 1 >= settings.analysis_max_attempts:
            demand.state = "retry_exhausted"
            demand.reason = f"retry_exhausted:{decision.reason}"
            demand.not_before = None
        else:
            delay = min(
                settings.analysis_retry_max_seconds,
                settings.analysis_retry_base_seconds * (2**demand.retry_attempt),
            )
            demand.retry_attempt += 1
            demand.state = "retry_wait"
            demand.reason = f"retry:{decision.reason}"
            demand.not_before = now + timedelta(seconds=delay)
    else:
        demand.state = (
            "updated"
            if promoted
            else "needs_review"
            if decision.decision == "incomparable"
            else "retained"
        )
        demand.reason = decision.reason
        demand.not_before = None
    _restore_pending_change(demand, blob, pending, now)
    demand.updated_at = now
    return DemandSettlement(demand.state, demand.retry_attempt, demand.not_before)


@dataclass(frozen=True)
class FanoutPage:
    revision: int
    affected: tuple[str, ...]
    event_complete: bool
    caught_up: bool


def fanout_next(session: Session, *, now: datetime, limit: int = 200) -> FanoutPage:
    """Advance one durable event page. Cursor and demand writes commit together."""
    require(1 <= limit <= 200, "FANOUT_LIMIT_INVALID")
    now = _utc(now)
    watermark = lock_catalog(session)
    cursor = session.get(AnalysisEventCursor, "catalog-symbols-v1")
    if cursor is None:
        cursor = AnalysisEventCursor(id="catalog-symbols-v1", revision=0)
        session.add(cursor)
        session.flush()
    query = select(CatalogChange).order_by(CatalogChange.revision).limit(1)
    query = query.where(
        CatalogChange.revision == cursor.revision
        if cursor.after_occurrence_id is not None
        else CatalogChange.revision > cursor.revision
    )
    event = session.scalar(query)
    if event is None:
        require(cursor.after_occurrence_id is None, "CATALOG_EVENT_GAP")
        return FanoutPage(cursor.revision, (), True, cursor.revision == watermark.revision)
    rows: list[str] = []
    if event.affects_selection:
        query_ids = (
            select(AnalysisDemand.occurrence_id)
            .join(
                DumpSymbolReference,
                DumpSymbolReference.occurrence_id == AnalysisDemand.occurrence_id,
            )
            .where(
                AnalysisDemand.index_revision < event.revision,
                DumpSymbolReference.inspection_id == AnalysisDemand.inspection_id,
                or_(
                    DumpSymbolReference.code_id == event.code_id,
                    DumpSymbolReference.debug_id == event.debug_id,
                ),
                or_(
                    DumpSymbolReference.code_id.is_(None),
                    DumpSymbolReference.code_id == event.code_id,
                ),
                or_(
                    DumpSymbolReference.debug_id.is_(None),
                    DumpSymbolReference.debug_id == event.debug_id,
                ),
                DumpSymbolReference.architecture.in_(["unknown", event.architecture]),
            )
        )
        if cursor.after_occurrence_id is not None:
            query_ids = query_ids.where(AnalysisDemand.occurrence_id > cursor.after_occurrence_id)
        rows = list(
            session.scalars(
                query_ids.distinct().order_by(AnalysisDemand.occurrence_id).limit(limit + 1)
            )
        )
    for occurrence_id in rows[:limit]:
        demand = session.scalars(
            select(AnalysisDemand)
            .where(AnalysisDemand.occurrence_id == occurrence_id)
            .with_for_update()
        ).one()
        _note_change(session, demand, now=now)
    more = len(rows) > limit
    cursor.revision = event.revision
    cursor.after_occurrence_id = rows[limit - 1] if more else None
    session.flush()
    return FanoutPage(
        event.revision,
        tuple(rows[:limit]),
        not more,
        not more and event.revision == watermark.revision,
    )


def fanout_workspace_role_next(
    session: Session, workspace_id: str, *, now: datetime, limit: int = 200
) -> FanoutPage:
    """Durably page one append-only exact-role event into matching demands."""
    require(1 <= limit <= 200, "FANOUT_LIMIT_INVALID")
    now = _utc(now)
    # This short metadata transaction serializes declarations and role fanout.
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    require(workspace is not None, "WORKSPACE_NOT_FOUND")
    assert workspace is not None
    cursor_id = f"workspace-role-v1:{workspace_id}"
    cursor = session.get(AnalysisEventCursor, cursor_id)
    if cursor is None:
        cursor = AnalysisEventCursor(id=cursor_id, revision=0)
        session.add(cursor)
        session.flush()
    event_version = (
        cursor.revision if cursor.after_occurrence_id is not None else cursor.revision + 1
    )
    event = session.get(WorkspaceModuleRole, (workspace_id, event_version))
    if event is None:
        require(cursor.after_occurrence_id is None, "WORKSPACE_ROLE_EVENT_GAP")
        require(cursor.revision == workspace.module_role_version, "WORKSPACE_ROLE_EVENT_GAP")
        return FanoutPage(cursor.revision, (), True, True)
    query_ids = (
        select(AnalysisDemand.occurrence_id)
        .join(
            DumpSymbolReference,
            DumpSymbolReference.occurrence_id == AnalysisDemand.occurrence_id,
        )
        .where(
            AnalysisDemand.workspace_id == workspace_id,
            DumpSymbolReference.inspection_id == AnalysisDemand.inspection_id,
            DumpSymbolReference.code_id == event.code_id,
            DumpSymbolReference.debug_id == event.debug_id,
            DumpSymbolReference.architecture == event.architecture,
        )
        .distinct()
        .order_by(AnalysisDemand.occurrence_id)
        .limit(limit + 1)
    )
    if cursor.after_occurrence_id is not None:
        query_ids = query_ids.where(AnalysisDemand.occurrence_id > cursor.after_occurrence_id)
    rows = list(session.scalars(query_ids))
    for occurrence_id in rows[:limit]:
        demand = session.scalars(
            select(AnalysisDemand)
            .where(AnalysisDemand.occurrence_id == occurrence_id)
            .with_for_update()
        ).one()
        _note_change(session, demand, now=now, cause="role_change")
    more = len(rows) > limit
    cursor.revision = event.version
    cursor.after_occurrence_id = rows[limit - 1] if more else None
    session.flush()
    return FanoutPage(
        event.version,
        tuple(rows[:limit]),
        not more,
        not more and event.version == workspace.module_role_version,
    )


def freeze_target(
    session: Session,
    demand_id: str,
    *,
    expected_sequence: int,
    manifest: dict[str, Any],
    manifest_object_key: str,
    context_sha256: str,
    cause: str,
    schema_root: Path,
    now: datetime,
) -> AnalysisDemandTarget:
    """Adopt a trusted planner snapshot; no Run/task is emitted by this preparatory layer."""
    now = _utc(now)
    watermark = lock_catalog(session)
    demand = _demand(session, demand_id)
    require(demand.change_sequence == expected_sequence, "STALE_DEMAND_PLAN")
    inspection = session.get(DumpInspection, demand.inspection_id) if demand.inspection_id else None
    require(inspection is not None, "INSPECTION_REQUIRED")
    assert inspection is not None
    blob = session.get(DumpBlob, inspection.dump_blob_id)
    require(blob is not None and _live(blob, now), "DUMP_UNAVAILABLE")
    validator = load_validator(str((schema_root / "resolution-manifest-v1.schema.json").resolve()))
    require(not list(validator.iter_errors(manifest)), "INVALID_MANIFEST")
    for module in manifest["modules"]:
        verify_selection(module)
    require(manifest["catalog_revision"] == watermark.revision, "CATALOG_SNAPSHOT_CHANGED")
    require(
        manifest["dump_sha256"] == inspection.dump_sha256
        and manifest["inspect_sha256"] == inspection.object_sha256
        and manifest["inspector_version"] == inspection.inspector_version,
        "MANIFEST_INSPECTION_MISMATCH",
    )
    require(
        [
            {"module_index": m["module_index"], "identity": m["identity"]}
            for m in manifest["modules"]
        ]
        == inspection.modules,
        "MANIFEST_MODULES_MISMATCH",
    )
    require(
        bool(manifest_object_key) and re.fullmatch(r"[0-9a-f]{64}", context_sha256) is not None,
        "INVALID_TARGET_CONTEXT",
    )
    require(
        cause
        in {
            "initial",
            "symbol_refresh",
            "role_change",
            "engine_upgrade",
            "evidence_correction",
            "manual",
        },
        "INVALID_TARGET_CAUSE",
    )
    fingerprint = resolution_fingerprint(manifest)
    target = (
        session.get(AnalysisDemandTarget, (demand.id, demand.generation))
        if demand.generation
        else None
    )
    manual_cycle = cause == "manual" and expected_sequence > demand.planned_sequence
    same_target = target is not None and (
        target.resolution_fingerprint, target.context_sha256, target.cause
    ) == (fingerprint, context_sha256, cause)
    if manual_cycle or not same_target:
        demand.generation += 1
        demand.retry_attempt = 0
        target = AnalysisDemandTarget(
            demand_id=demand.id,
            generation=demand.generation,
            inspection_id=inspection.id,
            resolution_fingerprint=fingerprint,
            context_sha256=context_sha256,
            cause=cause,
            manifest_object_key=manifest_object_key,
            manifest_sha256=digest(manifest),
            catalog_revision=watermark.revision,
            created_at=now,
        )
        session.add(target)
        # Remains preparing until the later Run+durable-intent transaction.
        if demand.state not in {"running", "paused"}:
            demand.state = "preparing"
    demand.planned_sequence = expected_sequence
    demand.index_revision = watermark.revision
    demand.first_event_at = demand.last_event_at = None
    demand.not_before, demand.updated_at = now, now
    session.flush()
    assert target is not None
    return target
