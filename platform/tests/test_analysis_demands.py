from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.evidence_comparison import ComparisonDecision
from crashcap_api.frozen_inputs import FrozenInputError, canonical_bytes
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisDemandTarget,
    AnalysisEventCursor,
    AnalysisRun,
    CatalogWatermark,
    DumpBlob,
    DumpInspection,
    DumpSymbolReference,
    Occurrence,
    Workspace,
)
from crashcap_api.services.analysis_demands import (
    DemandError,
    ensure_demand,
    fanout_next,
    fanout_workspace_role_next,
    freeze_target,
    inspection_evidence,
    register_inspection,
    settle_demand_after_comparison,
    settle_demand_after_execution_failure,
    settle_demand_after_planning_failure,
)
from crashcap_api.services.analysis_scheduler import claim_execution_slots
from crashcap_api.services.symbol_catalog import review_pair
from crashcap_api.services.workspace_policies import declare_workspace_module_role
from crashcap_api.storage import create_object_store
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from crashcap_worker.demand_inspection import prepare_inspection
from sqlalchemy import func, select

from .catalog_fixtures import admit_pair, origin, pair_evidence

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts/drafts/qa-symbol-import"
NOW = datetime(2026, 9, 3, tzinfo=UTC)


@pytest.fixture
def demands(tmp_path):
    db = Database(Settings.for_test(tmp_path))
    yield db.sessions
    db.dispose()


def seed(session, number=0, workspace="wsp_a", *, sha=None, size=19):
    if session.get(Workspace, workspace) is None:
        session.add(Workspace(id=workspace, name=workspace))
        session.flush()
    blob = DumpBlob(
        id=f"blob_{workspace}_{number}",
        workspace_id=workspace,
        sha256=sha or hashlib.sha256(f"{number}".encode()).hexdigest(),
        size=size,
        object_key=f"dumps/{workspace}/{number}",
        verification_status="ACCEPTED",
    )
    session.add(blob)
    session.flush()
    occurrence = Occurrence(
        id=f"occ_{workspace}_{number:04}",
        workspace_id=workspace,
        dump_blob_id=blob.id,
        uploaded_at=NOW,
        occurred_at=NOW,
        time_source="uploaded",
    )
    session.add(occurrence)
    session.flush()
    demand = ensure_demand(session, occurrence.id, now=NOW)
    return demand, blob


def evidence(blob, *, code="123456789", debug="2" * 32 + "1", version="unit-inspector"):
    data = canonical_bytes(
        {
            "schema_version": "0.1",
            "dump": {"size": blob.size},
            "process": {"architecture": "x86_64"},
            "modules": [{"code_id": code, "debug_id": debug}],
        }
    )
    return inspection_evidence(
        data,
        dump_sha256=blob.sha256,
        dump_size=blob.size,
        inspector_version="inspect-v0.1",
        inspector_provenance=version,
        object_key=f"inspect/{blob.id}/{version}",
    )


def test_exact_workspace_role_events_page_all_matching_demands(demands):
    with demands.begin() as session:
        rows = [seed(session, number) for number in range(2)]
        for demand, blob in rows:
            inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
            freeze(session, demand, inspection)
        declare_workspace_module_role(
            session,
            "wsp_a",
            {"code_id": "123456789", "debug_id": "2" * 32 + "1", "architecture": "x86_64"},
            "dependency",
            now=NOW,
        )
        declare_workspace_module_role(
            session,
            "wsp_a",
            {"code_id": "123456789", "debug_id": "2" * 32 + "1", "architecture": "x86_64"},
            "owned",
            now=NOW,
        )
        pages = [fanout_workspace_role_next(session, "wsp_a", now=NOW, limit=1) for _ in range(4)]
        assert [(page.revision, page.event_complete, page.caught_up) for page in pages] == [
            (1, False, False),
            (1, True, False),
            (2, False, False),
            (2, True, True),
        ]
        assert [page.affected for page in pages] == [
            ("occ_wsp_a_0000",),
            ("occ_wsp_a_0001",),
            ("occ_wsp_a_0000",),
            ("occ_wsp_a_0001",),
        ]
        for demand, _ in rows:
            session.refresh(demand)
            assert demand.reason == "role_change"
            assert demand.state == "coalescing"


