from __future__ import annotations

from datetime import UTC, datetime, timedelta

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import AnalysisDemand, AnalysisExecutionSlot
from crashcap_api.services.analysis_scheduler import (
    claim_execution_slots,
    heartbeat_planning_slot,
    release_planning_slot,
)
from sqlalchemy import func, select

from .test_analysis_demands import seed

NOW = datetime(2026, 9, 4, tzinfo=UTC)


def settings(tmp_path, **updates):
    return Settings.for_test(tmp_path).model_copy(
        update={
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 2,
            "automatic_analysis_workspace_limit": 1,
            "automatic_analysis_capacity": 2,
            "automatic_analysis_enumeration_limit": 200,
            "automatic_analysis_release_limit": 50,
            "automatic_analysis_planning_lease_seconds": 60,
            **updates,
        }
    )


def test_default_is_disabled_and_initial_limits_are_explicit(tmp_path):
    value = Settings.for_test(tmp_path)
    assert value.automatic_analysis_enabled is False
    assert (
        value.automatic_analysis_workspace_limit,
        value.automatic_analysis_global_limit,
        value.automatic_analysis_capacity,
        value.automatic_analysis_enumeration_limit,
        value.automatic_analysis_release_limit,
    ) == (1, 2, 2, 200, 50)


def test_fair_workspace_round_robin_respects_global_and_workspace_capacity(tmp_path):
    value = settings(tmp_path)
    database = Database(value)
    try:
        with database.sessions.begin() as session:
            for workspace in ("wsp_a", "wsp_b", "wsp_c"):
                for number in range(2):
                    seed(session, number, workspace)
            # Priority is local to a Workspace; its newer manual item wins that lane.
            manual = session.scalar(
                select(AnalysisDemand).where(
                    AnalysisDemand.workspace_id == "wsp_a",
                    AnalysisDemand.occurrence_id == "occ_wsp_a_0001",
                )
            )
            assert manual is not None
            manual.reason = "manual"
            older = session.scalar(
                select(AnalysisDemand).where(
                    AnalysisDemand.workspace_id == "wsp_a",
                    AnalysisDemand.occurrence_id == "occ_wsp_a_0000",
                )
            )
            assert older is not None
            older.reason = "symbol_refresh"

        with database.sessions.begin() as session:
            first = claim_execution_slots(session, value, owner_id="planner-a", now=NOW)
            assert [item.workspace_id for item in first] == ["wsp_a", "wsp_b"]
            assert first[0].demand_id == manual.id
            assert session.scalar(select(func.count()).select_from(AnalysisExecutionSlot)) == 2
        with database.sessions.begin() as session:
            assert not claim_execution_slots(session, value, owner_id="planner-b", now=NOW)
            for item in first:
                assert release_planning_slot(session, item)
        with database.sessions.begin() as session:
            second = claim_execution_slots(session, value, owner_id="planner-b", now=NOW)
            assert [item.workspace_id for item in second] == ["wsp_c", "wsp_a"]
            assert len({item.workspace_id for item in second}) == 2
    finally:
        database.dispose()


def test_small_enumeration_pages_rotate_without_dropping_later_workspaces(tmp_path):
    value = settings(
        tmp_path,
        automatic_analysis_global_limit=1,
        automatic_analysis_capacity=1,
        automatic_analysis_enumeration_limit=2,
    )
    database = Database(value)
    try:
        with database.sessions.begin() as session:
            for workspace in ("wsp_a", "wsp_b", "wsp_c", "wsp_d", "wsp_e"):
                seed(session, 0, workspace)
        observed = []
        for _ in range(5):
            with database.sessions.begin() as session:
                claims = claim_execution_slots(session, value, owner_id="planner", now=NOW)
                assert len(claims) == 1
                observed.append(claims[0].workspace_id)
                assert release_planning_slot(session, claims[0])
        assert observed == ["wsp_a", "wsp_b", "wsp_c", "wsp_d", "wsp_e"]
    finally:
        database.dispose()


