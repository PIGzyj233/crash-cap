"""The same global pair can have different frozen roles in two Workspaces."""

import hashlib
import json
import time

from crashcap_api.app import create_app
from crashcap_api.models import AnalysisDemand, AnalysisRun, GroupMembership, Occurrence, utcnow
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient
from sqlalchemy import select

from .test_frozen_delivery_redis import consume_in_fresh_process


def qualify_native_dependency(settings, live, occurrences, dispatcher, execute_round):
    sessions, store = live["sessions"], live["store"]
    owned_id, dependency_id = list(occurrences.values())
    demand_id = next(key for key, value in occurrences.items() if value == dependency_id)
    with sessions() as session:
        original_runs = set(session.scalars(select(AnalysisRun.id)))
        owned_run_id = session.get(Occurrence, owned_id).current_run_id
        owned_run = session.get(AnalysisRun, owned_run_id)
        owned_bytes = b"".join(store.stream(owned_run.result_object_key))
        owned_report = json.loads(owned_bytes)
        owned_key = owned_run.result_object_key
        occurrence = session.get(Occurrence, dependency_id)
        workspace_id, old_id = occurrence.workspace_id, occurrence.current_run_id
        old = session.get(AnalysisRun, old_id)
        old_key = old.result_object_key
        old_bytes = b"".join(store.stream(old_key))
        module = next(
            m for m in json.loads(old_bytes)["modules"] if m["selection"]["selected_pair_id"]
        )
    owned_module = owned_report["modules"][module["module_index"]]
    assert owned_module["role"] == "owned" and module["role"] == "unknown"
    assert owned_module["selection"]["selected_pair_id"] == module["selection"]["selected_pair_id"]
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/v3/workspaces/{workspace_id}/module-roles",
                json={
                    "identity": module["selection"]["identity"],
                    "role": "dependency",
                },
            )
            assert response.status_code == 201, response.text
            assert relay_once(sessions, dispatcher, settings, owner_id="dependency-role-relay")
            consume_in_fresh_process(settings, sessions, "ingest", timeout_seconds=90)
            with sessions() as session:
                demand = session.get(AnalysisDemand, demand_id)
                assert demand.reason == "role_change"
                due = demand.not_before
            time.sleep(max(0, (due - utcnow()).total_seconds()))
            results = execute_round(utcnow(), "dependency_role", count=1)
            assert set(results) == {demand_id}
            new = results[demand_id]
            changed = new["canonical"]["modules"][module["module_index"]]
            assert changed["role"] == "dependency" and not changed["in_app"]
            assert (
                changed["selection"]["selected_pair_id"] == module["selection"]["selected_pair_id"]
            )
            assert not new["canonical"]["fingerprints"]["exact"]
            assert new["decision"] == "incomparable"
            review = client.post(
                f"/api/v3/workspaces/{workspace_id}/occurrences/{dependency_id}/result-reviews",
                json={
                    "schema_version": "result-review-request-v1",
                    "idempotency_key": "native-dependency-role-review",
                    "current_run_id": old_id,
                    "candidate_run_id": new["run_id"],
                    "current_canonical_sha256": hashlib.sha256(old_bytes).hexdigest(),
                    "candidate_canonical_sha256": new["sha256"],
                    "cause": "role_change",
                    "reviewed_by": "Workspace dependency QA",
                    "rationale": "This Workspace consumes the exact module as a dependency.",
                    "basis_reviews": [],
                },
            )
            assert review.status_code == 200 and review.json()["decision"] == "promote", review.text
            with sessions() as session:
                assert set(session.scalars(select(AnalysisRun.id))) == original_runs | {
                    new["run_id"]
                }
                assert session.get(Occurrence, owned_id).current_run_id == owned_run_id
                assert session.get(Occurrence, dependency_id).current_run_id == new["run_id"]
                assert session.get(GroupMembership, owned_id).analysis_run_id == owned_run_id
                assert session.get(GroupMembership, dependency_id) is None
            assert b"".join(store.stream(owned_key)) == owned_bytes
            assert b"".join(store.stream(old_key)) == old_bytes
            (live["output"] / "native-dependency-result.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "owned_run_id": owned_run_id,
                        "dependency_run_id": new["run_id"],
                        "pair_id": changed["selection"]["selected_pair_id"],
                        "review": review.json(),
                        "historical_bytes_unchanged": True,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        app.state.dispatcher.broker.close()