def manifest(session, inspection, pairs=()):
    state = "unique" if len(pairs) == 1 else "conflict" if pairs else "none"
    return {
        "schema_version": "resolution-manifest-v1",
        "dump_sha256": inspection.dump_sha256,
        "inspect_sha256": inspection.object_sha256,
        "inspector_version": inspection.inspector_version,
        "selection_version": "pair-selection-v1",
        "catalog_revision": session.get(CatalogWatermark, 1).revision,
        "modules": [
            {
                **module,
                "state": state,
                "candidates_complete": True,
                "candidate_pair_ids": sorted(pairs),
                "unavailable_pair_ids": [],
                "selected_pair_id": pairs[0] if len(pairs) == 1 else None,
                "reason": "unique"
                if pairs and len(pairs) == 1
                else "identity_conflict"
                if pairs
                else "missing",
                "candidate_evidence": {"object_key": "unit/evidence", "sha256": "d" * 64},
                "review_refs": [],
            }
            for module in inspection.modules
        ],
    }


def freeze(session, demand, inspection, pairs=(), **kwargs):
    return freeze_target(
        session,
        demand.id,
        expected_sequence=demand.change_sequence,
        manifest=manifest(session, inspection, pairs),
        manifest_object_key="unit/manifest",
        context_sha256=kwargs.get("context", "f" * 64),
        cause=kwargs.get("cause", "symbol_refresh"),
        schema_root=SCHEMAS,
        now=NOW,
    )


def test_demand_precedes_inspect_and_same_dump_other_workspace_keeps_private_cache(demands):
    with demands.begin() as session:
        a, blob_a = seed(session)
        b, blob_b = seed(session, workspace="wsp_b", sha=blob_a.sha256)
        assert ensure_demand(session, a.occurrence_id, now=NOW).id == a.id
        assert a.generation == 0 and a.inspection_id is None
        ia = register_inspection(session, a.id, evidence(blob_a), now=NOW)
        ib = register_inspection(session, b.id, evidence(blob_b), now=NOW)
        assert ia.id != ib.id
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 0
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 2
        old_sequence = a.change_sequence
        register_inspection(session, a.id, replace(evidence(blob_a), object_key="replica"), now=NOW)
        assert a.change_sequence == old_sequence
    with demands.begin() as session, pytest.raises(DemandError, match="DIFFERENT_EVIDENCE"):
        register_inspection(
            session, a.id, replace(evidence(blob_a), object_sha256="a" * 64), now=NOW
        )


def test_inspection_algorithm_and_executor_identity_are_independent(demands):
    with demands.begin() as session:
        demand, blob = seed(session)
        first_evidence = evidence(blob, version="binary-a")
        first = register_inspection(session, demand.id, first_evidence, now=NOW)
        second = register_inspection(
            session,
            demand.id,
            replace(first_evidence, inspector_provenance="binary-b", object_key="second"),
            now=NOW,
        )
        assert first.id != second.id
        assert first.inspector_version == second.inspector_version == "inspect-v0.1"
        assert first.inspector_provenance == "binary-a"
        assert session.scalar(select(func.count()).select_from(DumpInspection)) == 2
        with pytest.raises(DemandError, match="UNSUPPORTED_INSPECTOR_VERSION"):
            register_inspection(
                session,
                demand.id,
                replace(
                    first_evidence, inspector_version="core-inspect-v1:binary-sha256:" + "a" * 64
                ),
                now=NOW,
            )


