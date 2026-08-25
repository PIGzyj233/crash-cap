from __future__ import annotations

import json
from datetime import timedelta

from crashcap_api.models import AnalysisRun, Occurrence, TaskExecution, utcnow
from crashcap_api.object_keys import analysis_generation_key
from crashcap_api.services.analysis_lifecycle import transition_analysis
from crashcap_api.task_handoff import claim_task
from crashcap_worker.core_runner import CoreOutput

from .conftest import Phase1Harness, dump_bytes


def test_reclaimed_generation_discards_late_success_and_failure(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("analysis-generation-fencing")
    upload = harness.initialize_dump(workspace["id"], dump_bytes(901))
    dispatcher = harness.app.state.dispatcher

    assert dispatcher.drain(limit=1) == 1  # verify creates the Run and analysis delivery
    message = dispatcher.snapshot()[0]
    dispatcher.messages.clear()
    now = utcnow()

    with harness.app.state.database.sessions() as session:
        first = claim_task(
            session,
            message,
            harness.settings.schema_root,
            owner_id="worker-first",
            lease_seconds=60,
            now=now,
        )
        run = session.get(AnalysisRun, message["run_id"])
        assert run is not None
        transition_analysis(run, "VALIDATING")
        spec = dict(run.run_spec)
        session.commit()

    with harness.app.state.database.sessions() as session:
        execution = session.get(
            TaskExecution,
            {"task_type": first.task_type, "logical_key": first.logical_key},
        )
        assert execution is not None
        execution.lease_until = now - timedelta(seconds=1)
        session.commit()

    with harness.app.state.database.sessions() as session:
        second = claim_task(
            session,
            message,
            harness.settings.schema_root,
            owner_id="worker-second",
            lease_seconds=60,
            now=now,
        )
        session.commit()
    assert second.acquired is True
    assert second.generation == first.generation + 1

    assert (
        harness.app.state.processor._fail_run(
            message,
            first,
            "CORE_FAILED",
            "late failure",
        )
        is False
    )
    output = harness.app.state.processor._execute_analysis(message, spec, second, 60)
    assert output is not None
    stale_canonical = json.loads(json.dumps(output.canonical))
    stale_canonical["quality"]["warnings"].append(
        {"code": "other", "message": "stale generation marker"}
    )
    stale_output = CoreOutput(
        inspect=output.inspect,
        canonical=stale_canonical,
        raw={},
    )
    assert harness.app.state.processor._persist_analysis(message, stale_output, first) is False

    stale_key = analysis_generation_key(
        workspace["id"],
        spec["occurrence_id"],
        spec["run_id"],
        first.attempt_id,
        first.generation,
        "canonical.json",
    )
    assert harness.app.state.store.head(stale_key).size > 0
    assert harness.app.state.processor._persist_analysis(message, output, second) is True
    assert (
        harness.app.state.processor._fail_run(
            message,
            first,
            "TIMEOUT",
            "later stale failure",
        )
        is False
    )

    metrics = harness.client.get("/metrics").text
    assert (
        'crashcap_fenced_stale_writes_total{stage="claim_check",task_type="analyze_occurrence"}'
        in metrics
    )
    assert 'crashcap_generation_orphan_objects_total{kind="canonical"}' in metrics
    assert 'crashcap_generation_orphan_bytes_total{kind="canonical"}' in metrics

    with harness.app.state.database.sessions() as session:
        run = session.get(AnalysisRun, message["run_id"])
        occurrence = session.get(Occurrence, spec["occurrence_id"])
        execution = session.get(
            TaskExecution,
            {"task_type": second.task_type, "logical_key": second.logical_key},
        )
        assert run is not None and occurrence is not None and execution is not None
        assert run.status in {"COMPLETE", "PARTIAL"}
        assert run.winner_attempt_id == second.attempt_id
        assert run.winner_generation == second.generation
        assert run.result_object_key is not None and "/g/2-" in run.result_object_key
        assert run.result_object_key != stale_key
        assert occurrence.current_run_id == run.id
        assert execution.outcome == "succeeded"
        assert upload["upload_id"]

    stale_document = json.loads(b"".join(harness.app.state.store.stream(stale_key)))
    public_document = harness.client.get(
        f"/api/v1/occurrences/{spec['occurrence_id']}/analysis"
    ).json()
    assert stale_document["quality"]["warnings"][-1]["message"] == "stale generation marker"
    assert public_document == output.canonical
