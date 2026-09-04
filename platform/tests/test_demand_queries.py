import pytest
from crashcap_api.errors import ApiError, register_error_handlers
from crashcap_api.ids import new_id
from crashcap_api.models import AnalysisDemand, DumpBlob, Occurrence
from crashcap_api.services.demand_queries import demand_status
from crashcap_api.services.frozen_runs import adopt_frozen_run

from . import test_frozen_run_adoption as adoption
from .test_analysis_demands import NOW

frozen = adoption.frozen
pg = adoption.pg


@pytest.mark.parametrize("main_app", [False, True])
def test_demand_route_returns_scoped_contract_and_404(frozen, main_app):
    from crashcap_api.app import create_app
    from crashcap_api.routes import session_dependency
    from crashcap_api.routes_demands import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    settings, sessions = frozen
    demand_id, _ = adoption.prepare(sessions, valid_ids=True)
    with sessions() as session:
        demand = session.get(AnalysisDemand, demand_id)
        workspace_id, occurrence_id = demand.workspace_id, demand.occurrence_id

    def provide_session():
        with sessions() as session:
            yield session

    app = create_app(settings) if main_app else FastAPI()
    if not main_app:
        app.state.settings = settings
        register_error_handlers(app)
        app.include_router(router)
    app.dependency_overrides[session_dependency] = provide_session
    with TestClient(app) as client:
        path = f"/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand"
        assert (
            "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/analysis-demand"
            in app.openapi()["paths"]
        )
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "demand_id",
            "occurrence_id",
            "state",
            "generation",
            "retry_attempt",
            "change_sequence",
            "run_id",
            "reason",
            "not_before",
            "current_run_id",
            "withdrawn_basis_pair_ids",
        }
        assert body["demand_id"] == demand_id
        assert body["run_id"] is None
        assert body["withdrawn_basis_pair_ids"] is None
        hidden = client.get(path.replace(workspace_id, "wsp_other"))
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "OCCURRENCE_NOT_FOUND"
        with sessions.begin() as session:
            blob = DumpBlob(
                id=new_id("blob"),
                workspace_id=workspace_id,
                sha256="2" * 64,
                size=19,
                object_key=f"dumps/{workspace_id}/no-demand",
                verification_status="ACCEPTED",
            )
            session.add(blob)
            session.flush()
            without_demand = Occurrence(
                id=new_id("occ"),
                workspace_id=workspace_id,
                dump_blob_id=blob.id,
                uploaded_at=NOW,
                occurred_at=NOW,
                time_source="uploaded",
            )
            session.add(without_demand)
            other_id = without_demand.id
        absent = client.get(path.replace(occurrence_id, other_id))
        assert absent.status_code == 200
        assert absent.json() is None
        with sessions() as session:
            assert demand_status(session, workspace_id=workspace_id, occurrence_id=other_id) is None
            assert not session.new and not session.dirty and not session.deleted


def test_status_binds_exact_attempt_without_using_old_current(frozen):
    settings, sessions = frozen
    demand_id, prepared = adoption.prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        run_id, occurrence_id = created.run.id, created.run.occurrence_id
        workspace_id = session.get(Occurrence, occurrence_id).workspace_id
    with sessions.begin() as session:
        result = demand_status(session, workspace_id=workspace_id, occurrence_id=occurrence_id)
        assert result["run_id"] == run_id
        assert result["state"] == "queued"
        demand = session.get(AnalysisDemand, demand_id)
        demand.retry_attempt += 1
        demand.state = "retry_wait"
    with sessions() as session:
        result = demand_status(session, workspace_id=workspace_id, occurrence_id=occurrence_id)
        assert result["run_id"] is None
        assert result["retry_attempt"] == 1
        assert result["state"] == "retry_wait"
        assert not session.new and not session.dirty and not session.deleted


def test_status_hides_other_workspace_and_preserves_unplanned_demand(frozen):
    _, sessions = frozen
    demand_id, _ = adoption.prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        demand = session.get(AnalysisDemand, demand_id)
        occurrence_id, workspace_id = demand.occurrence_id, demand.workspace_id
        # Existing preparation may own references, so retain it and test the
        # scoped read without manufacturing a cross-Workspace request result.
    with sessions() as session:
        with pytest.raises(ApiError) as error:
            demand_status(session, workspace_id="wsp_other", occurrence_id=occurrence_id)
        assert error.value.status_code == 404
        result = demand_status(session, workspace_id=workspace_id, occurrence_id=occurrence_id)
        assert result["run_id"] is None
        assert result["demand_id"] == demand_id
