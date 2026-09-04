from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from crashcap_api.config import Settings
from crashcap_api.models import AnalysisDemand, AnalysisExecutionSlot, Base
from crashcap_api.services.analysis_demands import fanout_next, register_inspection
from crashcap_api.services.analysis_scheduler import claim_execution_slots, release_planning_slot
from crashcap_api.services.symbol_catalog import admit_pair
from sqlalchemy import func, inspect, select, text

from . import test_analysis_demands as cases
from . import test_demand_restart_api as restart_api
from . import test_manual_demand_restart as manual_cases
from . import test_symbol_catalog_postgres as catalog_tests
from .test_symbol_catalog import origin, pair_evidence

pg = catalog_tests.pg
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
    ),
]


def test_demand_migration_empty_roundtrip_and_retained_evidence_guard(pg):
    engine, sessions, config = pg
    names = {
        "dump_inspections",
        "dump_symbol_references",
        "auto_analysis_demands",
        "analysis_demand_targets",
        "analysis_event_cursors",
    }
    inspector = inspect(engine)
    for name in names:
        model = Base.metadata.tables[name]
        assert {c["name"] for c in inspector.get_columns(name)} == set(model.columns.keys())
        assert {
            i["name"] for i in inspector.get_indexes(name) if not i.get("duplicates_constraint")
        } == {i.name for i in model.indexes}
    command.downgrade(config, "0014_catalog_backfill")
    assert not names.intersection(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    with sessions.begin() as session:
        cases.seed(session)
    with pytest.raises(RuntimeError, match="Retained analysis demand"):
        command.downgrade(config, "0014_catalog_backfill")
    assert names <= set(inspect(engine).get_table_names())


def test_postgres_205_cross_workspace_targets_rollback_and_replay(pg):
    cases.test_paginated_cross_workspace_fanout_rollback_resume_and_identity_filter(pg[1])


def test_postgres_real_inspection_and_retained_private_evidence(pg, tmp_path):
    cases.test_real_dump_inspection_retention_and_hash_failure(pg[1], tmp_path)


def test_postgres_comparison_retry_budget_and_backoff(pg, tmp_path):
    cases.test_comparison_retry_is_finite_exponential_and_preserves_diagnostics(pg[1], tmp_path)


def test_postgres_retry_expiry_and_terminal_outcomes(pg, tmp_path):
    cases.test_retry_refuses_an_expired_dump_and_nonretry_outcomes_settle(pg[1], tmp_path)


def test_postgres_runtime_failures_use_one_finite_budget(pg, tmp_path):
    cases.test_planning_and_execution_failures_share_finite_budget_and_preserve_cause(
        pg[1], tmp_path
    )


def test_postgres_run_settlement_keeps_newer_event(pg, tmp_path):
    cases.test_run_settlement_preserves_a_new_event_for_the_next_cycle(pg[1], tmp_path)


def test_postgres_exhausted_cycle_requires_new_relevant_evidence(pg, tmp_path):
    cases.test_exhausted_cycle_stays_stopped_until_new_relevant_evidence(pg[1], tmp_path)


def test_postgres_repeated_manual_cycles(pg, tmp_path):
    manual_cases.test_repeated_manual_cycles_get_new_targets_but_retries_do_not(pg[1], tmp_path)


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("disabled", "AUTOMATIC_ANALYSIS_DISABLED"),
        ("paused", "AUTOMATIC_ANALYSIS_PAUSED"),
        ("foreign", "DEMAND_NOT_FOUND"),
        ("stale", "STALE_DEMAND"),
        ("running", "DEMAND_NOT_EXHAUSTED"),
        ("expired", "DUMP_UNAVAILABLE"),
    ],
)
def test_postgres_manual_restart_rejections(pg, tmp_path, condition, reason):
    manual_cases.test_restart_rejections_preserve_demand(pg[1], tmp_path, condition, reason)


def test_postgres_restart_api_idempotency(pg, tmp_path):
    restart_api.test_restart_api_replays_original_receipt_and_rejects_conflicting_intent(
        pg[1], tmp_path
    )


def test_postgres_restart_api_audit_rollback(pg, tmp_path, monkeypatch):
    restart_api.test_restart_api_audit_failure_rolls_back_request_and_demand(
        pg[1], tmp_path, monkeypatch
    )


def test_postgres_concurrent_restart_requests(pg, tmp_path):
    from crashcap_api.models import AnalysisDemandRestart, OperationLog

    sessions = pg[1]
    _demand_id, path, body = restart_api.prepare(sessions)
    barrier = threading.Barrier(2)
    with restart_api.client_for(sessions, tmp_path) as client:

        def submit():
            barrier.wait(timeout=10)
            response = client.post(path, json=body)
            assert response.status_code == 202, response.text
            return response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(submit), pool.submit(submit)
            assert first.result(timeout=15) == second.result(timeout=15)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisDemandRestart)) == 1
        assert session.scalar(select(func.count()).select_from(OperationLog)) == 1


