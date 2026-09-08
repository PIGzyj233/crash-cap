"""Byte-validated attribution acceptance; requires real Core and PE/PDB/DMP fixtures."""

import hashlib
import os
from pathlib import Path

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import ArtifactEntry, CatalogFile, DumpBlob, OccurrenceSubmission, Upload
from crashcap_api.storage import stream_sha256
from sqlalchemy import func, select

from .test_authentication import client_for
from .test_upload_v3 import upload

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def native_auth(tmp_path):
    core = Path(os.getenv("CRASHCAP_AUTH_TEST_CORE", str(ROOT / "target/debug/dmp-core.exe")))
    files = {
        "exe": Path(
            os.getenv(
                "CRASHCAP_AUTH_TEST_EXE",
                str(ROOT / "fixtures/.build/golden/golden_target_debug.exe"),
            )
        ),
        "dll": Path(
            os.getenv(
                "CRASHCAP_AUTH_TEST_DLL",
                str(ROOT / "fixtures/.build/golden/golden_target_debug.exe"),
            )
        ),
        "pdb": Path(
            os.getenv(
                "CRASHCAP_AUTH_TEST_PDB",
                str(ROOT / "fixtures/.build/golden/golden_target_debug.pdb"),
            )
        ),
        "dmp": Path(
            os.getenv(
                "CRASHCAP_AUTH_TEST_DMP",
                str(ROOT / "fixtures/p0-b01-null-read/generated/null-read.dmp"),
            )
        ),
    }
    if not all(path.is_file() for path in (core, *files.values())):
        pytest.skip(
            "requires real Core and PE/PDB/DMP fixtures; see authentication validation guide"
        )
    app = create_app(
        Settings.for_test(tmp_path).model_copy(
            update={"core_executor": "local", "core_command": str(core)}
        )
    )
    yield app, files
    app.state.database.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("extension", ["exe", "dll", "pdb", "dmp"])
def test_real_content_is_deduplicated_without_merging_submitters(native_auth, extension):
    app, files = native_auth
    alice, aid = client_for(app)
    bob, bid = client_for(app, "bob")
    workspace = alice.post("/api/v3/workspaces", json={"name": "real-attribution"}).json()["id"]
    path = files[extension]
    first = upload((app, alice), path, workspace, "alice-version", name=f"alice.{extension}")
    second = upload((app, bob), path, workspace, "bob-version", name=f"bob.{extension}")
    assert first["status"] == second["status"] == "ACCEPTED"
    assert first["uploaded_by"]["id"] == aid
    assert second["uploaded_by"]["id"] == bid
    assert first["upload_id"] != second["upload_id"]
    with app.state.database.sessions() as session:
        if extension == "dmp":
            assert first["occurrence_id"] == second["occurrence_id"]
            rows = list(session.scalars(select(OccurrenceSubmission)))
            assert session.scalar(select(func.count()).select_from(DumpBlob)) == 1
            key = session.scalar(select(DumpBlob)).object_key
        else:
            rows = list(session.scalars(select(ArtifactEntry)))
            assert session.scalar(select(func.count()).select_from(CatalogFile)) == 1
            retained = session.scalar(select(CatalogFile))
            assert retained.validator_version.startswith("core-identify-v1:binary-sha256:")
            key = f"catalog/files/{retained.id}/raw"
        assert len(rows) == 2
        assert {row.uploaded_by["id"] for row in rows} == {aid, bid}
        assert {row.version for row in rows} == {"alice-version", "bob-version"}
        assert session.scalar(select(func.count()).select_from(Upload)) == 2
    assert stream_sha256(app.state.store, key)[:2] == (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        path.stat().st_size,
    )
    listed = alice.get("/api/v3/uploads", params={"uploaded_by_user_id": bid}).json()["items"]
    assert [row["upload_id"] for row in listed] == [second["upload_id"]]