def test_paginated_cross_workspace_fanout_rollback_resume_and_identity_filter(demands):
    with demands.begin() as session:
        for i in range(205):
            demand, blob = seed(session, i, "wsp_a" if i % 2 else "wsp_b")
            inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
            freeze(session, demand, inspection)
        other, blob = seed(session, 999)
        register_inspection(
            session, other.id, evidence(blob, code="999999999", debug="9" * 32 + "1"), now=NOW
        )
        admit_pair(session, *pair_evidence(), origin())
    with demands() as session:
        page = fanout_next(session, now=NOW)
        assert len(page.affected) == 200 and not page.event_complete
        session.rollback()
    with demands.begin() as session:
        assert session.get(AnalysisEventCursor, "catalog-symbols-v1") is None
        first = fanout_next(session, now=NOW)
    with demands.begin() as session:
        second = fanout_next(session, now=NOW + timedelta(seconds=1))
        assert len(second.affected) == 5 and second.event_complete and not second.caught_up
        assert not set(first.affected) & set(second.affected)
    with demands.begin() as session:
        for _ in range(8):
            if fanout_next(session, now=NOW).caught_up:
                break
        else:
            raise AssertionError("catalog fanout did not finish")
        assert session.get(AnalysisDemand, other.id).change_sequence == 2
        affected = session.scalars(
            select(AnalysisDemand).where(AnalysisDemand.generation == 1)
        ).all()
        assert len(affected) == 205 and all(d.change_sequence == 5 for d in affected)


def test_registration_compensates_already_consumed_events_and_later_events_are_seen(demands):
    with demands.begin() as session:
        demand, blob = seed(session)
        pair = admit_pair(session, *pair_evidence(), origin())
        for _ in range(8):
            if fanout_next(session, now=NOW).caught_up:
                break
        else:
            raise AssertionError("catalog fanout did not finish")
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        assert demand.index_revision == 3
        freeze(session, demand, inspection, (pair.id,))
        admit_pair(session, *pair_evidence(pdb_sha="c" * 64), origin("conflict"))
        assert fanout_next(session, now=NOW).affected == (demand.occurrence_id,)


def test_target_generations_ignore_replica_changes_but_a_conflict_a_is_new(demands):
    with demands.begin() as session:
        demand, blob = seed(session)
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        pair_a = admit_pair(session, *pair_evidence(), origin())
        first = freeze(session, demand, inspection, (pair_a.id,))
        original = first.manifest_sha256
        admit_pair(session, *pair_evidence(), origin("another-source"))
        assert not fanout_next(session, now=NOW).affected  # first event already covered
        assert freeze(session, demand, inspection, (pair_a.id,)).generation == 1
        assert first.manifest_sha256 == original
        pair_b = admit_pair(session, *pair_evidence(pdb_sha="c" * 64), origin("conflict"))
        assert freeze(session, demand, inspection, (pair_a.id, pair_b.id)).generation == 2
        review_pair(
            session,
            pair_b.id,
            state="withdrawn",
            reason="qualification fixture",
            idempotency_key="withdraw",
            expected_version=1,
            evidence_object_key="unit/review",
            evidence_sha256="d" * 64,
        )
        assert freeze(session, demand, inspection, (pair_a.id,)).generation == 3
        assert freeze(session, demand, inspection, (pair_a.id,), context="e" * 64).generation == 4
        assert (
            freeze(
                session, demand, inspection, (pair_a.id,), context="e" * 64, cause="role_change"
            ).generation
            == 5
        )
        assert session.scalar(select(func.count()).select_from(AnalysisDemandTarget)) == 5
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 0


def test_coalescing_deadline_and_stale_plan_rejection(demands):
    with demands.begin() as session:
        demand, blob = seed(session)
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        freeze(session, demand, inspection)
        old_manifest, sequence = manifest(session, inspection), demand.change_sequence
        for i in range(4):
            admit_pair(session, *pair_evidence(pdb_sha=f"{i + 10:064x}"), origin(str(i)))
            page = fanout_next(session, now=NOW + timedelta(seconds=i * 20))
            assert len(page.affected) == 1
        assert demand.not_before == NOW + timedelta(seconds=60)
        with pytest.raises(DemandError, match="STALE_DEMAND_PLAN"):
            freeze_target(
                session,
                demand.id,
                expected_sequence=sequence,
                manifest=old_manifest,
                manifest_object_key="stale",
                context_sha256="f" * 64,
                cause="symbol_refresh",
                schema_root=SCHEMAS,
                now=NOW,
            )
        with pytest.raises(DemandError, match="CATALOG_SNAPSHOT_CHANGED"):
            freeze_target(
                session,
                demand.id,
                expected_sequence=demand.change_sequence,
                manifest=old_manifest,
                manifest_object_key="stale",
                context_sha256="f" * 64,
                cause="symbol_refresh",
                schema_root=SCHEMAS,
                now=NOW,
            )