def test_postgres_restart_migration_and_history_guard(pg, tmp_path):
    from sqlalchemy.exc import DBAPIError

    engine, sessions, config = pg
    command.downgrade(config, "0022_result_reviews")
    assert "analysis_demand_restarts" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    _demand_id, path, body = restart_api.prepare(sessions)
    with restart_api.client_for(sessions, tmp_path) as client:
        assert client.post(path, json=body).status_code == 202
    for sql in (
        "UPDATE analysis_demand_restarts SET idempotency_key='changed'",
        "DELETE FROM analysis_demand_restarts",
    ):
        with (
            pytest.raises(DBAPIError, match="restart history is immutable"),
            engine.begin() as connection,
        ):
            connection.execute(text(sql))
    with pytest.raises(RuntimeError, match="Retained demand restart history"):
        command.downgrade(config, "0022_result_reviews")


def test_scheduler_migration_matches_models_and_refuses_live_slots(pg, tmp_path):
    engine, sessions, config = pg
    names = {"analysis_scheduler_state", "analysis_execution_slots"}
    inspector = inspect(engine)
    for name in names:
        model = Base.metadata.tables[name]
        assert {column["name"] for column in inspector.get_columns(name)} == set(
            model.columns.keys()
        )
        assert {
            index["name"]
            for index in inspector.get_indexes(name)
            if not index.get("duplicates_constraint")
        } == {index.name for index in model.indexes}
    command.downgrade(config, "0018_current_decisions")
    assert not names.intersection(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    value = Settings.for_test(tmp_path).model_copy(update={"automatic_analysis_enabled": True})
    with sessions.begin() as session:
        cases.seed(session)
        assert claim_execution_slots(session, value, owner_id="planner", now=cases.NOW)
    with pytest.raises(RuntimeError, match="Retained automatic-analysis slots"):
        command.downgrade(config, "0018_current_decisions")


def test_postgres_scheduler_serializes_capacity_across_coordinators(pg, tmp_path):
    _engine, sessions, _config = pg
    value = Settings.for_test(tmp_path).model_copy(
        update={
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 2,
            "automatic_analysis_workspace_limit": 1,
            "automatic_analysis_capacity": 2,
        }
    )
    with sessions.begin() as session:
        for workspace in ("wsp_a", "wsp_b", "wsp_c"):
            cases.seed(session, workspace=workspace)

    ready = threading.Barrier(2)

    def claim(owner):
        ready.wait(timeout=10)
        with sessions.begin() as session:
            return claim_execution_slots(session, value, owner_id=owner, now=cases.NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(claim, "planner-one")
        two = pool.submit(claim, "planner-two")
        claims = (*one.result(timeout=10), *two.result(timeout=10))
    assert len(claims) == 2
    assert len({claim.workspace_id for claim in claims}) == 2
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisExecutionSlot)) == 2


def test_postgres_scheduler_drains_more_than_one_enumeration_page_without_loss(pg, tmp_path):
    _engine, sessions, _config = pg
    value = Settings.for_test(tmp_path).model_copy(
        update={
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 2,
            "automatic_analysis_workspace_limit": 1,
            "automatic_analysis_capacity": 2,
            "automatic_analysis_enumeration_limit": 200,
            "automatic_analysis_release_limit": 50,
        }
    )
    with sessions.begin() as session:
        for number in range(205):
            cases.seed(session, workspace=f"wsp_fair_{number:03}")

    claimed: list[str] = []
    claimed_workspaces: list[str] = []
    while True:
        with sessions.begin() as session:
            page = claim_execution_slots(session, value, owner_id="drain", now=cases.NOW)
            if not page:
                break
            for claim in page:
                demand = session.get(AnalysisDemand, claim.demand_id)
                assert demand is not None
                demand.state = "updated"
                demand.not_before = None
                claimed.append(claim.demand_id)
                claimed_workspaces.append(claim.workspace_id)
                assert release_planning_slot(session, claim)

    assert len(claimed) == len(set(claimed)) == 205
    assert set(claimed_workspaces) == {f"wsp_fair_{number:03}" for number in range(205)}
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisExecutionSlot)) == 0
        assert (
            session.scalar(
                select(func.count())
                .select_from(AnalysisDemand)
                .where(AnalysisDemand.state == "updated")
            )
            == 205
        )


