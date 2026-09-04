"""Result review assertions over reports produced by the real late-pair lane."""

import pytest
from crashcap_api.errors import ApiError
from crashcap_api.models import AnalysisDemand, CurrentDecision, Occurrence, ResultReview
from crashcap_api.services.result_reviews import commit_result_review, prepare_result_review
from sqlalchemy import select


def review_withdrawn_candidates(client, live, settings, occurrences, before, candidates, provider):
    sessions = live["sessions"]
    saved = []
    for demand_id, occurrence_id in occurrences.items():
        old, new = before[demand_id], candidates[demand_id]
        with sessions() as session:
            workspace_id = session.get(Occurrence, occurrence_id).workspace_id
        path = f"/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews"
        status = client.get(path.replace("/result-reviews", "/analysis-demand"))
        assert status.status_code == 200, status.text
        assert status.json()["current_run_id"] == old["run_id"]
        assert provider["pair_id"] in status.json()["withdrawn_basis_pair_ids"]
        request = {
            "schema_version": "result-review-request-v1",
            "idempotency_key": f"native-correction-{demand_id}",
            "current_run_id": old["run_id"],
            "candidate_run_id": new["run_id"],
            "current_canonical_sha256": old["sha256"],
            "candidate_canonical_sha256": new["sha256"],
            "cause": "evidence_correction",
            "reviewed_by": "Isolated qualification reviewer",
            "rationale": "Adopt recomputed report after withdrawal of its former symbol basis.",
            "basis_reviews": [
                {"review_id": provider["id"], "evidence_sha256": provider["evidence_sha256"]}
            ],
        }
        if not saved:
            prepared = prepare_result_review(
                sessions, live["store"], occurrence_id, request, schema_root=settings.schema_root
            )
            pair_path = f"/api/v2/symbol-catalog/pairs/{provider['pair_id']}/reviews"
            restored = client.post(
                pair_path,
                json={
                    "expected_version": provider["qualification_version"],
                    "state": "active",
                    "reason": "Concurrent restoration qualification",
                    "reviewer": "Fixture provider",
                    "evidence": "Change current provider decision after result review preparation.",
                    "idempotency_key": "prepared-review-restoration",
                },
            )
            assert restored.status_code == 200, restored.text
            with (
                pytest.raises(ApiError, match="no longer the current"),
                sessions.begin() as session,
            ):
                commit_result_review(session, prepared, settings=settings)
            with sessions() as session:
                assert session.get(Occurrence, occurrence_id).current_run_id == old["run_id"]
                assert session.get(ResultReview, prepared.id) is None
                assert session.get(AnalysisDemand, demand_id).state == "needs_review"
            withdrawn = client.post(
                pair_path,
                json={
                    "expected_version": restored.json()["qualification_version"],
                    "state": "withdrawn",
                    "reason": "Resume isolated withdrawal qualification",
                    "reviewer": "Fixture provider",
                    "evidence": "New review supersedes the stale result review authorization.",
                    "idempotency_key": "prepared-review-withdraw-again",
                },
            )
            assert withdrawn.status_code == 200, withdrawn.text
            provider = withdrawn.json()
            request["basis_reviews"] = [
                {"review_id": provider["id"], "evidence_sha256": provider["evidence_sha256"]}
            ]
        response = client.post(path, json=request)
        assert response.status_code == 200, response.text
        row = response.json()
        assert row["decision"] == "correct", row
        replay = client.post(path, json=request)
        assert replay.status_code == 200 and replay.json() == row
        evidence = client.get(f"{path}/{row['id']}/evidence")
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["request"] == request
        with sessions() as session:
            assert session.get(Occurrence, occurrence_id).current_run_id == new["run_id"]
            assert session.get(CurrentDecision, new["run_id"]).decision == "incomparable"
            assert session.get(AnalysisDemand, demand_id).state == "updated"
            reviews = session.scalars(
                select(ResultReview).where(ResultReview.occurrence_id == occurrence_id)
            ).all()
            assert len(reviews) == 1 and reviews[0].id == row["id"]
        saved.append(row)
    return saved
