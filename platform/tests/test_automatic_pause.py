from contextlib import contextmanager

import pytest
from crashcap_api.models import AnalysisDemand, AnalysisExecutionSlot
from crashcap_api.routes_demands import get_analysis_demand
from crashcap_api.services.analysis_scheduler import claim_execution_slots
from crashcap_worker import automatic_main
from sqlalchemy import func, select

from . import test_frozen_run_adoption as adoption
from .test_analysis_demands import seed
from .test_analysis_scheduler import NOW, settings

frozen = adoption.frozen


def test_paused_scheduler_preserves_demand_and_resumes(tmp_path):
    from crashcap_api.db import Database

    value = settings(tmp_path, automatic_analysis_paused=True)
    database = Database(value)
    try:
        with database.sessions.begin() as session:
            seed(session, 0, "wsp_pause")
        with database.sessions.begin() as session:
            demand = session.scalar(select(AnalysisDemand))
            before = (demand.state, demand.generation, demand.retry_attempt, demand.not_before)
            assert claim_execution_slots(session, value, owner_id="paused", now=NOW) == ()
            assert session.scalar(select(func.count()).select_from(AnalysisExecutionSlot)) == 0
            session.refresh(demand)
            after = (demand.state, demand.generation, demand.retry_attempt, demand.not_before)
            assert after == before
        with database.sessions.begin() as session:
            claims = claim_execution_slots(
                session, value.model_copy(update={"automatic_analysis_paused": False}),
                owner_id="resumed", now=NOW,
            )
            assert len(claims) == 1
    finally:
        database.dispose()


@pytest.mark.parametrize(
    "state", ["preparing", "coalescing", "retry_wait", "updated", "needs_review"]
)
def test_paused_status_is_read_only_and_retains_terminal_result(frozen, state):
    from .test_frozen_run_adoption import prepare

    value, sessions = frozen
    demand_id, _ = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        demand = session.get(AnalysisDemand, demand_id)
        demand.state = state
        workspace_id, occurrence_id = demand.workspace_id, demand.occurrence_id
    with sessions() as session:
        response = get_analysis_demand(
            workspace_id, occurrence_id, session,
            value.model_copy(update={"automatic_analysis_paused": True}),
        )
        expected = "paused" if state in {"preparing", "coalescing", "retry_wait"} else state
        assert response.state == expected
        assert session.get(AnalysisDemand, demand_id).state == state
        assert not session.dirty


def test_resident_pause_keeps_recovery_but_stops_fanout_and_planning(tmp_path, monkeypatch):
    value = settings(tmp_path, automatic_analysis_paused=True)
    calls = []

    class StopLoop(BaseException):
        pass

    class FakeDatabase:
        def __init__(self, _settings):
            self.sessions = self

        @contextmanager
        def begin(self):
            yield object()

        def dispose(self):
            calls.append("disposed")

    def forbidden(*args, **kwargs):
        pytest.fail("pause must not enumerate or plan new work")

    def stop(_seconds):
        raise StopLoop()

    monkeypatch.setattr(automatic_main, "Settings", lambda: value)
    monkeypatch.setattr(automatic_main, "Database", FakeDatabase)
    monkeypatch.setattr(automatic_main, "create_object_store", lambda _: object())
    monkeypatch.setattr(automatic_main, "CoreExecutor", lambda _: object())
    monkeypatch.setattr(automatic_main.AutomaticAnalysisPlanner, "run_once", forbidden)
    monkeypatch.setattr(automatic_main, "fanout_next", forbidden)
    monkeypatch.setattr(
        automatic_main, "recover_expired_frozen_runs", lambda *a, **k: calls.append("recovery")
    )
    monkeypatch.setattr(automatic_main.time, "sleep", stop)
    with pytest.raises(StopLoop):
        automatic_main.run()
    assert calls == ["recovery", "disposed"]
