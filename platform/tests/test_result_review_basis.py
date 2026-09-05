import hashlib
from dataclasses import replace

import pytest
from crashcap_api.errors import ApiError
from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_api.services.result_reviews import (
    BoundResultReview,
    read_provider_review_basis,
    snapshot_provider_review_basis,
)
from crashcap_api.services.symbol_catalog import review_pair
from crashcap_api.storage import create_object_store

from . import test_symbol_catalog as catalog_tests
from .catalog_fixtures import admit_pair
from .test_current_decisions import _evidence

catalog = catalog_tests.catalog


def test_provider_basis_reads_exact_evidence_and_rechecks_latest_state(catalog):
    db, settings = catalog
    store = create_object_store(settings)
    with db.sessions.begin() as session:
        pair_id = admit_pair(session, *catalog_tests.pair_evidence(), catalog_tests.origin()).id
    payload = canonical_bytes(
        {
            "schema_version": "catalog-provider-review-v1",
            "pair_id": pair_id,
            "expected_version": 1,
            "state": "withdrawn",
            "reason": "incorrect basis",
            "reviewer": "provider declaration",
            "evidence": "verified incorrect pairing",
        }
    )
    sha = hashlib.sha256(payload).hexdigest()
    store.put_bytes("review.json", payload, "application/json")
    with db.sessions.begin() as session:
        review = review_pair(
            session,
            pair_id,
            expected_version=1,
            state="withdrawn",
            reason="incorrect basis",
            evidence_object_key="review.json",
            evidence_sha256=sha,
            idempotency_key="withdraw-one",
        )
        review_id = review.id
    before = _evidence("run_old", "occ_one")
    before = replace(before, modules=(replace(before.modules[0], pair_id=pair_id),))
    after = replace(before, run_id="run_new", modules=(replace(before.modules[0], pair_id=None),))
    request = {"basis_reviews": [{"review_id": review_id, "evidence_sha256": sha}]}
    bound = BoundResultReview(
        canonical_bytes(request), "a" * 64, "run_old", "run_new", "evidence_correction"
    )
    with db.sessions() as session:
        basis = snapshot_provider_review_basis(session, bound, before, after)
    assert read_provider_review_basis(store, basis[0]) == payload
    with db.sessions() as session, pytest.raises(ApiError, match="does not support"):
        snapshot_provider_review_basis(session, bound, before, before)
    store.put_bytes("review.json", payload + b" ", "application/json")
    with pytest.raises(ApiError, match="digest does not match"):
        read_provider_review_basis(store, basis[0])
    store.put_bytes("review.json", payload, "application/json")
    with pytest.raises(ApiError, match="does not match its stored review"):
        read_provider_review_basis(store, replace(basis[0], reason="different reason"))
    with db.sessions.begin() as session:
        review_pair(
            session,
            pair_id,
            expected_version=2,
            state="active",
            reason="restored",
            evidence_object_key="restore.json",
            evidence_sha256="c" * 64,
            idempotency_key="restore-two",
        )
    with db.sessions() as session, pytest.raises(ApiError, match="no longer the current"):
        snapshot_provider_review_basis(session, bound, before, after)


def test_restored_pair_must_be_new_evidence_for_correction(catalog):
    db, _ = catalog
    with db.sessions.begin() as session:
        pair_id = admit_pair(session, *catalog_tests.pair_evidence(), catalog_tests.origin()).id
        review_pair(
            session,
            pair_id,
            expected_version=1,
            state="withdrawn",
            reason="investigate",
            evidence_object_key="withdraw.json",
            evidence_sha256="a" * 64,
            idempotency_key="withdraw",
        )
        review = review_pair(
            session,
            pair_id,
            expected_version=2,
            state="active",
            reason="verified restoration",
            evidence_object_key="restore.json",
            evidence_sha256="b" * 64,
            idempotency_key="restore",
        )
        review_id = review.id
    before = _evidence("run_old", "occ_one")
    before = replace(before, modules=(replace(before.modules[0], pair_id=pair_id),))
    after = replace(before, run_id="run_new")
    bound = BoundResultReview(
        canonical_bytes({"basis_reviews": [{"review_id": review_id, "evidence_sha256": "b" * 64}]}),
        "c" * 64,
        "run_old",
        "run_new",
        "evidence_correction",
    )
    # A restoration unrelated to any change in the reports cannot authorize correction.
    with db.sessions() as session, pytest.raises(ApiError, match="does not support"):
        snapshot_provider_review_basis(session, bound, before, after)
    missing_before = replace(before, modules=(replace(before.modules[0], pair_id=None),))
    with db.sessions() as session:
        basis = snapshot_provider_review_basis(session, bound, missing_before, after)
    assert len(basis) == 1
    assert basis[0].review_id == review_id
