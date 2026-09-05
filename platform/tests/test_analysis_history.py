from copy import deepcopy

from crashcap_api.models import AnalysisRun, Occurrence

from .conftest import dump_bytes
from .occurrence_fixtures import seed_report


def test_history_pages_old_and_unfinished_runs_without_inventing_decisions(harness):
    workspace = harness.create_workspace("history")
    other = harness.create_workspace("other-history")
    upload = harness.upload_dump(workspace["id"], dump_bytes(42))
    occurrence_id = upload["occurrence_id"]
    seed_report(harness, occurrence_id)
    with harness.app.state.database.sessions.begin() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        old = session.get(AnalysisRun, occurrence.current_run_id)
        assert old is not None and old.result_object_key
        old_id = old.id
        values = {
            column.name: deepcopy(getattr(old, column.name))
            for column in AnalysisRun.__table__.columns
        }
        values.update(
            id="run_zz_history",
            idempotency_key="f" * 64,
            status="QUEUED",
            result_object_key=None,
            started_at=None,
            finished_at=None,
        )
        session.add(AnalysisRun(**values))
    url = f"/api/v3/workspaces/{workspace['id']}/occurrences/{occurrence_id}/analysis-history"
    response = harness.client.get(url, params={"limit": 1})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["current_run_id"] == old_id
    assert first["items"][0]["id"] == "run_zz_history"
    assert first["items"][0]["report_available"] is False
    assert first["items"][0]["selection"] is None
    assert first["items"][0]["finished_at"] is None
    second = harness.client.get(url, params={"limit": 1, "cursor": first["next_cursor"]}).json()
    assert second["next_cursor"] is None
    assert second["items"][0]["id"] == old_id
    assert second["items"][0]["report_available"] is True
    assert second["items"][0]["selection"] is None
    assert second["items"][0]["finished_at"].endswith("Z")
    assert "result_object_key" not in second["items"][0]
    assert harness.client.get(url.replace(workspace["id"], other["id"])).status_code == 404
    assert harness.client.get(url, params={"limit": 201}).status_code == 422
