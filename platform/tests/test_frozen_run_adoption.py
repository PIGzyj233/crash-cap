from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisDemandTarget,
    AnalysisExecutionSlot,
    AnalysisRun,
    DumpBlob,
    DumpInspection,
    Occurrence,
    TaskExecution,
    TaskIntent,
    Workspace,
    utcnow,
)
from crashcap_api.queueing import MemoryTaskDispatcher
from crashcap_api.services.analysis_demands import (
    DemandError,
    ensure_demand,
    inspection_evidence,
    register_inspection,
)
from crashcap_api.services.analysis_recovery import recover_expired_frozen_runs
from crashcap_api.services.analysis_scheduler import bind_execution_slot, claim_execution_slots
from crashcap_api.services.frozen_runs import FrozenRunPreparation, adopt_frozen_run
from crashcap_api.services.workspace_builds import prepare_build_policy, snapshot_workspace_builds
from crashcap_api.services.workspace_policies import (
    declare_workspace_module_role,
    prepare_workspace_policies,
    snapshot_workspace_policies,
)
from crashcap_api.storage import create_object_store
from crashcap_api.task_handoff import claim_is_current, claim_task
from crashcap_api.task_reconciliation import reconcile_task_intents
from crashcap_worker import processor as processor_module
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from crashcap_worker.frozen_core import FrozenCoreOutput
from crashcap_worker.processor import WorkerProcessor
from sqlalchemy import func, select

from . import test_symbol_catalog_postgres as catalog_tests
from .test_analysis_demands import NOW, manifest, seed

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = ROOT / "contracts/drafts/qa-symbol-import"
pg = catalog_tests.pg


@pytest.fixture
def frozen(tmp_path, request):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "core_executor": "local",
            "frozen_core_enabled": True,
            "frozen_analysis_enabled": True,
            "frozen_symbolicator_url": "http://symbolicator.test:3021",
            "frozen_pair_source_root": "http://pair-source.test:8080",
            "frozen_symbolicator_image_digest": "sha256:" + "f" * 64,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
            "frozen_public_sources": [],
        }
    )
    db = None
    if os.getenv("QAI_CATALOG_DATABASE_URL"):
        _, sessions, _ = request.getfixturevalue("pg")
    else:
        db = Database(settings)
        sessions = db.sessions
    try:
        yield settings, sessions
    finally:
        if db is not None:
            db.dispose()


def prepare(sessions, *, valid_ids=False):
    with sessions.begin() as session:
        if valid_ids:
            workspace_id = new_id("wsp")
            blob = DumpBlob(
                id=new_id("blob"),
                workspace_id=workspace_id,
                sha256="1" * 64,
                size=19,
                object_key=f"dumps/{workspace_id}/worker-test",
                verification_status="ACCEPTED",
            )
            occurrence = Occurrence(
                id=new_id("occ"),
                workspace_id=workspace_id,
                dump_blob_id=blob.id,
                uploaded_at=NOW,
                occurred_at=NOW,
                time_source="uploaded",
            )
            session.add(Workspace(id=workspace_id, name=workspace_id))
            session.flush()
            session.add(blob)
            session.flush()
            session.add(occurrence)
            session.flush()
            demand = ensure_demand(session, occurrence.id, now=NOW)
        else:
            demand, blob = seed(session)
        blob.capture_profile = "light-crash"
        inspect = {
            "schema_version": "0.1",
            "dump": {"size": blob.size, "kind": "user_minidump", "timestamp": None},
            "process": {"architecture": "x86_64"},
            "modules": [{"code_id": "123456789", "debug_id": "2" * 32 + "1"}],
        }
        inspect_bytes = canonical_bytes(inspect)
        inspection = register_inspection(
            session,
            demand.id,
            inspection_evidence(
                inspect_bytes,
                dump_sha256=blob.sha256,
                dump_size=blob.size,
                inspector_version="inspect-v0.1",
                inspector_provenance="unit-frozen-adoption",
                object_key=f"inspect/{blob.id}/unit-frozen-adoption",
            ),
            now=NOW,
        )
        assert inspection is not None
        selected_manifest = manifest(session, inspection)
        builds = snapshot_workspace_builds(
            session,
            demand.workspace_id,
            [row["identity"] for row in inspection.modules],
            reported_build_id=None,
        )
        policies = snapshot_workspace_policies(session, builds)
    build_policy = prepare_build_policy(builds, {}, schema_root=DRAFTS)
    policy_snapshots, source_locations = prepare_workspace_policies(
        policies,
        build_policy,
        inspect,
        public_sources=[],
        schema_root=DRAFTS,
    )
    return demand.id, FrozenRunPreparation(
        expected_sequence=demand.change_sequence,
        cause="initial",
        manifest=selected_manifest,
        manifest_bytes=canonical_bytes(selected_manifest),
        manifest_object_key="frozen/manifests/one.json",
        inspect_bytes=inspect_bytes,
        build_snapshot=builds,
        policy_snapshot=policies,
        policy_snapshots=policy_snapshots,
        source_bundle_locations=source_locations,
    )