@pytest.mark.parametrize("mutation", ["selected", "reason", "coverage", "incomplete"])
def test_invalid_frozen_target_cannot_consume_generation(demands, mutation):
    with demands.begin() as session:
        demand, blob = seed(session)
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        value = manifest(session, inspection, ("a" * 64,))
        if mutation == "selected":
            value["modules"][0]["selected_pair_id"] = "b" * 64
        elif mutation == "reason":
            value["modules"][0]["reason"] = "missing"
        elif mutation == "coverage":
            value["modules"] = []
        else:
            value["modules"][0]["candidates_complete"] = False
        with pytest.raises((DemandError, FrozenInputError)):
            freeze_target(
                session,
                demand.id,
                expected_sequence=demand.change_sequence,
                manifest=value,
                manifest_object_key="invalid",
                context_sha256="f" * 64,
                cause="symbol_refresh",
                schema_root=SCHEMAS,
                now=NOW,
            )
        assert demand.generation == 0
        assert session.scalar(select(func.count()).select_from(AnalysisDemandTarget)) == 0


def test_fake_inspector_cannot_create_evidence(tmp_path):
    core = CoreExecutor(Settings.for_test(tmp_path))
    with pytest.raises(CoreExecutionError, match="Fake Core"):
        prepare_inspection(
            core, None, workspace_id="wsp_a", dump_key="not-read", dump_sha256="a" * 64, dump_size=1
        )


def test_expired_dump_is_visible_cannot_recompute(demands):
    with demands.begin() as session:
        demand, blob = seed(session)
        register_inspection(session, demand.id, evidence(blob), now=NOW)
        blob.expires_at = NOW
        session.flush()
        admit_pair(session, *pair_evidence(), origin())
        fanout_next(session, now=NOW)
        assert demand.state == "cannot_recompute" and demand.reason == "DUMP_UNAVAILABLE"
        assert register_inspection(session, demand.id, evidence(blob), now=NOW) is None


def test_comparison_retry_is_finite_exponential_and_preserves_diagnostics(demands, tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "analysis_max_attempts": 3,
            "analysis_retry_base_seconds": 30,
            "analysis_retry_max_seconds": 45,
        }
    )
    decision = ComparisonDecision(
        None,
        "run_candidate",
        "retain",
        "business_transient_loss",
        True,
        (),
    )
    with demands.begin() as session:
        demand, blob = seed(session)
        demand.generation = 1
        demand.state = "running"
        first = settle_demand_after_comparison(
            demand,
            blob,
            decision,
            promoted=False,
            settings=settings,
            now=NOW,
        )
        assert (first.state, first.retry_attempt, first.not_before) == (
            "retry_wait",
            1,
            NOW + timedelta(seconds=30),
        )
        demand.state = "running"
        second = settle_demand_after_comparison(
            demand,
            blob,
            decision,
            promoted=False,
            settings=settings,
            now=NOW + timedelta(seconds=30),
        )
        assert (second.state, second.retry_attempt, second.not_before) == (
            "retry_wait",
            2,
            NOW + timedelta(seconds=75),
        )
        demand.state = "running"
        exhausted = settle_demand_after_comparison(
            demand,
            blob,
            decision,
            promoted=False,
            settings=settings,
            now=NOW + timedelta(seconds=75),
        )
        assert (exhausted.state, exhausted.retry_attempt, exhausted.not_before) == (
            "retry_exhausted",
            2,
            None,
        )
        assert demand.reason == "retry_exhausted:business_transient_loss"


