"""Single-file acceptance with real PE/PDB/DMP and explicit scope boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import (
    ArtifactEntry,
    CatalogFile,
    CatalogPair,
    DumpBlob,
    Occurrence,
    OccurrenceSubmission,
    OccurrenceVersionAudit,
    TaskIntent,
    Upload,
)
from crashcap_api.services.artifact_catalog import pair_is_visible
from crashcap_api.services.catalog_materials import CatalogMaterialError, select_material
from crashcap_api.services.symbol_catalog import candidate_page
from fastapi.testclient import TestClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
PE = ROOT / "fixtures/.build/golden/golden_target_debug.exe"
PDB = PE.with_suffix(".pdb")
DMP = ROOT / "fixtures/p0-b01-null-read/generated/null-read.dmp"
CORE = ROOT / "target/debug/dmp-core.exe"


@pytest.fixture
def v3(tmp_path):
    if not all(path.is_file() for path in (PE, PDB, DMP, CORE)):
        pytest.skip("build real golden fixtures and native dmp-core before this acceptance lane")
    settings = Settings.for_test(tmp_path).model_copy(
        update={"core_executor": "local", "core_command": str(CORE)}
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield app, client


def space(client, name):
    result = client.post("/api/v3/workspaces", json={"name": name})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def upload(v3, path, workspace, version=None, *, name=None, claimed_sha=None, payload=None):
    app, client = v3
    data = path.read_bytes() if payload is None else payload
    kind = "pdb" if path.suffix == ".pdb" else "dmp" if path.suffix == ".dmp" else "pe"
    result = client.post(
        "/api/v3/uploads:init",
        json={
            "workspace_id": workspace,
            "filename": name or path.name,
            "file_kind": kind,
            "size": len(data),
            "sha256": claimed_sha or hashlib.sha256(data).hexdigest(),
            "version": version,
            "source": "cli",
        },
    )
    assert result.status_code == 201, result.text
    uid = result.json()["upload_id"]
    with app.state.database.sessions() as session:
        record = session.get(Upload, uid)
        app.state.store.put_bytes(record.object_key, data, "application/octet-stream")
    completion = client.post(f"/api/v3/uploads/{uid}:complete", json={})
    assert completion.status_code == 200, completion.text
    with app.state.database.sessions() as session:
        message = dict(
            session.scalar(select(TaskIntent).where(TaskIntent.logical_key == uid)).message
        )
    app.state.processor.verify_upload(message)
    # Redelivery after terminal acceptance is inert and never reads deleted staging.
    app.state.processor.verify_upload(message)
    result = client.get(f"/api/v3/uploads/{uid}")
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("reverse", [False, True])
def test_cross_batch_different_names_pair_independently(v3, reverse):
    app, client = v3
    workspace = space(client, "pair")
    files = (PDB, PE) if reverse else (PE, PDB)
    first = upload(v3, files[0], workspace, "v1", name="unrelated-a" + files[0].suffix)
    assert (first["status"], first["availability"]) == ("ACCEPTED", "waiting_for_pair")
    second = upload(v3, files[1], workspace, "v2", name="unrelated-b" + files[1].suffix)
    assert (second["status"], second["availability"]) == ("ACCEPTED", "symbols_available")
    result = client.get(
        "/api/v3/artifacts", params={"workspace_id": workspace, "availability": "symbols_available"}
    ).json()
    assert len(result["items"]) == 2
    assert {row["version"] for row in result["items"]} == {"v1", "v2"}
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogFile)) == 2
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1


@pytest.mark.parametrize(
    "pe_scope,pdb_scope,visible",
    [
        ("public", "public", {"a", "b"}),
        ("a", "a", {"a"}),
        ("public", "a", {"a"}),
        ("a", "public", {"a"}),
        ("a", "b", set()),
    ],
)
def test_scope_matrix_candidates_and_materials(v3, pe_scope, pdb_scope, visible):
    app, client = v3
    spaces = {"a": space(client, "a"), "b": space(client, "b"), "public": None}
    upload(v3, PE, spaces[pe_scope])
    upload(v3, PDB, spaces[pdb_scope])
    with app.state.database.sessions() as session:
        pe = session.scalar(select(CatalogFile).where(CatalogFile.kind == "pe"))
        identity = {"code_id": pe.code_id, "debug_id": pe.debug_id, "architecture": "x86_64"}
        pairs = list(session.scalars(select(CatalogPair)))
        for name in ("a", "b"):
            page = candidate_page(session, identity, workspace_id=spaces[name])
            assert bool(page.pairs) == (name in visible)
            for pair in pairs:
                assert pair_is_visible(session, pair.id, spaces[name]) == (name in visible)
                if name in visible:
                    assert (
                        select_material(
                            session,
                            pair.id,
                            pair.debug_id,
                            "pdb",
                            max_locations=5,
                            workspace_id=spaces[name],
                        ).raw_size
                        == PDB.stat().st_size
                    )
                else:
                    with pytest.raises(CatalogMaterialError, match="CATALOG_PAIR_NOT_FOUND"):
                        select_material(
                            session,
                            pair.id,
                            pair.debug_id,
                            "pdb",
                            max_locations=5,
                            workspace_id=spaces[name],
                        )


def test_content_reuse_does_not_grant_scope_and_new_binding_can_pair(v3):
    app, client = v3
    a = space(client, "a")
    b = space(client, "b")
    upload(v3, PE, a)
    upload(v3, PDB, a)
    partial = upload(v3, PDB, b, "sdk")
    assert partial["availability"] == "waiting_for_pair"
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogFile)) == 2
    result = upload(v3, PE, b, "another-version")
    assert result["availability"] == "symbols_available"
    assert len(list(app.state.store.iter_objects("catalog/files"))) == 2


def test_same_identity_different_valid_pe_content_is_conflict(v3):
    app, client = v3
    a = space(client, "a")
    upload(v3, PE, None)
    upload(v3, PDB, None)
    different = PE.read_bytes() + b"valid PE overlay with distinct content"
    result = upload(v3, PE, a, payload=different)
    assert result["status"] == "ACCEPTED" and result["availability"] == "identity_conflict"
    with app.state.database.sessions() as session:
        public_pe = session.scalar(
            select(CatalogFile).where(CatalogFile.kind == "pe").order_by(CatalogFile.created_at)
        )
        identity = {
            "code_id": public_pe.code_id,
            "debug_id": public_pe.debug_id,
            "architecture": "x86_64",
        }
        assert len(candidate_page(session, identity, workspace_id=a).pairs) == 2
        assert len(candidate_page(session, identity, workspace_id=None).pairs) == 1


def test_dump_version_fill_conflict_edit_and_submission_history(v3):
    app, client = v3
    a = space(client, "a")
    first = upload(v3, DMP, a)
    second = upload(v3, DMP, a, "v1")
    conflict = upload(v3, DMP, a, "v2")
    oid = first["occurrence_id"]
    assert oid == second["occurrence_id"] == conflict["occurrence_id"]
    assert second["current_version"] == "v1" and conflict["version_conflict"] is True
    response = client.patch(f"/api/v3/occurrences/{oid}/version", json={"version": "v3"})
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/v3/occurrences/{oid}").json()
    assert detail["version"] == "v3" and detail["current_analysis"] is None
    page = client.get(f"/api/v3/workspaces/{a}/occurrences", params={"version": "v3"}).json()
    assert page["items"][0]["version"] == "v3"
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(DumpBlob)) == 1
        assert [
            row.version
            for row in session.scalars(
                select(OccurrenceSubmission).order_by(OccurrenceSubmission.upload_id)
            )
        ] == [None, "v1", "v2"]
        assert session.scalar(select(func.count()).select_from(OccurrenceVersionAudit)) == 1
    assert len(list(app.state.store.iter_objects("dump-blobs"))) == 1


def test_invalid_bytes_and_wrong_hash_do_not_pollute_accepted_files(v3):
    app, client = v3
    a = space(client, "a")
    accepted = upload(v3, PE, a)
    corrupt = upload(v3, PDB, a, payload=b"Microsoft C/C++ MSF 7.00" + b"\0" * 100)
    wrong = upload(v3, PDB, a, claimed_sha="0" * 64)
    assert accepted["status"] == "ACCEPTED"
    assert corrupt["status"] == wrong["status"] == "REJECTED"
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactEntry)) == 1
    assert upload(v3, PDB, a)["availability"] == "symbols_available"


def test_public_dump_and_old_build_inputs_are_rejected(v3):
    _app, client = v3
    assert (
        client.post(
            "/api/v3/uploads:init", json={"filename": "crash.dmp", "size": 32, "file_kind": "dmp"}
        ).status_code
        == 422
    )
    a = space(client, "a")
    assert (
        client.post(
            "/api/v3/uploads:init",
            json={
                "filename": "a.pdb",
                "size": 32,
                "file_kind": "pdb",
                "workspace_id": a,
                "build_id": "old",
            },
        ).status_code
        == 422
    )
    assert client.get("/api/v1/workspaces").status_code == 404
    assert not any("build" in path for path in client.get("/openapi.json").json()["paths"])
