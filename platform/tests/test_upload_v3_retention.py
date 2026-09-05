"""Real DMP bytes shared across spaces; expiration and restoration remain local."""

from datetime import timedelta

from crashcap_api.models import AnalysisDemand, DumpBlob, Occurrence, utcnow
from crashcap_worker.retention import expire_dump_blobs
from sqlalchemy import select

from .test_upload_v3 import DMP, PDB, PE, space, upload
from .test_upload_v3 import v3 as upload_fixture

v3 = upload_fixture


def test_shared_dump_has_one_physical_write_and_independent_retention(v3, monkeypatch):
    app, client = v3
    a, b = space(client, "a"), space(client, "b")
    writes = []
    original = app.state.store.put_file

    def put(key, path, content_type):
        if key.startswith("dump-blobs/"):
            writes.append(key)
        return original(key, path, content_type)

    monkeypatch.setattr(app.state.store, "put_file", put)
    first, second = upload(v3, DMP, a), upload(v3, DMP, b)
    assert len(writes) == 1 and first["occurrence_id"] != second["occurrence_id"]
    sessions = app.state.database.sessions
    with sessions.begin() as session:
        blob = session.scalar(select(DumpBlob).where(DumpBlob.workspace_id == a))
        blob.expires_at = utcnow() - timedelta(days=1)
        key = blob.object_key
    assert expire_dump_blobs(sessions, app.state.store) == 1
    assert app.state.store.head(key).size == DMP.stat().st_size
    with sessions.begin() as session:
        session.scalar(select(DumpBlob).where(DumpBlob.workspace_id == b)).expires_at = (
            utcnow() - timedelta(days=1)
        )
        demand = session.scalar(
            select(AnalysisDemand).where(AnalysisDemand.occurrence_id == first["occurrence_id"])
        )
        demand.state = "cannot_recompute"
        demand.reason = "DUMP_UNAVAILABLE"
    assert expire_dump_blobs(sessions, app.state.store) == 1
    assert len(list(app.state.store.iter_objects("dump-blobs/"))) == 0
    restored = upload(v3, DMP, a, "restored")
    assert restored["occurrence_id"] == first["occurrence_id"] and len(writes) == 2
    with sessions() as session:
        assert len(list(session.scalars(select(Occurrence)))) == 2
        demand = session.scalar(
            select(AnalysisDemand).where(AnalysisDemand.occurrence_id == first["occurrence_id"])
        )
        assert demand.state == "preparing" and demand.reason == "dump_restored"
        assert (
            session.scalar(select(DumpBlob).where(DumpBlob.workspace_id == b)).deleted_at
            is not None
        )


def test_failed_physical_delete_preserves_live_reference(v3, monkeypatch):
    app, client = v3
    workspace = space(client, "failed-delete")
    upload(v3, DMP, workspace)
    with app.state.database.sessions.begin() as session:
        session.scalar(select(DumpBlob)).expires_at = utcnow() - timedelta(days=1)

    def fail(_key):
        raise OSError("temporary storage outage")

    monkeypatch.setattr(app.state.store, "delete", fail)
    assert expire_dump_blobs(app.state.database.sessions, app.state.store) == 0
    with app.state.database.sessions() as session:
        assert session.scalar(select(DumpBlob)).deleted_at is None


def test_inventory_tracks_withdrawal_storage_failure_and_verified_restore(v3):
    from crashcap_api.models import CatalogFileLocation, CatalogPair
    from crashcap_api.services.symbol_catalog import mark_location_unavailable, review_pair

    app, client = v3
    workspace = space(client, "availability")
    first = upload(v3, PE, workspace)
    upload(v3, PDB, workspace)
    with app.state.database.sessions.begin() as session:
        pair = session.scalar(select(CatalogPair))
        pair_id = pair.id
        location = session.scalar(
            select(CatalogFileLocation).where(CatalogFileLocation.file_id == pair.pdb_file_id)
        )
        mark_location_unavailable(
            session,
            location.id,
            evidence_object_key="review/storage",
            evidence_sha256="e" * 64,
            reason="verified missing",
        )
    assert (
        client.get(f"/api/v3/uploads/{first['upload_id']}").json()["availability"]
        == "storage_unavailable"
    )
    assert upload(v3, PDB, workspace)["availability"] == "symbols_available"
    with app.state.database.sessions.begin() as session:
        review_pair(
            session,
            pair_id,
            expected_version=1,
            state="withdrawn",
            reason="provider reviewed",
            evidence_object_key="review/withdrawal",
            evidence_sha256="e" * 64,
            idempotency_key="withdraw",
        )
    assert (
        client.get(f"/api/v3/uploads/{first['upload_id']}").json()["availability"]
        == "waiting_for_pair"
    )
    assert upload(v3, PDB, workspace)["availability"] == "waiting_for_pair"
