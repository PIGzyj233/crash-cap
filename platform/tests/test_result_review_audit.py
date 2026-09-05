import hashlib

import pytest
from crashcap_api.errors import ApiError
from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_api.services.result_reviews import validate_review_audit

from .test_current_decisions import SCHEMAS
from .test_result_review_binding import sample


def audit():
    request, _, _, before, after = sample()
    return {
        "schema_version": "result-review-audit-v1",
        "review_id": "rrv_01M1MTSDVM1CBZW5153JC09KHE",
        "occurrence_id": before.occurrence_id,
        "request": request,
        "request_sha256": hashlib.sha256(canonical_bytes(request)).hexdigest(),
        "created_at": "2026-09-04T00:00:00+00:00",
        "current_evidence": before.as_dict(),
        "candidate_evidence": after.as_dict(),
        "provider_basis": [],
    }


def test_review_audit_contract_accepts_bound_evidence():
    validate_review_audit(audit(), SCHEMAS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", "2026-02-30T00:00:00Z"),
        ("created_at", "2026-09-04T00:00:00"),
        ("request_sha256", "f" * 64),
        ("occurrence_id", "occ_other"),
        ("schema_version", "unknown"),
        ("decision", "promote"),
    ],
)
def test_review_audit_rejects_unbound_fields(field, value):
    payload = audit()
    payload[field] = value
    with pytest.raises(ApiError):
        validate_review_audit(payload, SCHEMAS)


@pytest.mark.parametrize("field", ["run_id", "canonical_sha256", "dump_sha256"])
def test_review_audit_rejects_substituted_candidate(field):
    payload = audit()
    payload["candidate_evidence"][field] = "e" * 64
    with pytest.raises(ApiError):
        validate_review_audit(payload, SCHEMAS)


def test_review_audit_requires_all_provider_references():
    payload = audit()
    payload["request"]["basis_reviews"] = [{"review_id": "review", "evidence_sha256": "c" * 64}]
    payload["request_sha256"] = hashlib.sha256(canonical_bytes(payload["request"])).hexdigest()
    with pytest.raises(ApiError):
        validate_review_audit(payload, SCHEMAS)