def test_postgres_slow_inspection_renews_waiting_claims_and_fences_dead_planner(
    pg, tmp_path, monkeypatch,
):
    from crashcap_api.services.analysis_demands import DemandError
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner

    class PlannerStopped(BaseException):
        """Simulate process exit before it can release or settle its claims."""

    sessions = pg[1]
    settings = Settings.for_test(tmp_path).model_copy(update={
        "automatic_analysis_enabled": True,
        "automatic_analysis_global_limit": 2,
        "automatic_analysis_workspace_limit": 1,
        "automatic_analysis_capacity": 2,
        # Exercise the supported production minimum, including real wall time.
        "automatic_analysis_planning_lease_seconds": 30,
    })
    with sessions.begin() as session:
        for workspace in ("wsp_slow_a", "wsp_slow_b"):
            cases.seed(session, workspace=workspace)
    planner = AutomaticAnalysisPlanner(settings, sessions, None, None)
    entered, stop = threading.Event(), threading.Event()
    seen = []

    def slow_inspection(claim, now):
        seen.append(claim)
        entered.set()
        assert stop.wait(65), "test did not release the blocked inspection"
        raise PlannerStopped()

    monkeypatch.setattr(planner, "_ensure_inspection", slow_inspection)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(planner.run_once, owner_id="slow-planner")
        try:
            assert entered.wait(10)
            with sessions() as session:
                original = {
                    row.demand_id: (row.claim_token, row.lease_until)
                    for row in session.scalars(select(AnalysisExecutionSlot))
                }
            assert len(original) == 2
            # Cross the original lease boundary while inspection is still blocked.
            delay = max((expiry - datetime.now(UTC)).total_seconds()
                        for _, expiry in original.values()) + 1
            assert not stop.wait(delay)
            with sessions.begin() as session:
                assert claim_execution_slots(
                    session, settings, owner_id="competitor", now=datetime.now(UTC),
                ) == ()
                rows = list(session.scalars(select(AnalysisExecutionSlot)))
                assert len(rows) == 2
                for row in rows:
                    token, expiry = original[row.demand_id]
                    assert row.claim_token == token
                    assert row.lease_until > expiry
            assert len(seen) == 1  # The second claim was renewed before being processed.
        finally:
            stop.set()
        with pytest.raises(PlannerStopped):
            running.result(timeout=10)

    # Stopping the planner stops its heartbeat. Reclaim after the retained lease,
    # then verify that the dead owner's token cannot renew the replacement slot.
    with sessions() as session:
        expiry = max(session.scalars(select(AnalysisExecutionSlot.lease_until)))
    reclaimed_at = expiry + timedelta(seconds=1)
    with sessions.begin() as session:
        replacements = claim_execution_slots(
            session, settings, owner_id="replacement", now=reclaimed_at,
        )
        assert len(replacements) == 2
        assert all(claim.claim_token != original[claim.demand_id][0] for claim in replacements)
    with pytest.raises(DemandError, match="ANALYSIS_SLOT_LOST"):
        planner._heartbeat(seen[0], reclaimed_at)


def test_postgres_exact_workspace_role_history_and_paged_fanout(pg):
    engine, sessions, config = pg
    table = Base.metadata.tables["workspace_module_roles"]
    inspector = inspect(engine)
    assert {column["name"] for column in inspector.get_columns(table.name)} == set(
        table.columns.keys()
    )
    assert {
        index["name"]
        for index in inspector.get_indexes(table.name)
        if not index.get("duplicates_constraint")
    } == {index.name for index in table.indexes}
    cases.test_exact_workspace_role_events_page_all_matching_demands(sessions)
    with pytest.raises(RuntimeError, match="Retained Workspace role"):
        command.downgrade(config, "0015_analysis_demands")


@pytest.mark.parametrize("upload_first", [True, False])
def test_upload_and_index_registration_share_actual_commit_fence(pg, upload_first):
    engine, sessions, _ = pg
    with sessions.begin() as session:
        demand, blob = cases.seed(session)
        evidence = cases.evidence(blob)
    ready, release, started = threading.Event(), threading.Event(), threading.Event()
    pids = {}

    def action(session, upload):
        if upload:
            admit_pair(session, *pair_evidence(), origin())
        else:
            register_inspection(session, demand.id, evidence, now=cases.NOW)

    def first():
        with sessions.begin() as session:
            action(session, upload_first)
            ready.set()
            assert release.wait(10)

    def second():
        assert ready.wait(10)
        with sessions.begin() as session:
            pids["second"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            started.set()
            action(session, not upload_first)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(first), pool.submit(second)
        try:
            assert started.wait(10)
            deadline = time.monotonic() + 5
            with engine.connect() as connection:
                while True:
                    if connection.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pids["second"]}
                    ).scalar_one():
                        break
                    assert time.monotonic() < deadline, "Expected catalog commit fence was not held"
                    time.sleep(0.02)
        finally:
            release.set()
        a.result(timeout=10)
        b.result(timeout=10)
    with sessions.begin() as session:
        current = session.get(AnalysisDemand, demand.id)
        assert current.inspection_id is not None
        assert current.index_revision == (1 if upload_first else 0)
        page = fanout_next(session, now=cases.NOW)
        assert page.caught_up
        assert page.affected == (() if upload_first else (demand.occurrence_id,))
        assert current.change_sequence > current.planned_sequence