def test_expired_planning_lease_is_reclaimed_with_a_new_fence(tmp_path):
    value = settings(
        tmp_path,
        automatic_analysis_global_limit=1,
        automatic_analysis_capacity=1,
    )
    database = Database(value)
    try:
        with database.sessions.begin() as session:
            seed(session, 0)
            first = claim_execution_slots(session, value, owner_id="dead", now=NOW)[0]
        with database.sessions.begin() as session:
            second = claim_execution_slots(
                session,
                value,
                owner_id="replacement",
                now=NOW + timedelta(seconds=61),
            )[0]
            assert second.demand_id == first.demand_id
            assert second.claim_token != first.claim_token
            assert not release_planning_slot(session, first)
            assert release_planning_slot(session, second)
    finally:
        database.dispose()


def test_planning_heartbeat_extends_only_the_current_unexpired_fence(tmp_path):
    value = settings(
        tmp_path,
        automatic_analysis_global_limit=1,
        automatic_analysis_capacity=1,
    )
    database = Database(value)
    try:
        with database.sessions.begin() as session:
            seed(session, 0)
            claim = claim_execution_slots(session, value, owner_id="planner", now=NOW)[0]
        with database.sessions.begin() as session:
            assert heartbeat_planning_slot(
                session,
                value,
                claim,
                now=NOW + timedelta(seconds=30),
            )
            slot = session.get(AnalysisExecutionSlot, claim.demand_id)
            assert slot is not None
            assert slot.lease_until is not None
            assert slot.lease_until.replace(tzinfo=UTC) == NOW + timedelta(seconds=90)
        with database.sessions.begin() as session:
            assert not heartbeat_planning_slot(
                session,
                value,
                claim,
                now=NOW + timedelta(seconds=91),
            )
    finally:
        database.dispose()
def test_planning_heartbeat_renews_waiting_claims_and_stops(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner

    value = settings(tmp_path).model_copy(
        update={"automatic_analysis_planning_lease_seconds": 0.03}
    )
    planner = AutomaticAnalysisPlanner(value, None, None, None)
    claims = tuple(SimpleNamespace(demand_id=name) for name in ("first", "waiting"))
    seen, workers = set(), []
    ready = threading.Event()

    def heartbeat(claim, _now):
        seen.add(claim.demand_id)
        workers.append(threading.current_thread())
        if len(seen) == 2:
            ready.set()

    monkeypatch.setattr(planner, "_heartbeat", heartbeat)
    # No per-claim processing runs here: both the active and waiting claim must
    # be renewed independently while the main planner is blocked in I/O.
    with planner._renew_planning_claims(claims, None):
        assert ready.wait(1), seen
    assert seen == {"first", "waiting"}
    assert all(not worker.is_alive() for worker in workers)


def test_planning_heartbeat_does_not_revive_lost_claim(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    from crashcap_api.services.analysis_demands import DemandError
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner

    value = settings(tmp_path).model_copy(
        update={"automatic_analysis_planning_lease_seconds": 0.03}
    )
    planner = AutomaticAnalysisPlanner(value, None, None, None)
    claims = tuple(SimpleNamespace(demand_id=name) for name in ("lost", "live"))
    counts = {"lost": 0, "live": 0}
    ready = threading.Event()

    def heartbeat(claim, _now):
        counts[claim.demand_id] += 1
        if claim.demand_id == "lost":
            raise DemandError("ANALYSIS_SLOT_LOST")
        if counts["live"] >= 2:
            ready.set()

    monkeypatch.setattr(planner, "_heartbeat", heartbeat)
    with planner._renew_planning_claims(claims, None) as finished:
        assert ready.wait(1), counts
        assert finished["lost"].is_set()
    assert counts["lost"] == 1
    assert counts["live"] >= 2
