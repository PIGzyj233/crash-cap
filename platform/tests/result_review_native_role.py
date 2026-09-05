"""Workspace-local role declaration through the durable native analysis chain."""

import hashlib
import json
import time
from unittest.mock import patch

import pytest
from crashcap_api.app import create_app
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisRun,
    CrashGroup,
    GroupMembership,
    MissingSymbolOccurrence,
    Occurrence,
    ResultReview,
    SymbolProjectionState,
    utcnow,
)
from crashcap_api.services import result_reviews
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient
from sqlalchemy import select

from .result_review_role_browser import role_browser
from .test_frozen_delivery_redis import consume_in_fresh_process


def qualify_native_role(settings, live, occurrences, previous, dispatcher, execute_round):
    sessions = live["sessions"]
    demand_id, occurrence_id = next(iter(occurrences.items()))
    old = previous[demand_id]
    module = next(m for m in old["canonical"]["modules"] if m["selection"]["selected_pair_id"])
    assert module["role"] == "unknown"
    with sessions() as session:
        workspace_id = session.get(Occurrence, occurrence_id).workspace_id
        original_runs = set(session.scalars(select(AnalysisRun.id)))
    app = create_app(settings)
    try:
        with (
            TestClient(app) as client,
            role_browser(settings, live, workspace_id, occurrence_id, old["run_id"]) as browser,
        ):
            if browser:
                browser("declaration")
            else:
                response = client.post(
                    f"/api/v3/workspaces/{workspace_id}/module-roles",
                    json={"identity": module["selection"]["identity"], "role": "owned"},
                )
                assert response.status_code == 201, response.text
            assert relay_once(sessions, dispatcher, settings, owner_id="native-role-relay")
            consume_in_fresh_process(settings, sessions, "ingest", timeout_seconds=90)
            with sessions() as session:
                demand = session.get(AnalysisDemand, demand_id)
                assert demand.reason == "role_change"
                due = demand.not_before
                for other in occurrences:
                    if other != demand_id:
                        assert session.get(AnalysisDemand, other).state == "updated"
            time.sleep(max(0, (due - utcnow()).total_seconds()))
            results = execute_round(utcnow(), "role_change", count=1)
            assert set(results) == {demand_id}
            new = results[demand_id]
            changed = new["canonical"]["modules"][module["module_index"]]
            assert changed["role"] == "owned" and changed["in_app"]
            assert (
                changed["selection"]["selected_pair_id"] == module["selection"]["selected_pair_id"]
            )
            assert new["decision"] == "incomparable", new
            assert new["canonical"]["fingerprints"]["exact"], new["canonical"]["fingerprints"]
            path = f"/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews"
            request = {
                "schema_version": "result-review-request-v1",
                "idempotency_key": "native-role-review",
                "current_run_id": old["run_id"],
                "candidate_run_id": new["run_id"],
                "current_canonical_sha256": old["sha256"],
                "candidate_canonical_sha256": new["sha256"],
                "cause": "role_change",
                "reviewed_by": "Workspace QA",
                "rationale": "Verified this Workspace owns the exact captured fixture module.",
                "basis_reviews": [],
            }
            prepared = result_reviews.prepare_result_review(
                sessions, live["store"], occurrence_id, request, schema_root=settings.schema_root
            )
            real_projection = result_reviews.update_current_projections

            def fail_after_projection(session, occurrence, run, canonical, **kwargs):
                real_projection(session, occurrence, run, canonical, **kwargs)
                assert session.get(GroupMembership, occurrence_id).analysis_run_id == new["run_id"]
                assert (
                    session.get(SymbolProjectionState, occurrence_id).analysis_run_id
                    == new["run_id"]
                )
                raise RuntimeError("injected after strict projections")

            with (
                patch.object(result_reviews, "update_current_projections", fail_after_projection),
                pytest.raises(RuntimeError, match="injected after strict projections"),
                sessions.begin() as session,
            ):
                result_reviews.commit_result_review(session, prepared, settings)
            with sessions() as session:
                assert session.get(Occurrence, occurrence_id).current_run_id == old["run_id"]
                assert session.get(GroupMembership, occurrence_id) is None
                assert (
                    session.get(SymbolProjectionState, occurrence_id).analysis_run_id
                    == old["run_id"]
                )
                assert session.get(ResultReview, prepared.id) is None
                assert (
                    session.scalar(
                        select(CrashGroup).where(CrashGroup.workspace_id == workspace_id)
                    )
                    is None
                )
            if browser:
                browser("review", new["run_id"])
                with sessions() as session:
                    rows = session.scalars(
                        select(ResultReview).where(
                            ResultReview.occurrence_id == occurrence_id,
                            ResultReview.candidate_run_id == new["run_id"],
                        )
                    ).all()
                    assert len(rows) == 1 and rows[0].cause == "role_change"
                    review_id = rows[0].id
                review = client.get(f"{path}/{review_id}")
            else:
                review = client.post(path, json=request)
            assert review.status_code == 200, review.text
            assert review.json()["decision"] == "promote", review.text
            with sessions() as session:
                assert set(session.scalars(select(AnalysisRun.id))) == original_runs | {
                    new["run_id"]
                }
                for key, oid in occurrences.items():
                    expected = new["run_id"] if key == demand_id else previous[key]["run_id"]
                    assert session.get(Occurrence, oid).current_run_id == expected
                    assert session.get(SymbolProjectionState, oid).analysis_run_id == expected
                    missing = session.scalars(
                        select(MissingSymbolOccurrence).where(
                            MissingSymbolOccurrence.occurrence_id == oid
                        )
                    ).all()
                    assert missing and all(row.analysis_run_id == expected for row in missing)
                membership = session.get(GroupMembership, occurrence_id)
                assert membership.analysis_run_id == new["run_id"]
                assert (
                    membership.grouping_evidence_json["algorithm"]
                    == new["canonical"]["fingerprints"]["algorithm"]
                )
                group = session.get(CrashGroup, membership.group_id)
                assert group.fingerprint == new["canonical"]["fingerprints"]["exact"]
                assert group.occurrence_count == 1
            for result in previous.values():
                assert (
                    hashlib.sha256(b"".join(live["store"].stream(result["object_key"]))).hexdigest()
                    == result["sha256"]
                )
            (live["output"] / "native-role-result.json").write_text(
                json.dumps(
                    {
                        "workspace_id": workspace_id,
                        "candidate_run_id": new["run_id"],
                        "review": review.json(),
                        "other_workspace_unchanged": True,
                        "strict_projection_rollback_verified": True,
                        "browser_role_declaration_and_review": browser is not None,
                        "exact_fingerprint": new["canonical"]["fingerprints"]["exact"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        app.state.dispatcher.broker.close()
