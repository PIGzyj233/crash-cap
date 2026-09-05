from crashcap_api.architecture_health import collect_architecture_health
from crashcap_api.models import AnalysisRun

from .conftest import dump_bytes
from .occurrence_fixtures import seed_report


def test_current_metadata_and_missing_result_are_reported(harness):
    workspace = harness.create_workspace("health")["id"]
    occurrence = harness.upload_dump(workspace, dump_bytes(5))["occurrence_id"]
    run_id = seed_report(harness, occurrence)
    sessions, store = harness.app.state.database.sessions, harness.app.state.store
    with sessions() as session:
        assert collect_architecture_health(session, store)["status"] == "PASS"
        key = session.get(AnalysisRun, run_id).result_object_key
    store.delete(key)
    with sessions() as session:
        result = collect_architecture_health(session, store)
        assert result["problems"] == [
            {"occurrence_id": occurrence, "reason": "current_object_missing"}
        ]
        session.get(AnalysisRun, run_id).status = "FAILED"
        session.commit()
    with sessions() as session:
        assert collect_architecture_health(session, store)["problems"] == [
            {"occurrence_id": occurrence, "reason": "invalid_current"}
        ]
