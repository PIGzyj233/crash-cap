from __future__ import annotations

from dataclasses import replace

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import (
    CatalogChange,
    CatalogFile,
    CatalogFileLocation,
    CatalogPair,
    CatalogWatermark,
)
from crashcap_api.services.symbol_catalog import (
    CatalogError,
    candidate_page,
    lock_catalog,
    mark_location_unavailable,
    protects_object,
    review_pair,
)
from sqlalchemy import func, select

from .catalog_fixtures import admit_pair, origin, pair_evidence


def test_fake_validator_cannot_prepare_global_evidence(tmp_path):
    from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor

    from .catalog_fixtures import prepare_catalog_pair

    with pytest.raises(CoreExecutionError) as caught:
        prepare_catalog_pair(
            CoreExecutor(Settings.for_test(tmp_path)),
            None,
            tmp_path / "missing.pe",
            tmp_path / "missing.pdb",
        )
    assert caught.value.code == "CATALOG_REAL_VALIDATOR_REQUIRED"


@pytest.fixture
def catalog(tmp_path):
    settings = Settings.for_test(tmp_path)
    db = Database(settings)
    with db.sessions.begin() as session:
        lock_catalog(session)
    yield db, settings
    db.dispose()


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_conflicting_content_and_all_known_identity_filters(catalog):
    db, _ = catalog
    ids = []
    for pe_sha, pdb_sha, code in [
        ("a" * 64, "b" * 64, "123456789"),
        ("c" * 64, "d" * 64, "123456789"),
        ("e" * 64, "b" * 64, "987654321"),
    ]:
        with db.sessions.begin() as session:
            ids.append(
                admit_pair(session, *pair_evidence(pe_sha, pdb_sha, code), origin(pe_sha)).id
            )
    identity = {"code_id": "123456789", "debug_id": "2" * 32 + "1", "architecture": "x86_64"}
    with db.sessions.begin() as session:
        first = candidate_page(session, identity, limit=1)
        assert len(first.pairs) == 1 and first.next_pair_id is not None
        second = candidate_page(session, identity, after=first.next_pair_id, limit=10)
        assert second.next_pair_id is None
        # Two independent PE contents and two PDB contents share this real identity.
        # All four combinations remain visible; no arrival-order preference is allowed.
        assert len((*first.pairs, *second.pairs)) == 4
        assert set(ids[:2]).issubset(p["pair_id"] for p in (*first.pairs, *second.pairs))
        assert first.revision == second.revision
        debug_only = candidate_page(session, {"debug_id": identity["debug_id"]})
        assert len(debug_only.pairs) == 6


def test_reviews_are_fenced_idempotent_and_reupload_does_not_restore(catalog):
    db, _ = catalog
    args = pair_evidence()
    with db.sessions.begin() as session:
        pair_id = admit_pair(session, *args, origin()).id
    review = dict(
        expected_version=1,
        state="withdrawn",
        reason="provider verified wrong pair",
        evidence_object_key="reviews/report",
        evidence_sha256="e" * 64,
        idempotency_key="review-one",
    )
    with db.sessions.begin() as session:
        recorded = review_pair(session, pair_id, **review)
        review_id = recorded.id
    with db.sessions.begin() as session:
        pair = admit_pair(session, *args, origin("new-upload"))
        assert (pair.state, pair.qualification_version) == ("withdrawn", 2)
        assert review_pair(session, pair_id, **review).id == review_id
    with pytest.raises(CatalogError, match="version changed"), db.sessions.begin() as session:
        review_pair(session, pair_id, **{**review, "state": "active", "idempotency_key": "stale"})
    with db.sessions.begin() as session:
        review_pair(
            session,
            pair_id,
            **{**review, "expected_version": 2, "state": "active", "idempotency_key": "restore"},
        )
        assert review_pair(session, pair_id, **review).id == review_id
        assert session.get(CatalogPair, pair_id).state == "active"
    with pytest.raises(CatalogError, match="different request"), db.sessions.begin() as session:
        review_pair(session, pair_id, **{**review, "reason": "altered"})


@pytest.mark.parametrize("defect", ["payload", "temporary_location"])
def test_failed_admission_rolls_back_every_catalog_effect(catalog, defect):
    db, _ = catalog
    pe, pdb, locations = pair_evidence()
    if defect == "half":
        locations = {"pe": locations["pe"]}
    elif defect == "wrong_debug":
        pdb = replace(pdb, debug_id="3" * 32 + "1")
    elif defect == "payload":
        locations["pdb"] = (replace(locations["pdb"][0], payload_sha256="e" * 64),)
    elif defect == "temporary_location":
        locations["pdb"] = (replace(locations["pdb"][0], object_key="uploads/temporary"),)
    with pytest.raises(CatalogError), db.sessions.begin() as session:
        admit_pair(session, pe, pdb, locations, origin())
        if defect == "origin_rebind":
            admit_pair(
                session, pe, pdb, locations, replace(origin(), details={"source_label": "changed"})
            )
    with db.sessions() as session:
        assert (
            count(session, CatalogPair)
            == count(session, CatalogFile)
            == count(session, CatalogChange)
            == 0
        )
        assert session.get(CatalogWatermark, 1).revision == 0


def test_shared_file_availability_notifies_all_pairs_without_erasing_candidates(catalog):
    db, _ = catalog
    first, second = pair_evidence(), pair_evidence("c" * 64)
    with db.sessions.begin() as session:
        ids = {
            admit_pair(session, *first, origin()).id,
            admit_pair(session, *second, origin("two")).id,
        }
        location = session.scalar(
            select(CatalogFileLocation).where(CatalogFileLocation.file_id == first[1].id)
        )
        location_id = location.id
        start = session.get(CatalogWatermark, 1).revision
    with db.sessions.begin() as session:
        mark_location_unavailable(
            session,
            location_id,
            evidence_object_key="failures/source",
            evidence_sha256="e" * 64,
            reason="verified storage missing",
        )
        page = candidate_page(session, {"debug_id": first[0].debug_id})
        assert {p["pair_id"] for p in page.pairs} == ids
        assert protects_object(session, first[2]["pdb"][0].object_key)
    with db.sessions.begin() as session:
        admit_pair(session, *first, origin("restore"))
    with db.sessions() as session:
        events = list(
            session.scalars(
                select(CatalogChange)
                .where(CatalogChange.revision > start)
                .order_by(CatalogChange.revision)
            )
        )
        assert len(events) == 4 and all(e.affects_selection for e in events)
        assert [set(e.pair_id for e in events[i : i + 2]) for i in (0, 2)] == [ids, ids]
