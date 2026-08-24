from __future__ import annotations

from crashcap_api.architecture_health import collect_architecture_health
from crashcap_api.models import AnalysisRun

from .conftest import Phase1Harness, dump_bytes


def test_architecture_health_accepts_a_consistent_current_analysis(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("architecture-health-pass")
    completed = harness.upload_dump(workspace["id"], dump_bytes(801))
    assert completed["occurrence_id"]

    with harness.app.state.database.sessions() as session:
        report = collect_architecture_health(session, harness.app.state.store)

    assert report["status"] == "PASS"
    assert report["object_store_checked"] is True
    assert all(
        value == 0
        for name, value in report["counts"].items()
        if name != "double_null_missing_symbol_identities"
    )
    assert report["counts"]["double_null_missing_symbol_identities"] == 1


def test_architecture_health_detects_stale_current_and_missing_object(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("architecture-health-fail")
    completed = harness.upload_dump(workspace["id"], dump_bytes(802))
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    run_id = detail["current_analysis"]["id"]

    with harness.app.state.database.sessions() as session:
        run = session.get(AnalysisRun, run_id)
        assert run is not None and run.result_object_key
        result_object_key = run.result_object_key
        run.status = "FAILED"
        session.commit()
    harness.app.state.store.delete(result_object_key)

    with harness.app.state.database.sessions() as session:
        report = collect_architecture_health(session, harness.app.state.store)

    assert report["status"] == "FAIL"
    assert report["counts"]["current_analysis_violations"] == 1
    assert report["counts"]["missing_canonical_objects"] == 1
    assert report["current_analysis_violations"][0]["reasons"] == [
        "run_not_current_eligible"
    ]