def test_adoption_commits_target_run_and_strict_intent_atomically(frozen):
    settings, sessions = frozen
    demand_id, prepared = prepare(sessions)
    with sessions.begin() as session:
        created = adopt_frozen_run(
            session, settings, demand_id, prepared, now=NOW, request_id="req_frozen"
        )
        run_id, attempt_id = created.run.id, created.intent.attempt_id
        assert created.created is True
    with sessions() as session:
        demand = session.get(AnalysisDemand, demand_id)
        run = session.get(AnalysisRun, run_id)
        intent = session.get(TaskIntent, attempt_id)
        target = session.get(AnalysisDemandTarget, (demand_id, 1))
        assert demand is not None and demand.state == "queued" and demand.generation == 1
        assert run is not None
        assert target is not None and target.context_sha256 == run.run_spec["context_sha256"]
        assert (run.schema_version, run.assembly_mode, run.status) == (
            "1.1",
            "core-final",
            "QUEUED",
        )
        assert (run.demand_id, run.demand_generation, run.retry_attempt) == (demand_id, 1, 0)
        assert run.run_spec["result_facts"]["dump"]["capture_profile"] == "light-crash"
        assert intent is not None and intent.state == "pending"
        assert intent.message == {
            "schema_version": "1.2",
            "task_type": "analyze_frozen_run",
            "run_id": run_id,
            "attempt_id": attempt_id,
            "queue": "dump-small",
            "request_id": "req_frozen",
        }

    with sessions.begin() as session:
        replay = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        assert replay.created is False
        assert replay.run.id == run_id and replay.intent.attempt_id == attempt_id
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 1


@pytest.mark.parametrize("defect", [None, "retained", "fresh", "missing"])
def test_retry_uses_exact_retained_manifest_and_rejects_corruption(frozen, defect):
    settings, sessions = frozen
    demand_id, prepared = prepare(sessions)
    with sessions.begin() as session:
        original = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        original_ref = dict(original.run.run_spec["resolution_manifest"])
        original.run.status = "TIMEOUT"
        demand = session.get(AnalysisDemand, demand_id)
        demand.state = "retry_wait"
        demand.retry_attempt = 1
        demand.not_before = NOW
    fresh = json.loads(prepared.manifest_bytes)
    fresh["modules"][0]["candidate_evidence"]["object_key"] = "unit/new-evidence"
    retry = replace(
        prepared,
        manifest=fresh,
        manifest_bytes=canonical_bytes(fresh) + (b" " if defect == "fresh" else b""),
        manifest_object_key="frozen/manifests/two.json",
        retained_manifest_bytes=(
            None if defect == "missing"
            else prepared.manifest_bytes + (b" " if defect == "retained" else b"")
        ),
    )
    if defect:
        with (
            pytest.raises(DemandError, match="MANIFEST_STORED_BYTES_MISMATCH"),
            sessions.begin() as session,
        ):
            adopt_frozen_run(session, settings, demand_id, retry, now=NOW)
    else:
        with sessions.begin() as session:
            created = adopt_frozen_run(session, settings, demand_id, retry, now=NOW)
            assert created.created
            assert created.run.run_spec["resolution_manifest"] == original_ref
            assert created.run.retry_attempt == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == (1 if defect else 2)
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == (1 if defect else 2)
        target = session.get(AnalysisDemandTarget, (demand_id, 1))
        assert target.manifest_object_key == original_ref["object_key"]
        assert target.manifest_sha256 == original_ref["sha256"]
        assert session.get(AnalysisDemand, demand_id).generation == 1


