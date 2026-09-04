from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import (
    ArtifactBlob,
    ArtifactBlobPayloadLegacyCopy,
    CatalogChange,
    CatalogFile,
    CatalogFileLocation,
    CatalogPair,
    CatalogPairOrigin,
    CatalogWatermark,
    Workspace,
)
from crashcap_api.services.artifact_payload_backfill import cleanup_artifact_blob_raw_payloads
from crashcap_api.services.symbol_catalog import (
    CatalogError,
    FileEvidence,
    LocationEvidence,
    OriginEvidence,
    admit_pair,
    candidate_page,
    lock_catalog,
    mark_location_unavailable,
    protects_object,
    review_pair,
)
from sqlalchemy import func, select


def test_fake_validator_cannot_prepare_global_evidence(tmp_path):
    from crashcap_worker.catalog_validation import prepare_catalog_pair
    from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor

    with pytest.raises(CoreExecutionError) as caught:
        prepare_catalog_pair(
            CoreExecutor(Settings.for_test(tmp_path)),
            None,
            tmp_path / "missing.pe",
            tmp_path / "missing.pdb",
        )
    assert caught.value.code == "CATALOG_REAL_VALIDATOR_REQUIRED"


def pair_evidence(pe_sha="a" * 64, pdb_sha="b" * 64, code="123456789"):
    def file(kind, sha, arch, code_id):
        return FileEvidence(
            kind,
            sha,
            17,
            code_id,
            "2" * 32 + "1",
            arch,
            "unit-control-not-byte-proof",
            "proof/files",
            "f" * 64,
        )

    pe, pdb = file("pe", pe_sha, "x86_64", code), file("pdb", pdb_sha, "unknown", None)
    locations = {
        f.kind: (
            LocationEvidence(
                f"catalog/files/{f.id}/payload",
                "identity",
                f.raw_sha256,
                f.raw_size,
                "platform_owned",
                None,
                "proof/payload",
                "f" * 64,
            ),
        )
        for f in (pe, pdb)
    }
    return pe, pdb, locations


def origin(key="item-one"):
    return OriginEvidence("import_item", key, None, None, {"source_label": "unit source"})


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


def test_global_admission_replay_and_healthy_origin_append(catalog):
    db, _ = catalog
    pe, pdb, locations = pair_evidence()
    with db.sessions.begin() as session:
        pair = admit_pair(session, pe, pdb, locations, origin())
        pair_id = pair.id
    with db.sessions.begin() as session:
        admit_pair(session, pe, pdb, locations, origin())
        assert session.get(CatalogWatermark, 1).revision == 1
        replicas = {
            kind: (replace(values[0], object_key=values[0].object_key + "-replica"),)
            for kind, values in locations.items()
        }
        admit_pair(session, pe, pdb, replicas, origin("item-two"))
    with db.sessions() as session:
        assert count(session, CatalogFile) == 2
        assert count(session, CatalogPair) == 1
        assert count(session, CatalogPairOrigin) == 2
        assert count(session, CatalogFileLocation) == 4
        events = list(session.scalars(select(CatalogChange).order_by(CatalogChange.revision)))
        assert [e.affects_selection for e in events] == [True, False]
        assert {e.pair_id for e in events} == {pair_id}
        assert count(session, Workspace) == 0


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
        second = candidate_page(session, identity, after=first.next_pair_id, limit=1)
        assert second.next_pair_id is None
        assert {p["pair_id"] for p in (*first.pairs, *second.pairs)} == set(ids[:2])
        assert first.revision == second.revision
        debug_only = candidate_page(session, {"debug_id": identity["debug_id"]})
        assert len(debug_only.pairs) == 3


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


@pytest.mark.parametrize(
    "defect", ["half", "wrong_debug", "payload", "temporary_location", "origin_rebind"]
)
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
        admit_pair(session, *first, origin())
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


def test_catalog_reference_protects_raw_payload_after_compression_and_withdrawal(catalog):
    db, settings = catalog
    pe, pdb, locations = pair_evidence()
    raw_key = "artifact-blobs/wsp_source/pe/raw"
    now = datetime.now(UTC)
    with db.sessions.begin() as session:
        session.add(Workspace(id="wsp_source", name="source"))
        session.flush()
        session.add(
            ArtifactBlob(
                id="abl_source",
                workspace_id="wsp_source",
                kind="pe",
                sha256=pe.raw_sha256,
                size=pe.raw_size,
                object_key=raw_key,
                payload_object_key=raw_key,
                payload_encoding="identity",
                payload_sha256=pe.raw_sha256,
                payload_size=pe.raw_size,
                payload_verified_at=now,
                verification_status="verified",
                code_id=pe.code_id,
                debug_id=pe.debug_id,
            )
        )
    locations["pe"] = (
        replace(
            locations["pe"][0],
            object_key=raw_key,
            retention_basis="canonical_blob",
            artifact_blob_id="abl_source",
        ),
    )
    with db.sessions.begin() as session:
        pair = admit_pair(session, pe, pdb, locations, origin())
        review_pair(
            session,
            pair.id,
            expected_version=1,
            state="withdrawn",
            reason="retain reviewed history",
            evidence_object_key="review/evidence",
            evidence_sha256="e" * 64,
            idempotency_key="review",
        )
        blob = session.get(ArtifactBlob, "abl_source")
        blob.payload_object_key = raw_key + ".zst"
        blob.payload_encoding = "zstd-v1"
        blob.payload_sha256 = "d" * 64
        blob.payload_size = 10
        session.add(
            ArtifactBlobPayloadLegacyCopy(
                artifact_blob_id=blob.id,
                object_key=raw_key,
                sha256=blob.sha256,
                size=blob.size,
                retained_until=now - timedelta(days=1),
            )
        )

    class ForbiddenStore:
        def __getattr__(self, name):
            pytest.fail(f"protected content reached object I/O: {name}")

    with db.sessions.begin() as session:
        location = session.scalar(
            select(CatalogFileLocation).where(CatalogFileLocation.object_key == raw_key)
        )
        mark_location_unavailable(
            session,
            location.id,
            evidence_object_key="failures/raw-read",
            evidence_sha256="e" * 64,
            reason="controlled read failure",
        )

    for apply in (False, True):
        result = cleanup_artifact_blob_raw_payloads(
            db.sessions, ForbiddenStore(), settings, now=now, apply=apply
        )
        assert result["cases"][0]["reason"] == "catalog_retention_reference"
    with db.sessions() as session:
        assert session.get(ArtifactBlobPayloadLegacyCopy, "abl_source").deleted_at is None
    with db.sessions.begin() as session:
        # A new successful byte check can restore the already protected raw
        # location even though the Blob now serves its compressed payload.
        pair = admit_pair(session, pe, pdb, locations, origin())
        assert pair.state == "withdrawn"
        location = session.scalar(
            select(CatalogFileLocation).where(CatalogFileLocation.object_key == raw_key)
        )
        assert location.state == "available"
