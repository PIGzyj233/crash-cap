from contextlib import contextmanager

import pytest
from crashcap_api.config import Settings
from crashcap_api.errors import register_error_handlers
from crashcap_api.models import AnalysisDemand, AnalysisDemandRestart, OperationLog
from crashcap_api.routes import session_dependency
from crashcap_api.routes_demands import router
from crashcap_api.routes_v2 import router as reader_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from . import test_analysis_demands as cases

demands = cases.demands


@contextmanager
def client_for(sessions, tmp_path, *, enabled=True, paused=False):
    app = FastAPI()
    app.state.settings = Settings.for_test(tmp_path).model_copy(
        update={"automatic_analysis_enabled": enabled, "automatic_analysis_paused": paused}
    )
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(reader_router)

    def provide_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[session_dependency] = provide_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def prepare(sessions):
    with sessions.begin() as session:
        demand, _ = cases.seed(session)
        demand.state = "retry_exhausted"
        demand.reason = "execution_retry_exhausted:manual:CORE_TIMEOUT"
        demand.not_before = None
        return (
            demand.id,
            (
                f"/api/v2/workspaces/{demand.workspace_id}/occurrences/{demand.occurrence_id}"
                "/analysis-demand/restarts"
            ),
            {
                "idempotency_key": "restart-one",
                "expected_generation": demand.generation,
                "expected_sequence": demand.change_sequence,
                "rationale": "Retry after service recovery",
            },
        )


@pytest.mark.parametrize(
    "enabled,paused,expected", [(False, False, False), (True, True, False), (True, False, True)]
)
def test_restart_capability_matches_new_request_gate(demands, tmp_path, enabled, paused, expected):
    with client_for(demands, tmp_path, enabled=enabled, paused=paused) as client:
        response = client.get("/api/v2/capabilities")
        assert response.status_code == 200
        assert ("analysis_demand_restarts" in response.json()["enabled_writes"]) is expected


def test_restart_api_replays_original_receipt_and_rejects_conflicting_intent(demands, tmp_path):
    demand_id, path, body = prepare(demands)
    with client_for(demands, tmp_path) as client:
        accepted = client.post(path, json=body)
        assert accepted.status_code == 202, accepted.text
        original = accepted.json()
        with demands.begin() as session:
            demand = session.get(AnalysisDemand, demand_id)
            assert demand.change_sequence == body["expected_sequence"] + 1
            demand.state = "updated"  # A lost-response retry arrives after later work progressed.
        assert client.post(path, json=body).json() == original
        assert client.post(path, json={**body, "rationale": "Different intent"}).status_code == 409
        assert client.post(path, json={**body, "idempotency_key": "stale-page"}).status_code == 409
        assert client.post(path.replace("wsp_a", "wsp_other"), json=body).status_code == 404
    with demands() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisDemandRestart)) == 1
        assert session.scalar(select(func.count()).select_from(OperationLog)) == 1
        assert session.get(AnalysisDemand, demand_id).state == "updated"


def test_restart_api_audit_failure_rolls_back_request_and_demand(demands, tmp_path, monkeypatch):
    demand_id, path, body = prepare(demands)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected audit storage failure")

    monkeypatch.setattr("crashcap_api.routes_demands.operation_log", fail_audit)
    with client_for(demands, tmp_path) as client:
        assert client.post(path, json=body).status_code == 500
    with demands() as session:
        demand = session.get(AnalysisDemand, demand_id)
        assert (demand.state, demand.change_sequence) == (
            "retry_exhausted",
            body["expected_sequence"],
        )
        assert session.scalar(select(func.count()).select_from(AnalysisDemandRestart)) == 0
        assert session.scalar(select(func.count()).select_from(OperationLog)) == 0