def test_adoption_rejects_workspace_policy_changed_after_preparation(frozen):
    settings, sessions = frozen
    demand_id, prepared = prepare(sessions)
    with sessions.begin() as session:
        declare_workspace_module_role(
            session,
            "wsp_a",
            {"code_id": "123456789", "debug_id": "2" * 32 + "1", "architecture": "x86_64"},
            "owned",
            now=NOW,
        )
    with sessions.begin() as session, pytest.raises(DemandError, match="STALE_WORKSPACE_POLICY"):
        adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 0
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 0
        assert session.get(AnalysisDemand, demand_id).generation == 0


def test_frozen_reconciliation_reuses_receipt_after_execution_lease_expires(frozen):
    settings, sessions = frozen
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        message = dict(created.intent.message)
        created.intent.state = "published"
        created.run.status = "ANALYZING"
        claim = claim_task(
            session,
            message,
            settings.schema_root,
            receipt_mode="strict",
            lease_seconds=300,
            now=utcnow(),
        )
        assert claim.acquired
    with sessions.begin() as session:
        assert reconcile_task_intents(session, settings)["selected_count"] == 0
        execution = session.get(TaskExecution, ("analyze_frozen_run", message["run_id"]))
        assert execution is not None
        execution.lease_until = NOW - timedelta(seconds=1)
    with sessions.begin() as session:
        preview = reconcile_task_intents(session, settings)
        assert preview["selected_count"] == 1
        assert preview["items"][0]["task_type"] == "analyze_frozen_run"
        result = reconcile_task_intents(session, settings, apply=True)
        assert result["reopened_count"] == 1
    with sessions() as session:
        intent = session.get(TaskIntent, message["attempt_id"])
        run = session.get(AnalysisRun, message["run_id"])
        assert intent is not None and intent.state == "pending"
        assert intent.message == message
        assert run is not None and run.status == "ANALYZING"
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 1


@pytest.mark.parametrize("budget,expected", [(1, "retry_exhausted"), (3, "retry_wait")])
@pytest.mark.parametrize("paused", [False, True])
def test_automatic_expired_execution_settles_budget_and_fences_old_worker(
    frozen, budget, expected, paused
):
    settings, sessions = frozen
    settings = settings.model_copy(
        update={
            "automatic_analysis_enabled": True,
            "analysis_max_attempts": budget,
        }
    )
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="planner", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        message = dict(created.intent.message)
        claim = claim_task(
            session, message, settings.schema_root, receipt_mode="strict", lease_seconds=30, now=NOW
        )
        created.run.status = "ANALYZING"
    settings = settings.model_copy(update={"automatic_analysis_paused": paused})
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW) == 0
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=31)) == 1
    with sessions.begin() as session:
        assert not claim_is_current(session, claim, lock=True)
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=32)) == 0
        run = session.get(AnalysisRun, message["run_id"])
        demand = session.get(AnalysisDemand, demand_id)
        assert run is not None and run.status == "FAILED"
        assert run.error_code == "FROZEN_EXECUTION_LEASE_EXPIRED"
        assert demand is not None and demand.state == expected
        assert session.get(AnalysisExecutionSlot, demand_id) is None
        if paused:
            retry_attempt = demand.retry_attempt
            assert claim_execution_slots(
                session, settings, owner_id="paused", now=NOW + timedelta(seconds=600)
            ) == ()
            assert demand.retry_attempt == retry_attempt
    if paused:
        with sessions.begin() as session:
            claims = claim_execution_slots(
                session, settings.model_copy(update={"automatic_analysis_paused": False}),
                owner_id="resumed", now=NOW + timedelta(seconds=600),
            )
            assert len(claims) == (1 if expected == "retry_wait" else 0)


