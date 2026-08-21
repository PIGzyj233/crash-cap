from __future__ import annotations

from .conftest import Phase1Harness, dump_bytes


def test_metrics_expose_queue_state_duration_failures_and_object_growth(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("metrics")
    harness.initialize_dump(workspace["id"], dump_bytes(901))

    response = harness.client.get("/metrics")
    assert response.status_code == 200
    metrics = response.text

    assert 'crashcap_queue_depth{queue="verify"} 1.0' in metrics
    assert 'crashcap_uploads{status="VERIFYING"} 1.0' in metrics
    assert "crashcap_analysis_state_oldest_age_seconds" in metrics
    assert "crashcap_analysis_duration_seconds" in metrics
    assert 'crashcap_object_count{kind="upload_staging",state="all"} 1.0' in metrics
    assert "crashcap_object_bytes" in metrics
    assert "crashcap_metrics_refresh_failures_total" in metrics

    harness.drain()
    refreshed = harness.client.get("/metrics").text
    assert 'crashcap_queue_depth{queue="verify"} 0.0' in refreshed
    assert 'crashcap_analysis_runs{status="PARTIAL"} 1.0' in refreshed
    assert 'crashcap_object_count{kind="dump_blob",state="active"} 1.0' in refreshed
