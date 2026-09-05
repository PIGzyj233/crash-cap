import hashlib
import json
from dataclasses import replace

import pytest
from crashcap_api.errors import ApiError
from crashcap_api.services.result_reviews import bind_result_review_request

from .test_current_decisions import SCHEMAS, _evidence, _run


def sample():
    old = _run("occ_one", "run_00000000000000000000000001", schema_version="2.0")
    new = _run("occ_one", "run_00000000000000000000000002")
    old.core_version = "previous-engine"
    before, after = _evidence(old.id, old.occurrence_id), _evidence(new.id, new.occurrence_id)
    request = {
        "schema_version": "result-review-request-v1",
        "idempotency_key": "one",
        "current_run_id": old.id,
        "candidate_run_id": new.id,
        "current_canonical_sha256": before.canonical_sha256,
        "candidate_canonical_sha256": after.canonical_sha256,
        "cause": "engine_upgrade",
        "reviewed_by": "QA declaration",
        "rationale": "Reviewed the new report",
        "basis_reviews": [],
    }
    return request, old, new, before, after


def test_review_binding_keeps_original_evidence_and_stable_request():
    request, old, new, before, after = sample()
    bound = bind_result_review_request(request, old, new, before, after, schema_root=SCHEMAS)
    reordered = dict(reversed(list(request.items())))
    assert bound == bind_result_review_request(
        reordered, old, new, before, after, schema_root=SCHEMAS
    )
    assert bound.request_sha256 == hashlib.sha256(bound.request_bytes).hexdigest()
    assert json.loads(bound.request_bytes) == request
    assert after.reason == "symbol_refresh"
    assert new.run_spec["reason"] == "symbol_refresh"


@pytest.mark.parametrize(
    "field",
    [
        "current_run_id",
        "candidate_run_id",
        "current_canonical_sha256",
        "candidate_canonical_sha256",
    ],
)
def test_review_binding_rejects_stale_selection(field):
    request, old, new, before, after = sample()
    request[field] = "c" * 64
    with pytest.raises(ApiError, match="Review the exact current report"):
        bind_result_review_request(request, old, new, before, after, schema_root=SCHEMAS)


@pytest.mark.parametrize(
    "changes",
    [
        {"dump_sha256": "c" * 64},
        {"occurrence_id": "occ_other"},
        {"run_id": "run_other"},
        {"provenance": "insufficient"},
        {"pair_evidence_complete": False},
        {"usable": False},
        {"status": "FAILED"},
    ],
)
def test_review_binding_rejects_wrong_or_incomplete_candidate(changes):
    request, old, new, before, after = sample()
    with pytest.raises(ApiError):
        bind_result_review_request(
            request, old, new, before, replace(after, **changes), schema_root=SCHEMAS
        )


def test_engine_review_cannot_relabel_ordinary_symbol_change():
    request, old, new, before, after = sample()
    old.core_version = new.core_version
    with pytest.raises(ApiError, match="do not have an engine change"):
        bind_result_review_request(request, old, new, before, after, schema_root=SCHEMAS)


def test_provider_review_id_cannot_be_repeated_with_different_hashes():
    request, old, new, before, after = sample()
    request["cause"] = "evidence_correction"
    request["basis_reviews"] = [
        {"review_id": "review_one", "evidence_sha256": value * 64} for value in ("a", "b")
    ]
    with pytest.raises(ApiError, match="only be cited once"):
        bind_result_review_request(request, old, new, before, after, schema_root=SCHEMAS)