@pytest.mark.skipif(not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL")
def test_abrupt_process_exit_is_recovered_by_a_fresh_process(frozen, tmp_path):
    settings, sessions = frozen
    settings = settings.model_copy(update={"automatic_analysis_enabled": True})
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="planner", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        message = dict(created.intent.message)
        database_url = session.get_bind().url.render_as_string(hide_password=False)
    payload = json.dumps(
        {
            "url": database_url,
            "message": message,
            "schema_root": str(settings.schema_root),
            "temp": str(tmp_path),
        }
    )
    setup = """
import json, sys, os, time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from crashcap_api.models import AnalysisRun, utcnow
from crashcap_api.task_handoff import claim_task
from crashcap_api.config import Settings
from crashcap_api.services.analysis_recovery import recover_expired_frozen_runs
p = json.load(sys.stdin)
engine = create_engine(p["url"])
sessions = sessionmaker(engine, expire_on_commit=False, autoflush=False)
"""
    crash = subprocess.run(  # noqa: S603 - fixed interpreter/code; data is stdin JSON
        [
            sys.executable,
            "-c",
            setup
            + """
with sessions.begin() as session:
    claim = claim_task(session, p["message"], Path(p["schema_root"]),
                       receipt_mode="strict", lease_seconds=1, now=utcnow())
    assert claim.acquired
    session.get(AnalysisRun, p["message"]["run_id"]).status = "ANALYZING"
os._exit(17)
""",
        ],
        input=payload,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert crash.returncode == 17
    replacement = subprocess.run(  # noqa: S603 - fixed interpreter/code; data is stdin JSON
        [
            sys.executable,
            "-c",
            setup
            + """
time.sleep(1.2)
settings = Settings.for_test(Path(p["temp"])).model_copy(
    update={"automatic_analysis_enabled": True})
with sessions.begin() as session:
    count = recover_expired_frozen_runs(session, settings, now=utcnow())
print(count)
engine.dispose()
""",
        ],
        input=payload,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert replacement.returncode == 0, replacement.stderr
    assert replacement.stdout.strip() == "1"
    with sessions() as session:
        run = session.get(AnalysisRun, message["run_id"])
        demand = session.get(AnalysisDemand, demand_id)
        execution = session.get(TaskExecution, ("analyze_frozen_run", message["run_id"]))
        assert run is not None and run.status == "FAILED"
        assert execution is not None and execution.outcome == "failed"
        assert demand is not None and demand.state == "retry_wait"
        assert session.get(AnalysisExecutionSlot, demand_id) is None


@pytest.mark.parametrize("budget,expected", [(1, "retry_exhausted"), (3, "retry_wait")])
def test_unclaimed_published_delivery_uses_bounded_retry(frozen, budget, expected):
    settings, sessions = frozen
    settings = settings.model_copy(
        update={
            "automatic_analysis_enabled": True,
            "analysis_max_attempts": budget,
            "automatic_analysis_delivery_timeout_seconds": 30,
        }
    )
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="planner", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        run_id, attempt_id = created.run.id, created.intent.attempt_id
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=31)) == 0
        intent = session.get(TaskIntent, attempt_id)
        intent.state = "published"
        intent.published_at = NOW
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=29)) == 0
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=31)) == 1
    with sessions.begin() as session:
        assert recover_expired_frozen_runs(session, settings, now=NOW + timedelta(seconds=32)) == 0
        run = session.get(AnalysisRun, run_id)
        demand = session.get(AnalysisDemand, demand_id)
        assert run is not None and run.status in {"FAILED", "TIMEOUT"}
        assert run.error_code == "FROZEN_DELIVERY_UNCLAIMED_TIMEOUT"
        assert demand is not None and demand.state == expected
        assert session.get(AnalysisExecutionSlot, demand_id) is None


