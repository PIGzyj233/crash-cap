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
    assert "crashcap_task_intents" in metrics
    assert "crashcap_task_intent_oldest_pending_age_seconds" in metrics
    assert "crashcap_task_executions" in metrics
    assert "crashcap_task_execution_expired_active" in metrics
    assert "crashcap_symbol_projection_backfill_remaining" in metrics
    assert "crashcap_symbol_projection_unresolved_gaps" in metrics
    assert "crashcap_relay_deliveries_total" in metrics
    assert "crashcap_relay_backoff_seconds" in metrics
    assert "crashcap_task_heartbeats_total" in metrics
    assert "crashcap_fenced_stale_writes_total" in metrics
    assert "crashcap_canonical_validation_failures_total" in metrics
    assert "crashcap_generation_orphan_bytes_total" in metrics

    harness.drain()
    refreshed = harness.client.get("/metrics").text
    assert 'crashcap_queue_depth{queue="verify"} 0.0' in refreshed
    assert 'crashcap_analysis_runs{status="PARTIAL"} 1.0' in refreshed
    assert 'crashcap_object_count{kind="dump_blob",state="active"} 1.0' in refreshed
    assert "crashcap_task_claims_total" in refreshed
    assert "crashcap_analysis_transitions_total" in refreshed
    assert "crashcap_current_analysis_promotions_total" in refreshed
    assert "crashcap_canonical_winner_finalizes_total" in refreshed
    assert "crashcap_symbol_projection_writes_total" in refreshed


def test_metrics_expose_committed_pending_intent_without_redis_delivery(
    harness: Phase1Harness,
) -> None:
    harness.settings.task_handoff_mode = "outbox"
    workspace = harness.create_workspace("metrics-pending-intent")
    harness.initialize_dump(workspace["id"], dump_bytes(902))

    metrics = harness.client.get("/metrics").text
    assert 'crashcap_queue_depth{queue="verify"} 0.0' in metrics
    assert 'crashcap_task_intents{state="pending",task_type="verify_upload"} 1.0' in metrics
    assert 'crashcap_task_intent_oldest_pending_age_seconds{task_type="verify_upload"}' in metrics
