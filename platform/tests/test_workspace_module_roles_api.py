from __future__ import annotations

import os

from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import AnalysisEventCursor, TaskExecution, TaskIntent, WorkspaceModuleRole
from fastapi.testclient import TestClient

IDENTITY = {
    "code_id": "123456789",
    "debug_id": "222222222222222222222222222222221",
    "architecture": "x86_64",
}


def settings(tmp_path, *, enabled=False):
    url = os.getenv("QAI_CATALOG_DATABASE_URL")
    values = (
        Settings.for_test(tmp_path, url).model_dump()
        if url
        else Settings.for_test(tmp_path).model_dump()
    )
    values["workspace_module_roles_enabled"] = enabled
    return Settings.model_validate(values)


def test_workspace_role_api_is_default_off(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        workspace = client.post("/api/v1/workspaces", json={"name": "role-off"}).json()
        response = client.post(
            f"/api/v2/workspaces/{workspace['id']}/module-roles",
            json={"identity": IDENTITY, "role": "owned"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "QUALIFICATION_PENDING"
        assert client.get("/api/v2/capabilities").json()["enabled_writes"] == []


def test_workspace_role_api_atomically_stages_idempotent_fanout(tmp_path):
    app = create_app(settings(tmp_path, enabled=True))
    with TestClient(app) as client:
        workspace = client.post("/api/v1/workspaces", json={"name": "role-on"}).json()
        url = f"/api/v2/workspaces/{workspace['id']}/module-roles"
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
        assert client.get("/api/v2/capabilities").json()["enabled_writes"] == [
            "workspace_module_roles"
        ]
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