def test_retry_adoption_honors_due_time_and_exhaustion(frozen):
    settings, sessions = frozen
    demand_id, prepared = prepare(sessions)
    with sessions.begin() as session:
        first = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        first_run_id = first.run.id
        demand = session.get(AnalysisDemand, demand_id)
        assert demand is not None
        demand.state = "retry_wait"
        demand.reason = "retry:business_transient_loss"
        demand.retry_attempt = 1
        demand.not_before = NOW + timedelta(seconds=30)
    with sessions.begin() as session, pytest.raises(DemandError, match="RETRY_NOT_DUE"):
        adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
    with sessions.begin() as session:
        retry = adopt_frozen_run(
            session,
            settings,
            demand_id,
            prepared,
            now=NOW + timedelta(seconds=30),
        )
        assert retry.created is True and retry.run.id != first_run_id
        assert retry.run.retry_attempt == 1
        retry_run_id = retry.run.id
        demand = session.get(AnalysisDemand, demand_id)
        assert demand is not None
        demand.state = "retry_exhausted"
    with sessions.begin() as session:
        replay = adopt_frozen_run(
            session,
            settings,
            demand_id,
            prepared,
            now=NOW + timedelta(seconds=60),
        )
        assert replay.created is False and replay.run.id == retry_run_id


@pytest.mark.parametrize("promotion_enabled", [False, True])
@pytest.mark.parametrize("paused", [False, True])
def test_frozen_worker_claims_stages_and_persists_candidate_without_current(
    frozen, tmp_path, monkeypatch, promotion_enabled, paused
):
    settings, sessions = frozen
    settings = settings.model_copy(
        update={
            "automatic_analysis_enabled": True,
            "evidence_promotion_enabled": promotion_enabled,
        }
    )
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="planner", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        message = dict(created.intent.message)
        blob_key = created.run.run_spec["dump"]["object_key"]
        inspect_key = created.run.run_spec["inspect"]["object_key"]
        manifest_key = created.run.run_spec["resolution_manifest"]["object_key"]
        occurrence_id = created.run.occurrence_id
    store = create_object_store(settings)
    store.put_bytes(blob_key, b"x" * 19, "application/octet-stream")
    store.put_bytes(inspect_key, prepared.inspect_bytes, "application/json")
    store.put_bytes(manifest_key, prepared.manifest_bytes, "application/json")
    canonical = {
        "quality": {"score": 1, "warnings": []},
        "build_resolution": {
            "resolved_build_id": None,
            "resolution_method": "unresolved",
            "evidence": {"candidate_build_ids": []},
        },
        "modules": [],
    }

    class StubFrozenExecutor:
        def __init__(self, _settings):
            pass

        def execute(self, task_dir, assignment, pairs, **_kwargs):
            assert assignment.run_id == message["run_id"]
            assert pairs == {}
            path = task_dir / "canonical-stub.json"
            payload = canonical_bytes(canonical)
            path.write_bytes(payload)
            return FrozenCoreOutput(canonical, payload, path, {}, {})

    monkeypatch.setattr(processor_module, "FrozenCoreExecutor", StubFrozenExecutor)
    monkeypatch.setattr(processor_module, "_upsert_summary", lambda *_args: None)
    if promotion_enabled:
        from .test_current_decisions import _evidence

        monkeypatch.setattr(
            processor_module,
            "build_native_evidence",
            lambda run, *_args, **_kwargs: _evidence(run.id, run.occurrence_id),
        )
        monkeypatch.setattr(
            processor_module, "update_symbol_health_for_promotion", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr(processor_module, "_update_group_projection", lambda *_args: None)
    worker = WorkerProcessor(
        settings.model_copy(update={"automatic_analysis_paused": paused}),
        sessions,
        store,
        MemoryTaskDispatcher(settings),
    )
    worker.analyze_frozen_run(message)
    with sessions() as session:
        run = session.get(AnalysisRun, message["run_id"])
        demand = session.get(AnalysisDemand, demand_id)
        occurrence = session.get(Occurrence, occurrence_id)
        assert run is not None and run.status == "COMPLETE"
        assert run.result_object_key is not None
        assert b"".join(store.stream(run.result_object_key)) == canonical_bytes(canonical)
        assert run.winner_attempt_id == message["attempt_id"]
        assert run.winner_generation == 1
        assert demand is not None
        assert demand.state == ("updated" if promotion_enabled else "needs_review")
        assert occurrence is not None
        assert occurrence.current_run_id == (run.id if promotion_enabled else None)
        assert session.get(AnalysisExecutionSlot, demand_id) is None


def test_automatic_planner_composes_snapshot_objects_run_intent_and_slot(frozen, tmp_path):
    settings, sessions = frozen
    validator = tmp_path / "core-validator.exe"
    validator.write_bytes(b"qualified planner identity")
    settings = settings.model_copy(
        update={
            "automatic_analysis_enabled": True,
            "core_command": str(validator),
        }
    )
    demand_id, prepared = prepare(sessions, valid_ids=True)
    store = create_object_store(settings)
    with sessions() as session:
        demand = session.get(AnalysisDemand, demand_id)
        assert demand is not None and demand.inspection_id is not None
        inspection = session.get(DumpInspection, demand.inspection_id)
        assert inspection is not None
        inspect_key = inspection.object_key
    store.put_bytes(inspect_key, prepared.inspect_bytes, "application/json")

    planner = AutomaticAnalysisPlanner(
        settings,
        sessions,
        store,
        CoreExecutor(settings),
    )
    assert planner.run_once(owner_id="automatic-test", now=NOW) == 1
    with sessions() as session:
        demand = session.get(AnalysisDemand, demand_id)
        assert demand is not None and demand.state == "queued"
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.demand_id == demand_id))
        assert run is not None and run.status == "QUEUED"
        assert run.schema_version == "1.1" and run.assembly_mode == "core-final"
        slot = session.get(AnalysisExecutionSlot, demand_id)
        assert slot is not None
        assert (slot.state, slot.run_id, slot.lease_until) == ("executing", run.id, None)
        intent = session.scalar(
            select(TaskIntent).where(
                TaskIntent.task_type == "analyze_frozen_run",
                TaskIntent.logical_key == run.id,
            )
        )
        assert intent is not None
        assert b"".join(store.stream(run.run_spec["resolution_manifest"]["object_key"]))


