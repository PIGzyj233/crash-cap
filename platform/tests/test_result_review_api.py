"""HTTP validation boundaries; native transaction coverage is in catalog_source_real."""

import pytest

from .test_result_review_binding import sample

PATH = "/api/v2/workspaces/wsp_missing/occurrences/occ_missing/result-reviews"


def test_review_default_disabled_and_openapi(harness):
    body, *_ = sample()
    response = harness.client.post(PATH, json=body)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUALIFICATION_PENDING"
    assert (
        "result_reviews" not in harness.client.get("/api/v2/capabilities").json()["enabled_writes"]
    )
    schema = harness.client.get("/openapi.json").json()
    route = schema["paths"][
        "/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews"
    ]
    assert set(route) == {"get", "post"}
    assert route["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ResultReviewRequest"
    )
    assert schema["components"]["schemas"]["ResultReviewRequest"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"cause": "evidence_correction"},  # No provider references.
        {"reviewed_by": "   "},
        {"rationale": "\n"},
        {"current_canonical_sha256": "A" * 64},
        {"current_canonical_sha256": "a" * 64 + "\n"},
        {"candidate_run_id": 123},
        {"decision": "promote"},
        {"basis_reviews": [{"review_id": "review", "evidence_sha256": "c" * 64}] * 2},
    ],
)
def test_review_invalid_request_rejected_before_target_lookup(harness, changes):
    harness.app.state.settings = harness.settings.model_copy(
        update={"result_reviews_enabled": True}
    )
    body, *_ = sample()
    response = harness.client.post(PATH, json={**body, **changes})
    assert response.status_code == 422, response.text
