"""DMP runs before and after role declarations against sealed publications."""

import json
import time

from crashcap_api.models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    Occurrence,
    TaskIntent,
    Upload,
    utcnow,
)
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutor


def prepare_runs(client, settings, live, consumers, fixture, drain, *, with_source=False):
    for workspace_id, _, _ in consumers:
        payload = (fixture / "null-read.dmp").read_bytes()
        response = client.post(
            f"/api/v3/workspaces/{workspace_id}/dumps/uploads:init",
            json={"filename": "null-read.dmp", "size": len(payload)},
        )
        assert response.status_code == 201, response.text
        upload_id = response.json()["upload_id"]
        with live["sessions"]() as session:
            key = session.get(Upload, upload_id).object_key
        live["store"].put_bytes(key, payload, "application/octet-stream")
        response = client.post(f"/api/v3/uploads/{upload_id}/complete", json={})
        assert response.status_code == 200, response.text
        drain("verify")
    planner = AutomaticAnalysisPlanner(
        settings, live["sessions"], live["store"], CoreExecutor(settings)
    )

    def execute():
        with live["sessions"]() as session:
            due = max(
                (
                    row.not_before
                    for row in session.query(AnalysisDemand)
                    if row.not_before is not None
                ),
                default=utcnow(),
            )

        time.sleep(max(0, (due - utcnow()).total_seconds()) + 0.05)
        results = {}
        for _ in consumers:
            assert planner.run_once(owner_id="sealed-publication-planner") == 1
            with live["sessions"]() as session:
                slot = session.query(AnalysisExecutionSlot).one()
                run_id = slot.run_id
                queue = (
                    session.query(TaskIntent).filter_by(logical_key=run_id).one().message["queue"]
                )
            drain(queue)
            with live["sessions"]() as session:
                run = session.get(AnalysisRun, run_id)
                assert run.status in {"COMPLETE", "PARTIAL"}, (run.status, run.error_code)
                occurrence = session.get(Occurrence, run.occurrence_id)
                raw = b"".join(live["store"].stream(run.result_object_key))
                results[occurrence.workspace_id] = (run_id, run.result_object_key, raw)
        return results

    before = execute()

    def verify():
        after = execute()
        for workspace_id, build_id, role in consumers:
            old_id, old_key, old_raw = before[workspace_id]
            new_id, _, new_raw = after[workspace_id]
            assert new_id != old_id
            assert b"".join(live["store"].stream(old_key)) == old_raw
            canonical = json.loads(new_raw)
            assert canonical["build_resolution"]["resolved_build_id"] == build_id
            modules = [
                module for module in canonical["modules"] if module["selection"]["selected_pair_id"]
            ]
            assert modules and modules[0]["role"] == role, (role, modules)
            if with_source:
                for raw in (old_raw, new_raw):
                    report = json.loads(raw)
                    contexts = [
                        frame["source_context"]["line"]
                        for thread in report["threads"]
                        for frame in thread["frames"]
                        if frame.get("source_context")
                    ]
                    assert contexts and all(f"WORKSPACE_SOURCE_{role}" in line for line in contexts)
        return {
            workspace: {"before": before[workspace][0], "after": after[workspace][0]}
            for workspace, _, _ in consumers
        }

    return verify
