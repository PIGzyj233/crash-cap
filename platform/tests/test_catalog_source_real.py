"""Owned PostgreSQL + real HTTP source + pinned Symbolicator + native Core."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.frozen_inputs import normalize_identity
from crashcap_api.services.symbol_catalog import review_pair
from crashcap_api.storage import create_object_store
from crashcap_api.symbol_source import create_symbol_source_app
from crashcap_worker.core_runner import CoreExecutor

from . import test_frozen_delivery_redis as delivery_tests
from . import test_symbol_catalog_postgres as catalog_tests
from .catalog_fixtures import OriginEvidence, admit_pair, prepare_catalog_pair
from .test_upload_v3 import CORE, ROOT

FIXTURE = ROOT / "fixtures/p0-b01-null-read/generated"

pg = catalog_tests.pg
owned_redis = delivery_tests.owned_redis
IMAGE = (
    "ghcr.io/getsentry/symbolicator@sha256:"
    "9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_MATERIAL_REAL"),
        reason="requires the owned material-source qualification runner",
    ),
]


def docker(*args):
    return subprocess.run(  # noqa: S603 - fixed executable and test-owned arguments
        ["docker", *args],  # noqa: S607 - fixed executable used by owned qualification
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()


@pytest.fixture
def live(pg):
    engine, _, _ = pg
    token = uuid.uuid4().hex
    output = (
        ROOT
        / "target/qa-symbol-import/material-source"
        / os.environ["QAI_MATERIAL_RUN_TOKEN"]
        / token
    )
    output.mkdir(parents=True)
    settings = Settings.for_test(
        output, engine.url.render_as_string(hide_password=False)
    ).model_copy(
        update={
            "object_store_local_root": ROOT / "target/qai-material-objects" / token,
            "core_executor": "local",
            "core_command": str(CORE),
            "catalog_source_enabled": True,
            "symbol_imports_enabled": True,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
            "frozen_public_sources": [],
        }
    )
    database = Database(settings)
    store = create_object_store(settings)
    app = create_symbol_source_app(settings, database=database, store=store)
    events = []
    faults = {"pair_status": None}

    @app.middleware("http")
    async def observe(request, call_next):
        if faults["pair_status"] and request.url.path.startswith("/v3/pairs/"):
            from starlette.responses import Response

            response = Response(status_code=faults["pair_status"])
        else:
            response = await call_next(request)
        events.append(
            {
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "raw_sha256": response.headers.get("x-crashcap-raw-sha256"),
                "request_id": response.headers.get("x-request-id"),
                "range": request.headers.get("range"),
                "content_range": response.headers.get("content-range"),
                "content_length": response.headers.get("content-length"),
            }
        )
        return response

    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))  # noqa: S104 - synthetic fixture endpoint for Docker Desktop only
    listener.listen(64)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    container = None
    receipt = {"status": "RUNNING", "output": str(output)}
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Owned material HTTP service did not start")
            time.sleep(0.05)
        config = output / "symbolicator.yml"
        config.write_text(
            "bind: 0.0.0.0:3021\ncache_dir: /data\nconnect_to_reserved_ips: true\n"
            "max_concurrent_requests: 4\nsources: []\n",
            encoding="utf-8",
        )
        # Docker may allocate a different host port when an anonymous mapping is
        # restarted. Keep the endpoint fixed throughout a frozen comparison.
        with socket.socket() as port_picker:
            port_picker.bind(("127.0.0.1", 0))
            symbolicator_port = port_picker.getsockname()[1]
        container = docker(
            "run",
            "--pull=never",
            "-d",
            "--name",
            "qai-material-" + token,
            "--label",
            "crashcap.qai.material=" + token,
            "--label",
            "crashcap.qai.material.run=" + os.environ["QAI_MATERIAL_RUN_TOKEN"],
            "-p",
            f"127.0.0.1:{symbolicator_port}:3021",
            *(["--add-host", "host.docker.internal:host-gateway"] if os.name != "nt" else []),
            "--mount",
            f"type=bind,source={config.resolve().as_posix()},target=/etc/symbolicator/config.yml,readonly",
            "-v",
            "/data",
            IMAGE,
            "run",
            "-c",
            "/etc/symbolicator/config.yml",
        )
        mapping = docker("port", container, "3021/tcp")
        assert mapping.startswith("127.0.0.1:")
        endpoint = "http://" + mapping
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(endpoint + "/healthcheck", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned Symbolicator did not become ready")
            time.sleep(0.1)
        image_id = docker("inspect", "--format", "{{.Image}}", container)
        version = (
            docker("exec", container, "symbolicator", "--version")
            .splitlines()[0]
            .removeprefix("symbolicator version: ")
        )
        assert version == "26.7.2"
        receipt.update(image_id=image_id, version=version, container_id=container)

        def cold_cache():
            # Keep the frozen endpoint and engine identity, but force this owned
            # engine to observe the next HTTP fault rather than its positive cache.
            text = config.read_text(encoding="utf-8")
            text = "\n".join(
                "cache_dir: /data/" + uuid.uuid4().hex if line.startswith("cache_dir:") else line
                for line in text.splitlines()
            )
            config.write_text(text + "\n", encoding="utf-8")
            docker("restart", "--time", "1", container)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    if httpx.get(endpoint + "/healthcheck", timeout=2).status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            raise RuntimeError("Cold Symbolicator did not become ready")

        yield {
            "settings": settings,
            "sessions": database.sessions,
            "store": store,
            "core": CoreExecutor(settings),
            "output": output,
            "endpoint": endpoint,
            "source_root": f"http://host.docker.internal:{port}/v3/pairs/public",
            "local_root": f"http://127.0.0.1:{port}/v3/pairs/public",
            "image_id": image_id,
            "version": version,
            "events": events,
            "http_app": app,
            "faults": faults,
            "cold_cache": cold_cache,
        }
        receipt["status"] = "PASS"
    finally:
        errors = []
        if container is not None:
            try:
                assert (
                    docker(
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "crashcap.qai.material"}}',
                        container,
                    )
                    == token
                )
                docker("rm", "-f", "-v", container)
                receipt["owned_symbolicator_and_volume_removed"] = True
            except Exception as error:
                errors.append(type(error).__name__)
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        database.dispose()
        if thread.is_alive():
            errors.append("HTTP_SERVICE_STILL_ALIVE")
        receipt["http_service_stopped"] = not thread.is_alive()
        receipt["events"] = events
        if errors:
            receipt.update(status="FAIL", cleanup_errors=errors)
        (output / "lifecycle.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        assert not errors, errors


def admit(live, *, compressed=False, alternate=False, fixture=FIXTURE):
    pe, pdb = fixture / "null_read_target.exe", fixture / "null_read_target.pdb"
    if alternate:
        data = pdb.read_bytes()
        changed = data.replace(b"trigger_null_read", b"trigger_fake_read")
        assert changed != data and len(changed) == len(data)
        pdb = live["output"] / "alternate.pdb"
        pdb.write_bytes(changed)
    prepared = prepare_catalog_pair(
        live["core"],
        live["store"],
        pe,
        pdb,
        payload_encoding="zstd-v1" if compressed else "identity",
    )
    with live["sessions"].begin() as session:
        pair = admit_pair(
            session,
            prepared.pe,
            prepared.pdb,
            prepared.locations,
            OriginEvidence("import_item", "real-source-" + str(alternate), None, None, {}),
        )
        pair_id = pair.id
    return pair_id, prepared


def symbolicate(live, pair_id, prepared):
    inspect = json.loads(
        (ROOT / "target/qa-symbol-import/frozen-context/inspect.json").read_bytes()
    )
    module = next(
        module
        for module in inspect["modules"]
        if normalize_identity({**module, "architecture": "unknown"})["debug_id"]
        == prepared.pe.debug_id
    )
    request = {
        "platform": "native",
        "modules": [
            {
                "type": "pe",
                "code_id": prepared.pe.code_id,
                "debug_id": module["debug_id"],
                "code_file": "fixture.exe",
                "debug_file": "fixture.pdb",
                "image_addr": module["image_base"],
                "image_size": module["image_size"],
            }
        ],
        "stacktraces": [{"frames": [{"instruction_addr": inspect["exception"]["address"]}]}],
        "sources": [
            {
                "id": f"crash-cap:pair:{pair_id}:http-v2",
                "type": "http",
                "url": f"{live['source_root']}/{pair_id}/",
                "layout": {"type": "unified", "casing": "lowercase"},
                "filters": {"filetypes": ["pe", "pdb"]},
                "is_public": False,
            }
        ],
        "options": {"dif_candidates": True, "apply_source_context": False},
    }
    with httpx.Client(base_url=live["endpoint"], timeout=45) as client:
        result = client.post("/symbolicate?timeout=30", json=request)
        result.raise_for_status()
        value = result.json()
        deadline = time.monotonic() + 45
        while value["status"] == "pending" and time.monotonic() < deadline:
            value = client.get("/requests/" + value["request_id"]).json()
            if value["status"] == "pending":
                time.sleep(0.1)
        assert value["status"] == "completed", value
    (live["output"] / (pair_id + ".symbolicate.json")).write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8"
    )
    return [
        frame.get("function", "") for trace in value["stacktraces"] for frame in trace["frames"]
    ]


def test_real_symbolicator_isolates_same_identity_different_pdb_content(live):
    pair_a, prepared_a = admit(live, compressed=False)
    pair_b, prepared_b = admit(live, compressed=False, alternate=True)
    assert pair_a != pair_b and prepared_a.pe.debug_id == prepared_b.pe.debug_id
    assert any(
        "trigger_null_read" in function for function in symbolicate(live, pair_a, prepared_a)
    )
    assert any(
        "trigger_fake_read" in function for function in symbolicate(live, pair_b, prepared_b)
    )
    cold_count = len(live["events"])
    assert any(
        "trigger_null_read" in function for function in symbolicate(live, pair_a, prepared_a)
    )
    assert len(live["events"]) == cold_count  # Native Symbolicator reused the content cache.
    for pair_id, prepared in ((pair_a, prepared_a), (pair_b, prepared_b)):
        assert any(
            event["status"] in {200, 206}
            and f"/{pair_id}/" in event["path"]
            and event["raw_sha256"] == prepared.pdb.raw_sha256
            and event["content_length"] == str(prepared.pdb.raw_size)
            and (
                event["status"] == 200
                or event["content_range"]
                == f"bytes 0-{prepared.pdb.raw_size - 1}/{prepared.pdb.raw_size}"
            )
            for event in live["events"]
        )
    with live["sessions"].begin() as session:
        review_pair(
            session,
            pair_a,
            expected_version=1,
            idempotency_key="withdraw-source-fixture",
            state="withdrawn",
            reason="qualification fixture",
            evidence_object_key="fixture/review",
            evidence_sha256="a" * 64,
        )
    path = (
        f"{live['local_root']}/{pair_a}/{prepared_a.pe.debug_id[:2]}/"
        f"{prepared_a.pe.debug_id[2:]}/debuginfo"
    )
    response = httpx.get(path, timeout=10)
    assert (
        response.status_code == 200
        and hashlib.sha256(response.content).hexdigest() == prepared_a.pdb.raw_sha256
    )
    (live["output"] / "result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "case": "same_identity_content_isolation",
                "pairs": [pair_a, pair_b],
                "compressed": True,
                "cache_reused": True,
                "withdrawn_frozen_read": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