def test_retry_refuses_an_expired_dump_and_nonretry_outcomes_settle(demands, tmp_path):
    settings = Settings.for_test(tmp_path)
    retry = ComparisonDecision(None, "run_one", "retain", "system_transient_loss", True, ())
    with demands.begin() as session:
        demand, blob = seed(session)
        blob.expires_at = NOW
        result = settle_demand_after_comparison(
            demand,
            blob,
            retry,
            promoted=False,
            settings=settings,
            now=NOW,
        )
        assert (result.state, demand.reason, result.not_before) == (
            "cannot_recompute",
            "DUMP_UNAVAILABLE",
            None,
        )
        incomparable = replace(
            retry,
            decision="incomparable",
            reason="fault_changed",
            retry=False,
        )
        result = settle_demand_after_comparison(
            demand,
            blob,
            incomparable,
            promoted=False,
            settings=settings,
            now=NOW,
        )
        assert (result.state, demand.reason) == ("needs_review", "fault_changed")


def test_planning_and_execution_failures_share_finite_budget_and_preserve_cause(demands, tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "analysis_max_attempts": 2,
            "analysis_retry_base_seconds": 30,
        }
    )
    with demands.begin() as session:
        demand, blob = seed(session)
        result = settle_demand_after_planning_failure(
            session,
            demand.id,
            cause="initial",
            error_code="OBJECT_TIMEOUT",
            settings=settings,
            now=NOW,
        )
        assert (result.state, result.retry_attempt, demand.reason) == (
            "retry_wait",
            1,
            "planning_retry:initial:OBJECT_TIMEOUT",
        )
        demand.state = "running"
        exhausted = settle_demand_after_execution_failure(
            demand,
            blob,
            cause="initial",
            error_code="CORE_TIMEOUT",
            retryable=True,
            settings=settings,
            now=NOW + timedelta(seconds=30),
        )
        assert (exhausted.state, exhausted.retry_attempt, exhausted.not_before) == (
            "retry_exhausted",
            1,
            None,
        )
        demand.retry_attempt = 0
        permanent = settle_demand_after_execution_failure(
            demand,
            blob,
            cause="symbol_refresh",
            error_code="INVALID_FROZEN_EVIDENCE",
            retryable=False,
            settings=settings,
            now=NOW,
        )
        assert (permanent.state, demand.reason) == (
            "needs_review",
            "execution_failed:symbol_refresh:INVALID_FROZEN_EVIDENCE",
        )


def test_exhausted_cycle_stays_stopped_until_new_relevant_evidence(demands, tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={"automatic_analysis_enabled": True, "analysis_max_attempts": 2}
    )
    with demands.begin() as session:
        demand, blob = seed(session)
        pair = admit_pair(session, *pair_evidence(), origin())
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        target = freeze(session, demand, inspection, (pair.id,))
        demand_id, blob_id, pair_id = demand.id, blob.id, pair.id
        original_target = (target.generation, target.resolution_fingerprint, target.manifest_sha256)
        for offset in (0, 30):
            settle_demand_after_execution_failure(
                demand,
                blob,
                cause="symbol_refresh",
                error_code="CORE_TIMEOUT",
                retryable=True,
                settings=settings,
                now=NOW + timedelta(seconds=offset),
            )
        assert demand.state == "retry_exhausted"
        assert demand.not_before is None
        stopped = (demand.change_sequence, demand.retry_attempt, demand.reason)
    # A fresh coordinator must not release an exhausted target, even long after backoff.
    later = NOW + timedelta(days=1)
    for source in ("unrelated", "replica"):
        with demands.begin() as session:
            if source == "unrelated":
                admit_pair(
                    session, *pair_evidence(pe_sha="c" * 64, code="999999999"), origin(source)
                )
            else:
                admit_pair(session, *pair_evidence(), origin(source))
            for _ in range(32):
                page = fanout_next(session, now=later)
                assert not page.affected
                if page.caught_up:
                    break
            else:
                pytest.fail("Catalog cursor failed to drain the bounded event set")
        with demands.begin() as session:
            assert not claim_execution_slots(
                session, settings, owner_id="new-coordinator", now=later
            )
            demand = session.get(AnalysisDemand, demand_id)
            assert demand.state == "retry_exhausted"
            assert (demand.change_sequence, demand.retry_attempt, demand.reason) == stopped
            assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 0
    with demands.begin() as session:
        conflict = admit_pair(session, *pair_evidence(pdb_sha="d" * 64), origin("new-evidence"))
        assert fanout_next(session, now=later).affected == (demand.occurrence_id,)
        demand = session.get(AnalysisDemand, demand_id)
        assert demand.state == "coalescing"
        assert demand.change_sequence > stopped[0]
        inspection = session.get(DumpInspection, demand.inspection_id)
        next_target = freeze(session, demand, inspection, (pair_id, conflict.id))
        assert next_target.generation == original_target[0] + 1
        assert next_target.resolution_fingerprint != original_target[1]
        assert demand.retry_attempt == 0
        old = session.get(AnalysisDemandTarget, (demand_id, original_target[0]))
        assert (old.generation, old.resolution_fingerprint, old.manifest_sha256) == original_target
        assert session.get(DumpBlob, blob_id).verification_status == "ACCEPTED"
    with demands.begin() as session:
        claims = claim_execution_slots(session, settings, owner_id="next-cycle", now=later)
        assert len(claims) == 1 and claims[0].demand_id == demand_id


