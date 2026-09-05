"""Byte-serving controls. Real PE/PDB parsing is qualified in the live source lane."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from crashcap_api.catalog_source import OwnedMaterialResponse
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import CatalogFileLocation, CatalogPair
from crashcap_api.services.artifact_payloads import ArtifactBlobCodec
from crashcap_api.services.symbol_catalog import FileEvidence, LocationEvidence
from crashcap_api.storage import create_object_store
from crashcap_api.symbol_source import create_symbol_source_app
from fastapi.testclient import TestClient
from sqlalchemy import select

from .catalog_fixtures import OriginEvidence, admit_pair

DEBUG = "2" * 32 + "1"


@pytest.fixture
def material_source(tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "catalog_source_enabled": True,
            "catalog_source_max_concurrent": 1,
        }
    )
    database = Database(settings)
    store = create_object_store(settings)
    app = create_symbol_source_app(settings, database=database, store=store)
    with TestClient(app) as client:
        yield database.sessions, store, settings, client
    database.dispose()


def seed(source, *, compressed=False, pe=b"unit PE content", pdb=b"unit PDB content"):
    sessions, store, settings, _ = source
    files, locations = {}, {}
    for kind, content in (("pe", pe), ("pdb", pdb)):
        file = FileEvidence(
            kind,
            hashlib.sha256(content).hexdigest(),
            len(content),
            "123456789" if kind == "pe" else None,
            DEBUG,
            "x86_64" if kind == "pe" else "unknown",
            "unit-content-only-not-Core-proof",
            "proof/unit",
            "f" * 64,
        )
        key = f"catalog/files/{file.id}/fixture"
        if compressed:
            settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
            raw, encoded = settings.task_tmp_root / kind, settings.task_tmp_root / (kind + ".zst")
            raw.write_bytes(content)
            payload = ArtifactBlobCodec().encode_file(raw, encoded, kind=kind, encoding="zstd-v1")
            data = encoded.read_bytes()
            raw.unlink()
            encoded.unlink()
            encoding = payload.encoding
        else:
            data, encoding = content, "identity"
        store.put_bytes(key, data, "application/octet-stream")
        files[kind] = file
        locations[kind] = (
            LocationEvidence(
                key,
                encoding,
                hashlib.sha256(data).hexdigest(),
                len(data),
                "platform_owned",
                "proof/unit",
                "f" * 64,
            ),
        )
    with sessions.begin() as session:
        pair = admit_pair(
            session,
            files["pe"],
            files["pdb"],
            locations,
            OriginEvidence("import_item", files["pdb"].raw_sha256, None, None, {}),
        )
        pair_id = pair.id
    return pair_id, files, locations


def url(pair_id, leaf="debuginfo"):
    return f"/v3/pairs/public/{pair_id}/{DEBUG[:2]}/{DEBUG[2:]}/{leaf}"


@pytest.mark.parametrize("compressed", [False, True])
def test_get_head_raw_identity_and_temporary_cleanup(material_source, compressed):
    _, _, settings, client = material_source
    pair_id, files, _ = seed(material_source, compressed=compressed)
    for leaf, kind, content in (
        ("executable", "pe", b"unit PE content"),
        ("debuginfo", "pdb", b"unit PDB content"),
    ):
        response = client.get(url(pair_id, leaf))
        assert response.status_code == 200 and response.content == content
        assert response.headers["x-crashcap-raw-sha256"] == files[kind].raw_sha256
        assert response.headers["etag"] == f'"sha256:{files[kind].raw_sha256}"'
        head = client.head(url(pair_id, leaf))
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-length"] == str(len(content))
        assert not list(settings.task_tmp_root.iterdir())


def test_pair_content_does_not_change_on_conflict_or_withdrawal(material_source):
    sessions, _, _, client = material_source
    first, _, _ = seed(material_source)
    second, _, _ = seed(material_source, pdb=b"different content same Debug ID")
    assert first != second
    with sessions.begin() as session:
        session.get(CatalogPair, first).state = "withdrawn"
    assert client.get(url(first)).content == b"unit PDB content"
    assert client.get(url(second)).content == b"different content same Debug ID"
    with sessions() as session:
        assert session.get(CatalogPair, first).state == "withdrawn"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("compressed", [False, True])
def test_corrupted_payload_is_never_a_successful_head_or_body(material_source, method, compressed):
    _, store, settings, client = material_source
    pair_id, _, locations = seed(material_source, compressed=compressed)
    location = locations["pdb"][0]
    store.put_bytes(location.object_key, b"x" * location.payload_size, "application/octet-stream")
    response = client.request(method, url(pair_id))
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    if method == "GET":
        assert response.json()["error"]["failure_class"] == "permanent"
    assert not list(settings.task_tmp_root.iterdir())


def test_raw_hash_is_checked_after_successful_zstd_payload_read(material_source):
    sessions, store, settings, client = material_source
    pair_id, _, locations = seed(material_source, compressed=True)
    raw, encoded = settings.task_tmp_root / "changed", settings.task_tmp_root / "changed.zst"
    raw.write_bytes(b"wrong PDB value!")
    payload = ArtifactBlobCodec().encode_file(raw, encoded, kind="pdb", encoding="zstd-v1")
    location = locations["pdb"][0]
    store.put_file(location.object_key, encoded, "application/zstd")
    raw.unlink()
    encoded.unlink()
    with sessions.begin() as session:
        row = session.scalar(
            select(CatalogFileLocation).where(CatalogFileLocation.object_key == location.object_key)
        )
        row.payload_sha256, row.payload_size = payload.payload_sha256, payload.payload_size
    response = client.get(url(pair_id))
    assert response.status_code == 422 and response.json()["error"]["failure_class"] == "permanent"


def test_wrong_pair_debug_and_leaf_never_fall_back(material_source):
    _, _, _, client = material_source
    pair_id, _, _ = seed(material_source)
    for path in (
        url("0" * 64),
        url(pair_id).replace(DEBUG[2:], "3" * len(DEBUG[2:])),
        url(pair_id, "same.pdb"),
        url(pair_id.upper()),
        url("bad"),
    ):
        assert client.get(path).status_code == 404


def test_missing_replica_can_use_only_same_verified_content(material_source):
    sessions, store, _, client = material_source
    pair_id, files, locations = seed(material_source)
    alternative = replace(locations["pdb"][0], object_key=f"catalog/files/{files['pdb'].id}/second")
    store.put_bytes(alternative.object_key, b"unit PDB content", "application/octet-stream")
    with sessions.begin() as session:
        admit_pair(
            session,
            files["pe"],
            files["pdb"],
            {"pe": locations["pe"], "pdb": (alternative,)},
            OriginEvidence("import_item", "second-replica", None, None, {}),
        )
        first = session.scalar(
            select(CatalogFileLocation).where(
                CatalogFileLocation.object_key == locations["pdb"][0].object_key
            )
        )
        first.state = "unavailable"
    store.delete(locations["pdb"][0].object_key)
    assert client.get(url(pair_id)).content == b"unit PDB content"
    store.delete(alternative.object_key)
    response = client.get(url(pair_id))
    assert response.status_code == 503 and response.json()["error"]["failure_class"] == "transient"
    # Serving a reappeared exact object must not mutate qualification state.
    store.put_bytes(locations["pdb"][0].object_key, b"unit PDB content", "application/octet-stream")
    assert client.get(url(pair_id)).status_code == 200
    with sessions() as session:
        assert session.get(CatalogFileLocation, first.id).state == "unavailable"


def test_replica_budget_is_explicit_and_not_a_false_404(material_source):
    sessions, store, settings, client = material_source
    pair_id, files, locations = seed(material_source)
    alternative = replace(locations["pdb"][0], object_key=f"catalog/files/{files['pdb'].id}/second")
    with sessions.begin() as session:
        admit_pair(
            session,
            files["pe"],
            files["pdb"],
            {"pe": locations["pe"], "pdb": (alternative,)},
            OriginEvidence("import_item", "second-replica", None, None, {}),
        )
    store.delete(locations["pdb"][0].object_key)
    settings.catalog_source_max_locations = 1
    response = client.get(url(pair_id))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CATALOG_LOCATION_BUDGET_EXHAUSTED"
    assert response.json()["error"]["failure_class"] == "unknown"


def test_source_off_and_request_capacity_are_explicit(material_source, monkeypatch):
    _, store, settings, client = material_source
    pair_id, _, _ = seed(material_source)
    entered, release = threading.Event(), threading.Event()
    original = store.stream

    def slow(*args):
        entered.set()
        assert release.wait(timeout=10)
        yield from original(*args)

    monkeypatch.setattr(store, "stream", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.get, url(pair_id))
        try:
            assert entered.wait(timeout=5)
            busy = client.get(url(pair_id))
            assert busy.status_code == 503 and busy.json()["error"]["code"] == "CATALOG_SOURCE_BUSY"
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert client.get(url(pair_id)).status_code == 200


def test_disconnect_cleans_file_and_releases_capacity(tmp_path):
    root = tmp_path / "owned-response"
    root.mkdir()
    path = root / "payload"
    path.write_bytes(b"verified bytes")
    released = []
    response = OwnedMaterialResponse(root, path, {}, lambda: released.append(True))

    async def fail_send(_message):
        raise RuntimeError("simulated disconnect")

    async def receive():
        return {"type": "http.disconnect"}

    with pytest.raises(RuntimeError, match="disconnect"):
        asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, fail_send))
    assert released == [True] and not root.exists()


@pytest.mark.parametrize(
    "range_header,expected", [("bytes=0-", b"unit PDB content"), ("bytes=1-3", b"nit")]
)
def test_ranges_are_from_fully_verified_raw_content(material_source, range_header, expected):
    _, store, settings, client = material_source
    pair_id, files, locations = seed(material_source, compressed=True)
    response = client.get(url(pair_id), headers={"Range": range_header})
    assert response.status_code == 206 and response.content == expected
    end = files["pdb"].raw_size - 1
    assert response.headers["content-range"] == (
        f"bytes 0-{end}/{end + 1}" if range_header == "bytes=0-" else f"bytes 1-3/{end + 1}"
    )
    assert response.headers["x-crashcap-raw-sha256"] == files["pdb"].raw_sha256
    assert not list(settings.task_tmp_root.iterdir())
    location = locations["pdb"][0]
    store.put_bytes(location.object_key, b"x" * location.payload_size, "application/octet-stream")
    assert client.get(url(pair_id), headers={"Range": range_header}).status_code == 422
