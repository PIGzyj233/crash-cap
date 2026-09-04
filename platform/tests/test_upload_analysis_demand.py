import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisRun,
    Occurrence,
    OccurrenceSubmission,
    Upload,
)
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient
from sqlalchemy import select

from .conftest import Phase1Harness, dump_bytes


@pytest.mark.parametrize("automatic", [False, True])
def test_accepted_duplicate_dump_uses_one_demand_when_automatic_enabled(
    tmp_path, automatic, database_url=None
):
    settings = Settings.model_validate(
        {
            **Settings.for_test(tmp_path).model_dump(),
            **({"database_url": database_url, "create_schema": False} if database_url else {}),
            "core_executor": "local",
            "frozen_core_enabled": True,
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "automatic_analysis_enabled": automatic,
            "frozen_symbolicator_url": "http://symbolicator.test:3021",
            "frozen_pair_source_root": "http://pair-source.test:8080",
            "frozen_symbolicator_image_digest": "sha256:" + "f" * 64,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
        }
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert (
            "submission_labels" in client.get("/api/v2/capabilities").json()["enabled_writes"]
        ) == automatic
        harness = Phase1Harness(client=client, app=app, settings=settings)
        workspace_id = harness.create_workspace("upload-demand")["id"]
        for index in range(3 if automatic else 1):
            if index == 0:
                upload = harness.initialize_dump(workspace_id, dump_bytes(42))
            else:
                payload = dump_bytes(42)
                response = client.post(
                    f"/api/v2/workspaces/{workspace_id}/uploads",
                    json={
                        "filename": "qa.dmp",
                        "size": len(payload),
                        "label": f"version-{index}",
                        "batch": f"batch-{index}",
                        "source": "manual-browser",
                    },
                )
                assert response.status_code == 201, response.text
                upload = response.json()
                with app.state.database.sessions() as session:
                    row = session.get(Upload, upload["upload_id"])
                    app.state.store.put_bytes(row.object_key, payload, "application/octet-stream")
                    assert session.get(OccurrenceSubmission, row.id).occurrence_id is None
                response = client.post(f"/api/v1/uploads/{upload['upload_id']}/complete", json={})
                assert response.status_code == 200, response.text
            while relay_once(
                app.state.database.sessions, app.state.dispatcher, settings, owner_id="upload-relay"
            ):
                pass
            harness.drain()
            response = client.get(f"/api/v1/uploads/{upload['upload_id']}")
            assert response.json()["verification_status"] == "ACCEPTED"
            with app.state.database.sessions() as session:
                occurrences = list(session.scalars(select(Occurrence)))
                demands = list(session.scalars(select(AnalysisDemand)))
                runs = list(session.scalars(select(AnalysisRun)))
                assert len(occurrences) == 1
                if automatic:
                    assert len(demands) == 1 and not runs
                    assert demands[0].occurrence_id == occurrences[0].id
                    assert demands[0].state == "preparing"
                    if index == 0:
                        identity = (demands[0].id, demands[0].generation)
                    else:
                        assert (demands[0].id, demands[0].generation) == identity
                else:
                    assert not demands and len(runs) == 1
        if automatic:
            occurrence_id = occurrences[0].id
            assert occurrences[0].reported_build_id is None
            path = f"/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/submissions"
            page = client.get(path, params={"limit": 2}).json()
            assert [row["label"] for row in page["items"]] == [None, "version-1"]
            tail = client.get(path, params={"cursor": page["next_cursor"], "limit": 2}).json()
            assert tail["next_cursor"] is None
            assert [(row["label"], row["batch"], row["source"]) for row in tail["items"]] == [
                ("version-2", "batch-2", "manual-browser")
            ]
            before = client.get(path).json()
            assert all(
                row["submitted_at"].endswith("Z") and row["verified_at"].endswith("Z")
                for row in before["items"]
            )
            browse = f"/api/v1/workspaces/{workspace_id}/occurrences"
            matching = client.get(
                browse, params={"test_label": "version-1", "test_batch": "batch-1"}
            )
            assert matching.status_code == 200, matching.text
            assert [row["id"] for row in matching.json()["items"]] == [occurrence_id]
            crossed = client.get(
                browse, params={"test_label": "version-1", "test_batch": "batch-2"}
            )
            assert crossed.json()["items"] == []
            assert client.get(browse, params={"version": "version-1"}).json()["items"] == []
            assert (
                client.post(f"/api/v1/uploads/{upload['upload_id']}/complete", json={}).status_code
                == 200
            )
            assert client.get(path).json() == before
            other = harness.create_workspace("other-submission-scope")["id"]
            assert client.get(path.replace(workspace_id, other)).status_code == 404
        else:
            response = client.post(
                f"/api/v2/workspaces/{workspace_id}/uploads",
                json={"filename": "qa.dmp", "size": 32, "source": "manual-browser"},
            )
            assert response.status_code == 409
