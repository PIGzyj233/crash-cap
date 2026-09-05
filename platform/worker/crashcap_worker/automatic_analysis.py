"""Resident Demand planner that freezes and releases bounded automatic Runs."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from crashcap_api.config import Settings
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisDemandTarget,
    DumpBlob,
    DumpInspection,
    Occurrence,
)
from crashcap_api.services.analysis_demands import (
    DemandError,
    register_inspection,
    settle_demand_after_planning_failure,
)
from crashcap_api.services.analysis_scheduler import (
    ExecutionSlotClaim,
    bind_execution_slot,
    claim_execution_slots,
    heartbeat_planning_slot,
    release_planning_slot,
)
from crashcap_api.services.frozen_runs import FrozenRunPreparation, adopt_frozen_run
from crashcap_api.services.resolution_planning import snapshot_resolution
from crashcap_api.services.workspace_policies import (
    WorkspacePolicySnapshot,
    prepare_workspace_policies,
    snapshot_workspace_policies,
)
from crashcap_api.storage import ObjectStore
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .core_runner import CoreExecutionError, CoreExecutor
from .demand_inspection import prepare_inspection
from .resolution_planner import prepare_resolution

LOGGER = logging.getLogger(__name__)
STALE_PLAN_ERRORS = {
    "ANALYSIS_SLOT_LOST",
    "CATALOG_SNAPSHOT_CHANGED",
    "STALE_DEMAND_PLAN",
    "STALE_WORKSPACE_BUILDS",
    "STALE_WORKSPACE_POLICY",
}


@dataclass(frozen=True)
class _DemandInput:
    workspace_id: str
    dump_key: str
    dump_sha256: str
    dump_size: int
    inspection_id: str | None


@dataclass(frozen=True)
class _PlanningSnapshot:
    cause: str
    inspect_bytes: bytes
    policies: WorkspacePolicySnapshot
    resolution: Any


class AutomaticAnalysisPlanner:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        store: ObjectStore,
        core: CoreExecutor,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.store = store
        self.core = core

    def run_once(self, *, owner_id: str, now: datetime | None = None) -> int:
        """Claim one release page and fully adopt every successfully prepared Run."""

        if not self.settings.automatic_analysis_enabled or self.settings.automatic_analysis_paused:
            return 0
        current = now or datetime.now(UTC)
        with self.sessions.begin() as session:
            claims = claim_execution_slots(
                session,
                self.settings,
                owner_id=owner_id,
                now=current,
            )
        fixed_now = current if now is not None else None
        with self._renew_planning_claims(claims, fixed_now) as finished:
            for claim in claims:
                try:
                    self._process_claim(claim, fixed_now)
                finally:
                    finished[claim.demand_id].set()
        return len(claims)

    def _process_claim(self, claim: ExecutionSlotClaim, fixed_now: datetime | None) -> None:
        try:
            self._prepare_and_adopt(claim, fixed_now)
        except Exception as error:
            settled_at = fixed_now or datetime.now(UTC)
            with self.sessions.begin() as session:
                released = release_planning_slot(session, claim)
                code = self._error_code(error)
                if released and code not in STALE_PLAN_ERRORS:
                    settle_demand_after_planning_failure(
                        session,
                        claim.demand_id,
                        cause=self._failure_cause(session, claim.demand_id),
                        error_code=code,
                        settings=self.settings,
                        now=settled_at,
                    )
            LOGGER.exception(
                "automatic analysis planning failed demand_id=%s code=%s",
                claim.demand_id,
                self._error_code(error),
            )

    @contextmanager
    def _renew_planning_claims(
        self,
        claims: tuple[ExecutionSlotClaim, ...],
        fixed_now: datetime | None,
    ) -> Iterator[dict[str, threading.Event]]:
        finished = {claim.demand_id: threading.Event() for claim in claims}
        if not claims:
            yield finished
            return
        stop = threading.Event()

        def renew() -> None:
            interval = min(30, self.settings.automatic_analysis_planning_lease_seconds / 3)
            while not stop.wait(interval):
                for claim in claims:
                    if stop.is_set():
                        return
                    if finished[claim.demand_id].is_set():
                        continue
                    try:
                        self._heartbeat(claim, fixed_now)
                    except DemandError:
                        # Adoption/release may race this heartbeat. A lost owner
                        # cannot be revived; final binding rechecks its token.
                        finished[claim.demand_id].set()
                    except Exception:
                        LOGGER.exception("planning heartbeat failed demand_id=%s", claim.demand_id)

        thread = threading.Thread(target=renew, name="automatic-planning-lease", daemon=True)
        thread.start()
        try:
            yield finished
        finally:
            stop.set()
            thread.join(timeout=5)

    def _demand_input(self, demand_id: str) -> _DemandInput:
        with self.sessions() as session:
            demand = session.get(AnalysisDemand, demand_id)
            occurrence = session.get(Occurrence, demand.occurrence_id) if demand else None
            blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
            if demand is None or occurrence is None or blob is None:
                raise RuntimeError("automatic Demand target disappeared")
            return _DemandInput(
                demand.workspace_id,
                blob.object_key,
                blob.sha256.lower(),
                blob.size,
                demand.inspection_id,
            )

    def _ensure_inspection(self, claim: ExecutionSlotClaim, now: datetime) -> None:
        source = self._demand_input(claim.demand_id)
        if source.inspection_id is not None:
            return
        evidence = prepare_inspection(
            self.core,
            self.store,
            workspace_id=source.workspace_id,
            dump_key=source.dump_key,
            dump_sha256=source.dump_sha256,
            dump_size=source.dump_size,
        )
        with self.sessions.begin() as session:
            register_inspection(session, claim.demand_id, evidence, now=now)

    def _snapshot(self, claim: ExecutionSlotClaim) -> _PlanningSnapshot:
        with self.sessions.begin() as session:
            demand = session.scalar(
                select(AnalysisDemand)
                .where(AnalysisDemand.id == claim.demand_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if demand is None or demand.inspection_id is None:
                raise RuntimeError("automatic Demand lost its inspection")
            inspection = session.get(DumpInspection, demand.inspection_id)
            occurrence = session.get(Occurrence, demand.occurrence_id)
            if inspection is None or occurrence is None:
                raise RuntimeError("automatic Demand evidence disappeared")
            resolution = snapshot_resolution(session, demand.id)
            policies = snapshot_workspace_policies(
                session, demand.workspace_id, [row["identity"] for row in inspection.modules]
            )
            cause = self._cause(session, demand)
        inspect_bytes = self._read_exact(
            resolution.inspect_object_key,
            resolution.inspect_sha256,
            64 * 1024**2,
        )
        return _PlanningSnapshot(cause, inspect_bytes, policies, resolution)

    def _prepare_and_adopt(self, claim: ExecutionSlotClaim, fixed_now: datetime | None) -> None:
        prepared_at = fixed_now or datetime.now(UTC)
        self._heartbeat(claim, fixed_now)
        self._ensure_inspection(claim, prepared_at)
        self._heartbeat(claim, fixed_now)
        snapshot = self._snapshot(claim)
        policy_snapshots = prepare_workspace_policies(
            snapshot.policies,
            json.loads(snapshot.inspect_bytes),
            public_sources=self.settings.frozen_public_sources,
            schema_root=self.settings.schema_root / "drafts/qa-symbol-import",
        )
        self._heartbeat(claim, fixed_now)
        resolution = prepare_resolution(self.core, self.store, snapshot.resolution)
        self._heartbeat(claim, fixed_now)
        # Replanning retains fresh candidate receipts under new object keys. If the
        # semantic target is reused, its immutable Run must still reference the
        # original manifest bytes. Read those outside the adoption transaction.
        with self.sessions() as session:
            demand = session.get(AnalysisDemand, claim.demand_id)
            target = (
                session.get(AnalysisDemandTarget, (demand.id, demand.generation))
                if demand is not None and demand.generation
                else None
            )
            retained = (
                (target.manifest_object_key, target.manifest_sha256)
                if target is not None
                and target.resolution_fingerprint == resolution.resolution_fingerprint
                else None
            )
        retained_bytes = self._read_exact(*retained, 64 * 1024**2) if retained else None
        prepared = FrozenRunPreparation(
            expected_sequence=resolution.change_sequence,
            cause=snapshot.cause,
            manifest=resolution.manifest,
            manifest_bytes=resolution.manifest_bytes,
            manifest_object_key=resolution.manifest_object_key,
            inspect_bytes=snapshot.inspect_bytes,
            policy_snapshot=snapshot.policies,
            policy_snapshots=policy_snapshots,
            retained_manifest_bytes=retained_bytes,
        )
        adopted_at = fixed_now or datetime.now(UTC)
        with self.sessions.begin() as session:
            created = adopt_frozen_run(
                session,
                self.settings,
                claim.demand_id,
                prepared,
                now=adopted_at,
            )
            bind_execution_slot(session, claim, created.run.id, now=adopted_at)

    def _heartbeat(self, claim: ExecutionSlotClaim, fixed_now: datetime | None) -> None:
        current = fixed_now or datetime.now(UTC)
        with self.sessions.begin() as session:
            if not heartbeat_planning_slot(
                session,
                self.settings,
                claim,
                now=current,
            ):
                raise DemandError("ANALYSIS_SLOT_LOST")

    def _read_bounded(self, key: str, limit: int) -> bytes:
        value = bytearray()
        for block in self.store.stream(key):
            if len(value) + len(block) > limit:
                raise CoreExecutionError(
                    "AUTOMATIC_PLANNER_OBJECT_LIMIT",
                    "Planner object exceeds its bounded size",
                )
            value.extend(block)
        return bytes(value)

    def _read_exact(self, key: str, expected_sha256: str, limit: int) -> bytes:
        value = self._read_bounded(key, limit)
        if hashlib.sha256(value).hexdigest() != expected_sha256:
            raise CoreExecutionError(
                "AUTOMATIC_PLANNER_OBJECT_HASH_MISMATCH",
                "Planner object digest mismatch",
            )
        return value

    @staticmethod
    def _cause(session: Session, demand: AnalysisDemand) -> str:
        if demand.state == "retry_wait":
            if demand.reason.startswith(("planning_retry:", "execution_retry:")):
                parts = demand.reason.split(":", 2)
                if len(parts) == 3 and parts[1] in {
                    "initial",
                    "symbol_refresh",
                    "role_change",
                    "engine_upgrade",
                    "evidence_correction",
                    "manual",
                }:
                    return parts[1]
            target = (
                session.get(AnalysisDemandTarget, (demand.id, demand.generation))
                if demand.generation
                else None
            )
            if target is None:
                raise RuntimeError("retry Demand has no prior immutable target")
            return target.cause
        if demand.reason in {
            "symbol_refresh",
            "role_change",
            "engine_upgrade",
            "evidence_correction",
            "manual",
        }:
            return demand.reason
        return "initial"

    @staticmethod
    def _failure_cause(session: Session, demand_id: str) -> str:
        demand = session.get(AnalysisDemand, demand_id)
        if demand is None:
            return "initial"
        return AutomaticAnalysisPlanner._cause(session, demand)

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, (CoreExecutionError, DemandError)):
            return str(getattr(error, "code", "") or str(error))[:200]
        return type(error).__name__.upper()[:200]
