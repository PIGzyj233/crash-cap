from __future__ import annotations

import os

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import AnalysisEventCursor, TaskExecution, TaskIntent, WorkspaceModuleRole

from . import test_symbol_catalog_postgres as catalog_tests
from .auth_support import AuthenticatedClient as TestClient

pg = catalog_tests.pg

IDENTITY = {
    "code_id": "123456789",
    "debug_id": "222222222222222222222222222222221",
    "architecture": "x86_64",
}


@pytest.fixture
def role_settings(tmp_path, request):
    if os.getenv("QAI_CATALOG_DATABASE_URL"):
        engine, _, _ = request.getfixturevalue("pg")
        return Settings.for_test(tmp_path).model_copy(
            update={
                "database_url": engine.url.render_as_string(hide_password=False),
                "create_schema": False,
            }
        )
    return Settings.for_test(tmp_path)


def test_workspace_role_api_is_enabled(role_settings):
    with TestClient(create_app(role_settings)) as client:
        workspace = client.post("/api/v3/workspaces", json={"name": "role-off"}).json()
        response = client.post(
            f"/api/v3/workspaces/{workspace['id']}/module-roles",
            json={"identity": IDENTITY, "role": "owned"},
        )
        assert response.status_code == 201
        assert response.json()["role"] == "owned"
        assert (
            "workspace_module_roles" in client.get("/api/v3/capabilities").json()["enabled_writes"]
        )


def test_workspace_role_api_atomically_stages_idempotent_fanout(role_settings):
    app = create_app(role_settings)
    with TestClient(app) as client:
        workspace = client.post("/api/v3/workspaces", json={"name": "role-on"}).json()
        url = f"/api/v3/workspaces/{workspace['id']}/module-roles"
        first = client.post(url, json={"identity": IDENTITY, "role": "owned"})
        assert first.status_code == 201
        result = first.json()
        assert result == {
            "workspace_id": workspace["id"],
            "version": 1,
            "identity": IDENTITY,
            "role": "owned",
            "changed": True,
            "fanout_attempt_id": result["fanout_attempt_id"],
        }
        assert result["fanout_attempt_id"].startswith("wra_")
        second = client.post(url, json={"identity": IDENTITY, "role": "owned"})
        assert second.status_code == 200
        assert second.json()["changed"] is False
        assert second.json()["fanout_attempt_id"] is None
        assert (
            "workspace_module_roles" in client.get("/api/v3/capabilities").json()["enabled_writes"]
        )
        with app.state.database.sessions() as session:
            declarations = session.query(WorkspaceModuleRole).all()
            intents = session.query(TaskIntent).all()
            assert len(declarations) == len(intents) == 1
            assert intents[0].state == "pending"
            message = intents[0].message
        app.state.processor.dispatch_workspace_role(message)
        with app.state.database.sessions() as session:
            execution = session.get(
                TaskExecution,
                ("dispatch_workspace_role", f"{workspace['id']}:role:1"),
            )
            assert execution is not None and execution.outcome == "succeeded"
            cursor = session.get(AnalysisEventCursor, f"workspace-role-v1:{workspace['id']}")
            assert cursor.revision == 1 and cursor.after_occurrence_id is None