def test_run_settlement_preserves_a_new_event_for_the_next_cycle(demands, tmp_path):
    settings = Settings.for_test(tmp_path)
    decision = ComparisonDecision(None, "run_old", "retain", "equivalent", False, ())
    with demands.begin() as session:
        demand, blob = seed(session)
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        freeze(session, demand, inspection)
        demand.state = "running"
        admit_pair(session, *pair_evidence(), origin())
        fanout_next(session, now=NOW + timedelta(seconds=10))
        deadline = demand.not_before
        assert (
            demand.state,
            demand.reason,
            demand.change_sequence > demand.planned_sequence,
        ) == ("running", "symbol_refresh", True)
        settled = settle_demand_after_comparison(
            demand,
            blob,
            decision,
            promoted=False,
            settings=settings,
            now=NOW + timedelta(seconds=11),
        )
        assert (settled.state, demand.reason, settled.not_before) == (
            "coalescing",
            "symbol_refresh",
            deadline,
        )


@pytest.mark.skipif(
    not os.getenv("QAI_DEMAND_REAL"), reason="requires explicit real inspection qualification"
)
def test_real_dump_inspection_retention_and_hash_failure(demands, tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "core_executor": "local",
            "core_command": str(
                ROOT / "target/debug" / ("dmp-core.exe" if os.name == "nt" else "dmp-core")
            ),
        }
    )
    core, store = CoreExecutor(settings), create_object_store(settings)
    dump = ROOT / "fixtures/p0-b01-null-read/generated/null-read.dmp"
    metadata = json.loads(dump.with_name("pe-metadata.json").read_bytes())
    sha, size = hashlib.sha256(dump.read_bytes()).hexdigest(), dump.stat().st_size
    with demands.begin() as session:
        demand, blob = seed(session, sha=sha, size=size)
    store.put_file(blob.object_key, dump, "application/octet-stream")
    result = prepare_inspection(
        core,
        store,
        workspace_id=blob.workspace_id,
        dump_key=blob.object_key,
        dump_sha256=sha,
        dump_size=size,
    )
    with demands.begin() as session:
        registered = register_inspection(session, demand.id, result, now=NOW)
        identity = registered.modules[0]["identity"]
        assert identity["code_id"] == metadata["code_id"].lower()
        assert identity["debug_id"] == metadata["debug_id"].lower()
        references = session.scalars(select(DumpSymbolReference)).all()
        assert len(references) == len(result.modules)
        assert {r.module_index for r in references} == {m["module_index"] for m in result.modules}
        assert all(r.inspection_id == registered.id for r in references)
        assert session.scalar(select(func.count()).select_from(DumpInspection)) == 1
    with pytest.raises(CoreExecutionError, match="verification failed"):
        prepare_inspection(
            core,
            store,
            workspace_id=blob.workspace_id,
            dump_key=blob.object_key,
            dump_sha256="f" * 64,
            dump_size=size,
        )
    assert not list(settings.task_tmp_root.iterdir())