def test_frozen_execution_failure_releases_slot_and_enters_finite_retry(frozen, monkeypatch):
    settings, sessions = frozen
    settings = settings.model_copy(update={"automatic_analysis_enabled": True})
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="planner", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        message = dict(created.intent.message)
        blob_key = created.run.run_spec["dump"]["object_key"]
        inspect_key = created.run.run_spec["inspect"]["object_key"]
        manifest_key = created.run.run_spec["resolution_manifest"]["object_key"]
    store = create_object_store(settings)
    store.put_bytes(blob_key, b"x" * 19, "application/octet-stream")
    store.put_bytes(inspect_key, prepared.inspect_bytes, "application/json")
    store.put_bytes(manifest_key, prepared.manifest_bytes, "application/json")

    class FailingFrozenExecutor:
        def __init__(self, _settings):
            pass

        def execute(self, *_args, **_kwargs):
            raise CoreExecutionError("CORE_STAGE_TIMEOUT", "qualified timeout")

    monkeypatch.setattr(processor_module, "FrozenCoreExecutor", FailingFrozenExecutor)
    worker = WorkerProcessor(
        settings,
        sessions,
        store,
        MemoryTaskDispatcher(settings),
    )
    with pytest.raises(CoreExecutionError, match="qualified timeout"):
        worker.analyze_frozen_run(message)
    with sessions() as session:
        run = session.get(AnalysisRun, message["run_id"])
        demand = session.get(AnalysisDemand, demand_id)
        assert run is not None and run.status == "TIMEOUT"
        assert demand is not None
        assert (demand.state, demand.retry_attempt, demand.reason) == (
            "retry_wait",
            1,
            "execution_retry:initial:CORE_STAGE_TIMEOUT",
        )
        assert session.get(AnalysisExecutionSlot, demand_id) is None
