from copy import deepcopy
from pathlib import Path

import pytest
from crashcap_api.contracts import validate_contract
from crashcap_api.errors import ApiError

SCHEMA = (Path(__file__).resolve().parents[2] / "contracts/drafts/qa-symbol-import"
          / "result-review-request-v1.schema.json")


def request():
    return {
        "schema_version": "result-review-request-v1",
        "idempotency_key": "review-one",
        "current_run_id": "run_old",
        "candidate_run_id": "run_new",
        "current_canonical_sha256": "a" * 64,
        "candidate_canonical_sha256": "b" * 64,
        "cause": "engine_upgrade",
        "reviewed_by": "QA reviewer declaration",
        "rationale": "Reviewed the new engine interpretation against the old report",
        "basis_reviews": [],
    }


def test_result_review_accepts_existing_result_binding():
    payload = request()
    validate_contract(payload, SCHEMA, "result review")
    payload["cause"] = "evidence_correction"
    payload["basis_reviews"] = [{"review_id": "review_pair", "evidence_sha256": "c" * 64}]
    validate_contract(payload, SCHEMA, "result review")


@pytest.mark.parametrize("changes", [
    {"cause": "evidence_correction"},
    {"current_canonical_sha256": ""},
    {"candidate_canonical_sha256": "A" * 64},
    {"reviewed_by": "  "},
    {"rationale": "\n\t"},
    {"cause": "force"},
    {"decision": "promote"},
    {"reviewed_at": "client-controlled-time"},
    {"basis_reviews": [{"review_id": "x"}]},
    {"basis_reviews": [{"review_id": "x", "evidence_sha256": "c" * 64}] * 2},
])
def test_result_review_rejects_incomplete_or_client_controlled_evidence(changes):
    payload = deepcopy(request())
    payload.update(changes)
    with pytest.raises(ApiError):
        validate_contract(payload, SCHEMA, "result review")
