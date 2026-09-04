"""Owned PostgreSQL + real HTTP source + pinned Symbolicator + native Core."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import ExitStack

import httpx
import pytest
import uvicorn
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.frozen_inputs import canonical_bytes, digest, frozen_run_key, normalize_identity
from crashcap_api.models import Artifact, Build, BuildModule, Workspace
from crashcap_api.services.catalog_materials import materialize_catalog_file, select_material
from crashcap_api.services.symbol_catalog import OriginEvidence, admit_pair, review_pair
from crashcap_api.services.workspace_builds import prepare_build_policy, snapshot_workspace_builds
from crashcap_api.services.workspace_policies import (
    prepare_workspace_policies,
    snapshot_workspace_policies,
)
from crashcap_api.storage import create_object_store
from crashcap_api.symbol_source import create_symbol_source_app
from crashcap_worker.catalog_validation import prepare_catalog_pair
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from crashcap_worker.frozen_core import FrozenAssignment, FrozenCoreExecutor

from . import test_frozen_delivery_redis as delivery_tests
from . import test_symbol_catalog_postgres as catalog_tests
from .fixture_source import fixture_source_root
from .test_symbol_imports import CORE, FIXTURE, ROOT

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
        if faults["pair_status"] and request.url.path.startswith("/v2/pairs/"):
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
            "source_root": f"http://host.docker.internal:{port}/v2/pairs",
            "local_root": f"http://127.0.0.1:{port}/v2/pairs",
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


def admit(live, *, compressed=True, alternate=False, fixture=FIXTURE):
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
    pair_a, prepared_a = admit(live, compressed=True)
    pair_b, prepared_b = admit(live, compressed=True, alternate=True)
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


@pytest.mark.parametrize("source_mode", ["none", "valid", "corrupt", "missing"])
def test_real_frozen_worker_uses_catalog_materials_for_unwind_and_symbols(live, source_mode):
    from crashcap_api.services.analysis_demands import freeze_target, register_inspection
    from crashcap_api.services.resolution_planning import snapshot_resolution
    from crashcap_worker.demand_inspection import prepare_inspection
    from crashcap_worker.resolution_planner import prepare_resolution
    from crashcap_worker.source_bundle import inspect_source_bundle

    from .test_analysis_demands import NOW, SCHEMAS, seed

    pair_id, prepared = admit(live, compressed=True)
    baseline = ROOT / "target/qa-symbol-import/frozen-context"
    task = live["output"] / "worker"
    task.mkdir()
    dump = FIXTURE / "null-read.dmp"
    with live["sessions"].begin() as session:
        demand, blob = seed(
            session,
            workspace="wsp_fixture",
            sha=hashlib.sha256(dump.read_bytes()).hexdigest(),
            size=dump.stat().st_size,
        )
    live["store"].put_file(blob.object_key, dump, "application/octet-stream")
    core = CoreExecutor(live["settings"])
    inspection = prepare_inspection(
        core,
        live["store"],
        workspace_id=blob.workspace_id,
        dump_key=blob.object_key,
        dump_sha256=blob.sha256,
        dump_size=blob.size,
    )
    with live["sessions"].begin() as session:
        register_inspection(session, demand.id, inspection, now=NOW)
        snapshot = snapshot_resolution(session, demand.id)
    planned = prepare_resolution(core, live["store"], snapshot)
    assert planned.manifest["inspector_version"] == "inspect-v0.1"
    assert inspection.inspector_provenance.startswith("core-inspect-v1:binary-sha256:")
    (task / "resolution-manifest.json").write_bytes(planned.manifest_bytes)
    (task / "inspect.json").write_bytes(b"".join(live["store"].stream(inspection.object_key)))
    shutil.copyfile(dump, task / "dump.dmp")
    pair_paths = {}
    for kind in ("pe", "pdb"):
        with live["sessions"]() as session:
            material = select_material(
                session, pair_id, prepared.pe.debug_id, kind, max_locations=32
            )
        pair_paths[kind] = task / f"pair.{kind}"
        materialize_catalog_file(live["store"], material, pair_paths[kind])
    run = json.loads((baseline / "run.json").read_bytes())
    # All policies come from consumer-owned persisted metadata and deployment
    # configuration. The baseline is only a Run envelope until durable adoption.
    local_manifest = {
        "schema_version": "1.0",
        "product": "fixture",
        "version": "qualification",
        "architecture": "x86_64",
        "modules": [
            {
                "code_file": "null_read_target.exe",
                "debug_file": "null_read_target.pdb",
                "role": "entrypoint",
            }
        ],
    }
    source_paths = {}
    source_sha = None
    if source_mode != "none":
        local_manifest["schema_version"] = "2.0"
        local_manifest["source_bundle"] = {
            "schema_version": "1.0",
            "archive": "source.zip",
            "source_root": fixture_source_root(FIXTURE),
        }
        source_path = task / "source.zip"
        with zipfile.ZipFile(source_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(
                ROOT / "scripts/fixtures/null_read_target.cpp",
                "scripts/fixtures/null_read_target.cpp",
            )
        source_metadata = inspect_source_bundle(source_path)
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        live["store"].put_file("fixture/source.zip", source_path, "application/zip")
        if source_mode != "missing":
            source_paths["art_fixture_source"] = source_path
    manifest_path = task / "local-build-manifest.json"
    manifest_path.write_bytes(canonical_bytes(local_manifest))
    manifest_key = "workspaces/wsp_fixture/builds/bld_fixture/manifest.json"
    live["store"].put_file(manifest_key, manifest_path, "application/json")
    for kind in ("pe", "pdb"):
        live["store"].put_file(
            f"fixture/local/{kind}", pair_paths[kind], "application/octet-stream"
        )
    with live["sessions"].begin() as session:
        session.add(
            Build(
                id="bld_fixture",
                workspace_id="wsp_fixture",
                version="qualification",
                manifest_schema_version=local_manifest["schema_version"],
                manifest_object_key=manifest_key,
                source_bundle_config=local_manifest.get("source_bundle"),
            )
        )
        session.flush()
        session.add(
            BuildModule(
                id="mod_target",
                build_id="bld_fixture",
                code_file="null_read_target.exe",
                debug_file="null_read_target.pdb",
                role="entrypoint",
            )
        )
        session.flush()
        for evidence in (prepared.pe, prepared.pdb):
            session.add(
                Artifact(
                    id=f"art_fixture_{evidence.kind}",
                    build_id="bld_fixture",
                    module_id="mod_target",
                    kind=evidence.kind,
                    logical_name=f"local.{evidence.kind}",
                    sha256=evidence.raw_sha256,
                    size=evidence.raw_size,
                    object_key=f"fixture/local/{evidence.kind}",
                    code_id=evidence.code_id,
                    debug_id=evidence.debug_id,
                    verification_status="verified",
                )
            )
        session.flush()
        if source_mode != "none":
            session.add(
                Artifact(
                    id="art_fixture_source",
                    build_id="bld_fixture",
                    kind="source_bundle",
                    logical_name="source.zip",
                    sha256=source_sha,
                    size=source_path.stat().st_size,
                    object_key="fixture/source.zip",
                    verification_status="verified",
                    ingest_metadata=source_metadata,
                )
            )
            session.flush()
        # The same global pair is also consumed by another Workspace. Its Build
        # and distinct source archive must not become local resolution inputs.
        session.add(Workspace(id="wsp_foreign", name="foreign consumer"))
        session.flush()
        foreign_manifest = json.loads(canonical_bytes(local_manifest))
        foreign_manifest["schema_version"] = "2.0"
        foreign_manifest["source_bundle"] = {
            "schema_version": "1.0",
            "archive": "foreign.zip",
            "source_root": fixture_source_root(FIXTURE),
        }
        foreign_source = task / "foreign.zip"
        with zipfile.ZipFile(foreign_source, "w") as archive:
            archive.writestr(
                "scripts/fixtures/null_read_target.cpp",
                "// FOREIGN_WORKSPACE_SOURCE_MUST_NOT_LEAK\n" * 200,
            )
        foreign_key = "workspaces/wsp_foreign/builds/bld_foreign/source.zip"
        source_paths["art_foreign_source"] = foreign_source
        live["store"].put_file(foreign_key, foreign_source, "application/zip")
        foreign_manifest_path = task / "foreign-manifest.json"
        foreign_manifest_path.write_bytes(canonical_bytes(foreign_manifest))
        foreign_manifest_key = "workspaces/wsp_foreign/builds/bld_foreign/manifest.json"
        live["store"].put_file(foreign_manifest_key, foreign_manifest_path, "application/json")
        session.add(
            Build(
                id="bld_foreign",
                workspace_id="wsp_foreign",
                version="qualification",
                manifest_schema_version="2.0",
                manifest_object_key=foreign_manifest_key,
                source_bundle_config=foreign_manifest["source_bundle"],
            )
        )
        session.flush()
        session.add(
            BuildModule(
                id="mod_foreign",
                build_id="bld_foreign",
                code_file="null_read_target.exe",
                debug_file="null_read_target.pdb",
                role="entrypoint",
            )
        )
        session.flush()
        for evidence in (prepared.pe, prepared.pdb):
            session.add(
                Artifact(
                    id=f"art_foreign_{evidence.kind}",
                    build_id="bld_foreign",
                    module_id="mod_foreign",
                    kind=evidence.kind,
                    logical_name=f"local.{evidence.kind}",
                    sha256=evidence.raw_sha256,
                    size=evidence.raw_size,
                    object_key=f"fixture/local/{evidence.kind}",
                    code_id=evidence.code_id,
                    debug_id=evidence.debug_id,
                    verification_status="verified",
                )
            )
        session.add(
            Artifact(
                id="art_foreign_source",
                build_id="bld_foreign",
                kind="source_bundle",
                logical_name="foreign.zip",
                sha256=hashlib.sha256(foreign_source.read_bytes()).hexdigest(),
                size=foreign_source.stat().st_size,
                object_key=foreign_key,
                verification_status="verified",
                ingest_metadata=inspect_source_bundle(foreign_source),
            )
        )
        session.flush()
        foreign_builds = snapshot_workspace_builds(
            session, "wsp_foreign", [module.identity for module in snapshot.modules]
        )
        assert [row["build_id"] for row in json.loads(foreign_builds.metadata)] == ["bld_foreign"]
        local_builds = snapshot_workspace_builds(
            session,
            "wsp_fixture",
            [module.identity for module in snapshot.modules],
        )
        local_policies = snapshot_workspace_policies(session, local_builds)
    build_policy = prepare_build_policy(
        local_builds,
        {"bld_fixture": b"".join(live["store"].stream(manifest_key))},
        schema_root=ROOT / "contracts",
    )
    policies, source_locations = prepare_workspace_policies(
        local_policies,
        build_policy,
        json.loads((task / "inspect.json").read_bytes()),
        public_sources=live["settings"].frozen_public_sources,
        schema_root=SCHEMAS,
    )
    run["policy_snapshots"] = policies
    assert [row["build_id"] for row in build_policy["builds"]] == ["bld_fixture"]
    assert b"bld_foreign" not in canonical_bytes(policies)
    assert b"art_foreign_source" not in canonical_bytes(source_locations)
    run["source_bundle_locations"] = source_locations
    for name, policy in policies.items():
        run["context"][f"{name}_sha256"] = digest(policy)
    run["run_id"] = "run_catalog_material_" + live["output"].name
    run["occurrence_id"], run["demand_id"] = demand.occurrence_id, demand.id
    run["reason"] = "initial"
    run["dump"] = {"object_key": blob.object_key, "sha256": blob.sha256, "size": blob.size}
    run["inspect"] = {"object_key": inspection.object_key, "sha256": inspection.object_sha256}
    run["resolution_manifest"] = {
        "object_key": planned.manifest_object_key,
        "sha256": planned.manifest_sha256,
    }
    run["resolution_evidence_fingerprint"] = planned.resolution_fingerprint
    run["result_facts"]["dump"].update(
        blob_id=blob.id,
        sha256=blob.sha256,
        size=blob.size,
        kind=blob.dump_kind,
        capture_profile=blob.capture_profile,
        dump_timestamp=json.loads((task / "inspect.json").read_bytes())["dump"].get("timestamp"),
        uploaded_at=NOW.isoformat(),
        occurred_at=NOW.isoformat(),
        reported_at=None,
        time_source="uploaded",
    )
    run["context"]["inspector_version"] = planned.manifest["inspector_version"]
    run["context"]["symbolicator_image_digest"] = live["image_id"]
    run["context_sha256"] = digest(run["context"])
    with live["sessions"].begin() as session:
        target = freeze_target(
            session,
            demand.id,
            expected_sequence=planned.change_sequence,
            manifest=planned.manifest,
            manifest_object_key=planned.manifest_object_key,
            context_sha256=run["context_sha256"],
            cause=run["reason"],
            schema_root=SCHEMAS,
            now=NOW,
        )
    run["demand_generation"] = target.generation
    run["idempotency_key"] = frozen_run_key(run)
    encoded = canonical_bytes(run)
    (task / "run.json").write_bytes(encoded)
    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
            "symbolicator_version": live["version"],
        }
    )
    assignment = FrozenAssignment(
        run["run_id"],
        run["occurrence_id"],
        run["context"]["workspace_id"],
        hashlib.sha256(encoded).hexdigest(),
    )
    if source_mode == "corrupt":
        altered = bytearray(source_path.read_bytes())
        altered[len(altered) // 2] ^= 1
        source_path.write_bytes(altered)
    with pytest.raises(CoreExecutionError, match="Staged source is outside frozen policy"):
        FrozenCoreExecutor(settings).execute(
            task,
            assignment,
            {pair_id: (pair_paths["pe"], pair_paths["pdb"])},
            raw_object_prefix=f"qualification/materials/{live['output'].name}",
            source_bundles=source_paths,
        )
    source_paths.pop("art_foreign_source")
    output = FrozenCoreExecutor(settings).execute(
        task,
        assignment,
        {pair_id: (pair_paths["pe"], pair_paths["pdb"])},
        raw_object_prefix=f"qualification/materials/{live['output'].name}",
        source_bundles=source_paths,
    )
    frames = [frame for thread in output.canonical["threads"] for frame in thread["frames"]]
    assert b"FOREIGN_WORKSPACE_SOURCE_MUST_NOT_LEAK" not in output.canonical_bytes
    assert any(
        "trigger_null_read" in (frame.get("function") or "") and frame["line"] == 76
        for frame in frames
    )
    assert any(frame.get("unwind_method") == "call_frame_info" for frame in frames)
    assert output.canonical["build_resolution"]["resolved_build_id"] == "bld_fixture"
    assert output.canonical["build_resolution"]["resolution_method"] == "auto_unique"
    source_diagnostic = json.loads(
        (task / "results/frozen-output/raw/source-bundles.json").read_bytes()
    )
    if source_mode == "valid":
        assert source_diagnostic["status"] == "attached"
        assert source_diagnostic["archive_sha256"] == source_sha
        expected_line = (
            (ROOT / "scripts/fixtures/null_read_target.cpp")
            .read_text(encoding="utf-8")
            .splitlines()[75]
        )
        assert any(
            "trigger_null_read" in (frame.get("function") or "")
            and frame.get("source_context", {}).get("line") == expected_line
            for frame in frames
        )
    elif source_mode in {"corrupt", "missing"}:
        code = (
            "SOURCE_ARCHIVE_HASH_MISMATCH"
            if source_mode == "corrupt"
            else "SOURCE_ARCHIVE_UNAVAILABLE"
        )
        assert source_diagnostic["failure_code"] == code
        assert not any(frame.get("source_context") for frame in frames)
        assert any(
            code in warning["message"] for warning in output.canonical["quality"]["warnings"]
        )
    else:
        assert source_diagnostic["status"] == "not_applicable"
    assert any(
        event["status"] in {200, 206}
        and event["raw_sha256"] == prepared.pdb.raw_sha256
        and event["content_length"] == str(prepared.pdb.raw_size)
        and (
            event["status"] == 200
            or event["content_range"]
            == f"bytes 0-{prepared.pdb.raw_size - 1}/{prepared.pdb.raw_size}"
        )
        for event in live["events"]
    )
    (live["output"] / "result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "case": "frozen_worker_catalog_materials",
                "pair_id": pair_id,
                "run_id": assignment.run_id,
                "run_sha256": assignment.object_sha256,
                "canonical_sha256": hashlib.sha256(output.canonical_bytes).hexdigest(),
                "core_binary_sha256": hashlib.sha256(CORE.read_bytes()).hexdigest(),
                "native_cfi": True,
                "source_mode": source_mode,
                "foreign_build_and_source_excluded": True,
                "source_diagnostic": source_diagnostic,
                "inspector_version": inspection.inspector_version,
                "inspector_provenance": inspection.inspector_provenance,
                "planned_manifest_sha256": planned.manifest_sha256,
                "workspace_build_policy_sha256": digest(build_policy),
                "workspace_role_policy_sha256": digest(policies["role_policy"]),
                "workspace_source_policy_sha256": digest(policies["source_policy"]),
                "workspace_build_metadata_sha256": hashlib.sha256(
                    local_builds.metadata
                ).hexdigest(),
                "build_resolution": output.canonical["build_resolution"],
                "boundary": (
                    "real demand, catalog plan and persisted Workspace policies; "
                    "native source cases included; "
                    "no durable Run/task consumer or Current promotion"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("with_source", [False, True])
def test_native_publications_preserve_sealed_history(live, owned_redis, with_source):
    from .native_publication_roles import qualify_publications

    qualify_publications(live, owned_redis[0], FIXTURE, with_source=with_source)


@pytest.mark.parametrize("declare_owned", [True, False])
def test_unknown_fault_with_owned_caller(live, owned_redis, declare_owned):
    from .native_unknown_fault import qualify_unknown_fault

    qualify_unknown_fault(
        live,
        owned_redis[0],
        ROOT / "fixtures/qai-c08-cross-module/generated",
        declare_owned=declare_owned,
    )


def test_late_catalog_pair_updates_existing_native_reports(live, owned_redis):
    import time

    from crashcap_api.app import create_app
    from crashcap_api.models import (
        AnalysisDemand,
        AnalysisExecutionSlot,
        AnalysisRun,
        CurrentDecision,
        Occurrence,
        TaskIntent,
        Upload,
        utcnow,
    )
    from crashcap_api.queueing import DramatiqTaskDispatcher
    from crashcap_api.services.analysis_demands import fanout_next
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
    from crashcap_worker.outbox_relay import relay_once
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    workspace_count = int(os.environ.get("QAI_LATE_PAIR_WORKSPACES", "2"))
    page_size = 200 if workspace_count > 200 else 1

    def progress(phase, completed):
        (live["output"] / "late-pair-progress.json").write_text(
            json.dumps({"phase": phase, "completed": completed, "workspaces": workspace_count}),
            encoding="utf-8",
        )

    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 1,
            "automatic_analysis_capacity": 1,
            "automatic_analysis_enumeration_limit": page_size,
            "catalog_reviews_enabled": True,
            "result_reviews_enabled": True,
            "workspace_module_roles_enabled": True,
            "symbol_projection_mode": "strict-writer",
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
            "symbolicator_version": live["version"],
        }
    )
    payload = (FIXTURE / "null-read.dmp").read_bytes()
    occurrences = {}
    upload_ids = []
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            for index in range(workspace_count):
                response = client.post("/api/v1/workspaces", json={"name": f"late-pair-{index}"})
                assert response.status_code == 201, response.text
                workspace_id = response.json()["id"]
                response = client.post(
                    f"/api/v1/workspaces/{workspace_id}/dumps/uploads:init",
                    json={"filename": "null-read.dmp", "size": len(payload)},
                )
                assert response.status_code == 201, response.text
                upload_id = response.json()["upload_id"]
                upload_ids.append(upload_id)
                with live["sessions"]() as session:
                    key = session.get(Upload, upload_id).object_key
                live["store"].put_bytes(key, payload, "application/octet-stream")
                response = client.post(f"/api/v1/uploads/{upload_id}/complete", json={})
                assert response.status_code == 200, response.text
                assert relay_once(
                    live["sessions"], app.state.dispatcher, settings, owner_id="upload-native-relay"
                )
                delivery_tests.consume_in_fresh_process(
                    settings, live["sessions"], "verify", timeout_seconds=90
                )
                response = client.get(f"/api/v1/uploads/{upload_id}")
                assert response.json()["verification_status"] == "ACCEPTED", response.text
                with live["sessions"]() as session:
                    occurrence = session.scalar(
                        select(Occurrence).where(Occurrence.workspace_id == workspace_id)
                    )
                    demand = session.scalar(
                        select(AnalysisDemand).where(AnalysisDemand.occurrence_id == occurrence.id)
                    )
                    assert demand is not None and demand.state == "preparing"
                    assert (
                        session.scalar(
                            select(AnalysisRun).where(AnalysisRun.occurrence_id == occurrence.id)
                        )
                        is None
                    )
                    occurrences[demand.id] = occurrence.id
                progress("accepted_uploads", index + 1)
    finally:
        app.state.dispatcher.broker.close()
    planner = AutomaticAnalysisPlanner(
        settings, live["sessions"], live["store"], CoreExecutor(settings)
    )
    dispatcher = DramatiqTaskDispatcher(settings)

    def execute_round(now, phase="analysis", count=None):
        results = {}
        for _ in range(workspace_count if count is None else count):
            assert planner.run_once(owner_id="late-pair-planner", now=max(now, utcnow())) == 1
            with live["sessions"]() as session:
                slot = session.scalar(select(AnalysisExecutionSlot))
                demand_id, run_id = slot.demand_id, slot.run_id
                assert demand_id not in results
                intent = session.scalar(select(TaskIntent).where(TaskIntent.logical_key == run_id))
                queue = intent.message["queue"]
            assert relay_once(live["sessions"], dispatcher, settings, owner_id="late-pair-relay")
            delivery_tests.consume_in_fresh_process(
                settings, live["sessions"], queue, timeout_seconds=90
            )
            with live["sessions"]() as session:
                run = session.get(AnalysisRun, run_id)
                assert run.status in {"COMPLETE", "PARTIAL"}, (
                    run.status,
                    run.error_code,
                    run.error_detail,
                )
                report_bytes = b"".join(live["store"].stream(run.result_object_key))
                results[demand_id] = {
                    "run_id": run_id,
                    "sha256": hashlib.sha256(report_bytes).hexdigest(),
                    "object_key": run.result_object_key,
                    "canonical": json.loads(report_bytes),
                    "decision": session.get(CurrentDecision, run_id).decision,
                    "reason": session.get(CurrentDecision, run_id).reason,
                }
            progress(phase, len(results))
        return results

    try:
        before = execute_round(utcnow(), "initial_reports")
        for result in before.values():
            assert not any(
                "trigger_null_read" in (frame.get("function") or "")
                for thread in result["canonical"]["threads"]
                for frame in thread["frames"]
            )
        import_app = create_app(settings)
        try:
            with TestClient(import_app) as client:
                files = {
                    kind: FIXTURE / name
                    for kind, name in (
                        ("pe", "null_read_target.exe"),
                        ("pdb", "null_read_target.pdb"),
                    )
                }
                claims = {
                    kind: {
                        "name": path.name,
                        "raw_size": path.stat().st_size,
                        "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for kind, path in files.items()
                }
                response = client.post(
                    "/api/v2/symbol-imports",
                    json={
                        "idempotency_key": "late-native-pair",
                        "source_label": "native API qualification",
                        "pairs": [{"client_pair_id": "pair-1", **claims}],
                    },
                )
                assert response.status_code == 201, response.text
                batch = response.json()
                import_id = batch["import_id"]
                item_id = batch["items"][0]["item_id"]
                item_path = f"/api/v2/symbol-imports/{import_id}/items/{item_id}"
                for kind, path in files.items():
                    response = client.put(item_path + "/files/" + kind, content=path.read_bytes())
                    assert response.status_code == 200, response.text
                response = client.post(item_path + "/complete")
                assert response.status_code == 202, response.text
                assert relay_once(
                    live["sessions"],
                    import_app.state.dispatcher,
                    settings,
                    owner_id="import-native-relay",
                )
                delivery_tests.consume_in_fresh_process(
                    settings, live["sessions"], "ingest", timeout_seconds=90
                )
                response = client.get(f"/api/v2/symbol-imports/{import_id}")
                item = response.json()["items"][0]
                assert item["state"] == "available", item
                pair_id = item["pair_id"]
        finally:
            import_app.state.dispatcher.broker.close()
        affected = set()
        for _ in range(10):
            with live["sessions"].begin() as session:
                page = fanout_next(session, now=utcnow(), limit=page_size)
                affected.update(page.affected)
            if page.caught_up:
                break
        else:
            pytest.fail("catalog fanout did not finish")
        assert affected == set(occurrences.values())
        with live["sessions"]() as session:
            due = max(session.get(AnalysisDemand, key).not_before for key in occurrences)
        time.sleep(max(0, (due - utcnow()).total_seconds()))
        after = execute_round(utcnow(), "updated_reports")
        for demand_id, result in after.items():
            assert result["run_id"] != before[demand_id]["run_id"]
            assert any(
                "trigger_null_read" in (frame.get("function") or "") and frame["line"] == 76
                for thread in result["canonical"]["threads"]
                for frame in thread["frames"]
            )
            assert result["decision"] == "promote"
            with live["sessions"]() as session:
                assert (
                    session.get(Occurrence, occurrences[demand_id]).current_run_id
                    == result["run_id"]
                )
                assert session.get(AnalysisDemand, demand_id).state == "updated"
            assert (
                hashlib.sha256(
                    b"".join(live["store"].stream(before[demand_id]["object_key"]))
                ).hexdigest()
                == before[demand_id]["sha256"]
            )
        assert planner.run_once(owner_id="late-pair-idle", now=utcnow()) == 0
        reviews = []
        result_reviews = []
        rounds = {"imported": after}
        review_app = create_app(settings)
        try:
            with TestClient(review_app) as client:
                review_states = ((1, "withdrawn"), (2, "active")) if workspace_count == 2 else ()
                for version, state in review_states:
                    if state == "active":
                        origins = client.get(f"/api/v2/symbol-catalog/pairs/{pair_id}/origins")
                        assert origins.status_code == 200, origins.text
                        version = origins.json()["qualification_version"]
                    response = client.post(
                        f"/api/v2/symbol-catalog/pairs/{pair_id}/reviews",
                        json={
                            "expected_version": version,
                            "state": state,
                            "reason": "Isolated native recovery qualification",
                            "reviewer": "Fixture provider",
                            "evidence": "Generated fixture; logical review recovery only.",
                            "idempotency_key": f"native-review-{state}",
                        },
                    )
                    assert response.status_code == 200, response.text
                    reviews.append(response.json())
                    touched = set()
                    for _ in range(10):
                        with live["sessions"].begin() as session:
                            page = fanout_next(session, now=utcnow(), limit=1)
                            touched.update(page.affected)
                        if page.caught_up:
                            break
                    else:
                        pytest.fail("review fanout did not finish")
                    assert touched == set(occurrences.values())
                    with live["sessions"]() as session:
                        due = max(
                            session.get(AnalysisDemand, key).not_before for key in occurrences
                        )
                    time.sleep(max(0, (due - utcnow()).total_seconds()))
                    rounds[state] = execute_round(utcnow())
                    for demand_id, result in rounds[state].items():
                        previous = [before, after] + (
                            [rounds["withdrawn"]] if state == "active" else []
                        )
                        assert all(result["run_id"] != old[demand_id]["run_id"] for old in previous)
                        has_function = any(
                            "trigger_null_read" in (frame.get("function") or "")
                            for thread in result["canonical"]["threads"]
                            for frame in thread["frames"]
                        )
                        assert has_function == (state == "active")
                        assert result["decision"] == (
                            "promote" if state == "active" else "incomparable"
                        ), result
                        with live["sessions"]() as session:
                            assert session.get(
                                Occurrence, occurrences[demand_id]
                            ).current_run_id == (
                                result["run_id"]
                                if state == "active"
                                else after[demand_id]["run_id"]
                            )
                        for old in previous:
                            assert (
                                hashlib.sha256(
                                    b"".join(live["store"].stream(old[demand_id]["object_key"]))
                                ).hexdigest()
                                == old[demand_id]["sha256"]
                            )
                    assert planner.run_once(owner_id="review-idle", now=utcnow()) == 0
                    if state == "withdrawn":
                        from .result_review_native_correction import review_withdrawn_candidates

                        review_occurrences = dict(occurrences)
                        if os.environ.get("CRASHCAP_QA_CORRECTION_BROWSER") == "1":
                            from .result_review_browser import run_browser_review

                            demand_id = next(iter(review_occurrences))
                            occurrence_id = review_occurrences.pop(demand_id)
                            with live["sessions"]() as session:
                                workspace_id = session.get(Occurrence, occurrence_id).workspace_id
                            run_browser_review(
                                settings,
                                live,
                                workspace_id,
                                occurrence_id,
                                after[demand_id]["run_id"],
                                rounds[state][demand_id]["run_id"],
                                decision="correct",
                            )
                        result_reviews = review_withdrawn_candidates(
                            client,
                            live,
                            settings,
                            review_occurrences,
                            after,
                            rounds[state],
                            reviews[-1],
                        )
        finally:
            review_app.state.dispatcher.broker.close()
        if workspace_count == 2:
            from .result_review_native_role import qualify_native_role

            qualify_native_role(
                settings, live, occurrences, rounds["active"], dispatcher, execute_round
            )
            from .result_review_native_dependency import qualify_native_dependency
            from .result_review_native_expiry import qualify_native_expiry

            qualify_native_dependency(settings, live, occurrences, dispatcher, execute_round)
            qualify_native_expiry(settings, live, occurrences, pair_id, planner)
        (live["output"] / "late-pair-result.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "workspace_count": workspace_count,
                    "enumeration_page_size": page_size,
                    "pair_id": pair_id,
                    "affected": sorted(affected),
                    "upload_ids": upload_ids,
                    "import_id": import_id,
                    "before": {key: value["run_id"] for key, value in before.items()},
                    "after": {key: value["run_id"] for key, value in after.items()},
                    "reviews": reviews,
                    "result_reviews": result_reviews,
                    "review_rounds": {
                        state: {
                            key: {
                                field: value[field]
                                for field in ("run_id", "sha256", "decision", "reason")
                            }
                            for key, value in results.items()
                        }
                        for state, results in rounds.items()
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        dispatcher.broker.close()


@pytest.fixture
def legacy_live(pg):
    # A separate service/cache prevents legacy source state leaking into frozen analysis.
    yield from live.__wrapped__(pg)


def test_legacy_current_preserved_for_native_candidate(live, legacy_live, owned_redis):
    from crashcap_api.app import create_app
    from crashcap_api.models import (
        AnalysisDemand,
        AnalysisExecutionSlot,
        AnalysisRun,
        CurrentDecision,
        Occurrence,
        TaskIntent,
        Upload,
        utcnow,
    )
    from crashcap_api.queueing import DramatiqTaskDispatcher
    from crashcap_api.services.analysis_demands import ensure_demand
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
    from crashcap_worker.outbox_relay import relay_once
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    legacy_settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "symbolicator_url": legacy_live["endpoint"],
            "symbolicator_version": legacy_live["version"],
        }
    )
    app = create_app(legacy_settings)
    payload = (FIXTURE / "null-read.dmp").read_bytes()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/workspaces", json={"name": "legacy-current"})
            assert response.status_code == 201, response.text
            workspace_id = response.json()["id"]
            response = client.post(
                f"/api/v1/workspaces/{workspace_id}/dumps/uploads:init",
                json={"filename": "null-read.dmp", "size": len(payload)},
            )
            assert response.status_code == 201, response.text
            upload_id = response.json()["upload_id"]
            with live["sessions"]() as session:
                key = session.get(Upload, upload_id).object_key
            live["store"].put_bytes(key, payload, "application/octet-stream")
            response = client.post(f"/api/v1/uploads/{upload_id}/complete", json={})
            assert response.status_code == 200, response.text
            assert relay_once(
                live["sessions"],
                app.state.dispatcher,
                legacy_settings,
                owner_id="legacy-upload-relay",
            )
            delivery_tests.consume_in_fresh_process(
                legacy_settings,
                live["sessions"],
                "verify",
                timeout_seconds=90,
            )
            with live["sessions"]() as session:
                occurrence = session.scalar(
                    select(Occurrence).where(Occurrence.workspace_id == workspace_id)
                )
                occurrence_id = occurrence.id
                old_run = session.scalar(
                    select(AnalysisRun).where(AnalysisRun.occurrence_id == occurrence_id)
                )
                assert old_run is not None and old_run.schema_version == "1.0"
                old_run_id = old_run.id
                intent = session.scalar(
                    select(TaskIntent).where(TaskIntent.logical_key == old_run_id)
                )
                queue = intent.message["queue"]
            assert relay_once(
                live["sessions"],
                app.state.dispatcher,
                legacy_settings,
                owner_id="legacy-analysis-relay",
            )
            delivery_tests.consume_in_fresh_process(
                legacy_settings,
                live["sessions"],
                queue,
                timeout_seconds=90,
            )
    finally:
        app.state.dispatcher.broker.close()
    with live["sessions"]() as session:
        old_run = session.get(AnalysisRun, old_run_id)
        assert old_run.status in {"COMPLETE", "PARTIAL"}, (
            old_run.status,
            old_run.error_code,
            old_run.error_detail,
        )
        assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
        old_key = old_run.result_object_key
        old_bytes = b"".join(live["store"].stream(old_key))
        assert json.loads(old_bytes)["schema_version"] == "1.0"
    pair_id, _ = admit(live, compressed=True)
    settings = Settings.model_validate(
        {
            **legacy_settings.model_dump(),
            "automatic_analysis_enabled": True,
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
        }
    )
    with live["sessions"].begin() as session:
        demand_id = ensure_demand(session, occurrence_id, now=utcnow()).id
    planner = AutomaticAnalysisPlanner(
        settings, live["sessions"], live["store"], CoreExecutor(settings)
    )
    dispatcher = DramatiqTaskDispatcher(settings)
    try:
        assert planner.run_once(owner_id="legacy-continuation", now=utcnow()) == 1
        with live["sessions"]() as session:
            slot = session.scalar(select(AnalysisExecutionSlot))
            run_id = slot.run_id
            intent = session.scalar(select(TaskIntent).where(TaskIntent.logical_key == run_id))
            queue = intent.message["queue"]
        assert relay_once(live["sessions"], dispatcher, settings, owner_id="legacy-new-relay")
        missing_run_id = run_id
        live["store"].delete(old_key)
        try:
            delivery_tests.consume_in_fresh_process(
                settings, live["sessions"], queue, timeout_seconds=90
            )
            with live["sessions"]() as session:
                failed = session.get(AnalysisRun, missing_run_id)
                assert failed.status == "FAILED"
                assert failed.error_code == "CURRENT_EVIDENCE_UNAVAILABLE"
                assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
                assert session.get(CurrentDecision, missing_run_id) is None
                assert session.scalar(select(AnalysisExecutionSlot)) is None
                demand = session.get(AnalysisDemand, demand_id)
                assert demand.state == "retry_wait"
                assert demand.retry_attempt == 1
                retry_due = demand.not_before
                assert retry_due is not None
        finally:
            live["store"].put_bytes(old_key, old_bytes, "application/json")
        assert planner.run_once(owner_id="legacy-restored", now=retry_due) == 1
        with live["sessions"]() as session:
            slot = session.scalar(select(AnalysisExecutionSlot))
            run_id = slot.run_id
            assert run_id != missing_run_id
            intent = session.scalar(select(TaskIntent).where(TaskIntent.logical_key == run_id))
            queue = intent.message["queue"]
        assert relay_once(live["sessions"], dispatcher, settings, owner_id="legacy-restored-relay")
        delivery_tests.consume_in_fresh_process(
            settings,
            live["sessions"],
            queue,
            timeout_seconds=90,
        )
        with live["sessions"]() as session:
            run = session.get(AnalysisRun, run_id)
            assert run.status in {"COMPLETE", "PARTIAL"}, (
                run.status,
                run.error_code,
                run.error_detail,
            )
            candidate_bytes = b"".join(live["store"].stream(run.result_object_key))
            candidate = json.loads(candidate_bytes)
            assert candidate["schema_version"] == "1.1"
            assert any(
                "trigger_null_read" in (frame.get("function") or "")
                for thread in candidate["threads"]
                for frame in thread["frames"]
            )
            decision = session.get(CurrentDecision, run_id)
            assert decision.decision == "incomparable"
            # This is the first Demand after migration, not a catalog refresh
            # of an existing frozen target. It requires an explicit transition.
            assert run.run_spec["reason"] == "initial"
            assert decision.reason == "transition_requires_review"
            assert decision.current_evidence["provenance"] == "insufficient"
            assert decision.current_evidence["dump_sha256"] == hashlib.sha256(payload).hexdigest()
            assert (
                decision.current_evidence["dump_sha256"]
                == decision.candidate_evidence["dump_sha256"]
            )
            assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
            assert session.get(AnalysisDemand, demand_id).state == "needs_review"
            assert session.scalar(select(AnalysisExecutionSlot)) is None
            assert b"".join(live["store"].stream(old_key)) == old_bytes
            result = {
                "status": "PASS",
                "occurrence_id": occurrence_id,
                "pair_id": pair_id,
                "old_run_id": old_run_id,
                "candidate_run_id": run_id,
                "old_canonical_sha256": hashlib.sha256(old_bytes).hexdigest(),
                "candidate_canonical_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "decision": decision.decision,
                "reason": decision.reason,
            }
        from crashcap_api.services.result_reviews import (
            load_result_review_evidence,
            prepare_result_review,
        )

        loaded_old = load_result_review_evidence(
            old_run,
            live["store"],
            hashlib.sha256(old_bytes).hexdigest(),
            initial_decision=None,
            schema_root=ROOT / "contracts",
        )
        loaded_new = load_result_review_evidence(
            run,
            live["store"],
            hashlib.sha256(candidate_bytes).hexdigest(),
            initial_decision=decision,
            schema_root=ROOT / "contracts",
        )
        assert loaded_old.canonical_bytes == old_bytes
        assert loaded_new.canonical_bytes == candidate_bytes
        assert loaded_old.evidence.provenance == "insufficient"
        assert loaded_new.evidence.provenance == "native_1.1"
        assert loaded_old.evidence.dump_sha256 == loaded_new.evidence.dump_sha256
        result["review_evidence_loaded_from_objects"] = True
        result["missing_current_worker_recovery"] = {
            "failed_run_id": missing_run_id,
            "error_code": "CURRENT_EVIDENCE_UNAVAILABLE",
            "retry_state": "retry_wait",
            "restored_candidate_run_id": run_id,
            "current_preserved": True,
        }
        from crashcap_api.errors import ApiError
        from crashcap_api.storage import ObjectNotFoundError

        # Only mutate this test's owned object; restore its exact bytes even on failure.
        fault_checks = []
        for fault, damaged in (
            ("missing", None),
            ("truncated", old_bytes[: len(old_bytes) // 2]),
            ("same_length_corruption", bytes([old_bytes[0] ^ 1]) + old_bytes[1:]),
        ):
            try:
                if damaged is None:
                    live["store"].delete(old_key)
                else:
                    live["store"].put_bytes(old_key, damaged, "application/json")
                expected_error = ObjectNotFoundError if damaged is None else ApiError
                with pytest.raises(expected_error) as rejected:
                    load_result_review_evidence(
                        old_run,
                        live["store"],
                        hashlib.sha256(old_bytes).hexdigest(),
                        initial_decision=None,
                        schema_root=ROOT / "contracts",
                    )
                if damaged is not None:
                    assert rejected.value.code == "REVIEW_OBJECT_INVALID"
                with live["sessions"]() as session:
                    assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
                    assert session.get(AnalysisRun, old_run_id).result_object_key == old_key
                fault_checks.append({"fault": fault, "rejected": True, "current_preserved": True})
            finally:
                live["store"].put_bytes(old_key, old_bytes, "application/json")
            assert b"".join(live["store"].stream(old_key)) == old_bytes
        result["owned_legacy_object_fault_checks"] = fault_checks
        prepared_review = prepare_result_review(
            live["sessions"],
            live["store"],
            occurrence_id,
            {
                "schema_version": "result-review-request-v1",
                "idempotency_key": "native-engine-review",
                "current_run_id": old_run_id,
                "candidate_run_id": run_id,
                "current_canonical_sha256": hashlib.sha256(old_bytes).hexdigest(),
                "candidate_canonical_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "cause": "engine_upgrade",
                "reviewed_by": "qualification declaration",
                "rationale": "Review actual 1.0 and 1.1 native reports",
                "basis_reviews": [],
            },
            schema_root=ROOT / "contracts",
        )
        assert prepared_review.current.canonical_bytes == old_bytes
        assert prepared_review.candidate.canonical_bytes == candidate_bytes
        assert (
            hashlib.sha256(prepared_review.audit_bytes).hexdigest() == prepared_review.audit_sha256
        )
        result["prepared_review_id"] = prepared_review.id
        result["prepared_review_audit_sha256"] = prepared_review.audit_sha256
        reader_settings = Settings.model_validate(
            {
                **settings.model_dump(),
                "automatic_analysis_enabled": False,
                "frozen_analysis_enabled": False,
                "evidence_promotion_enabled": False,
                "frozen_core_enabled": False,
                "symbol_imports_enabled": False,
                "catalog_reviews_enabled": False,
                "workspace_module_roles_enabled": False,
            }
        )
        reader_app = create_app(reader_settings)
        try:
            with TestClient(reader_app) as client:
                capabilities = client.get("/api/v2/capabilities")
                assert capabilities.status_code == 200, capabilities.text
                assert capabilities.json()["enabled_writes"] == []
                checks = []
                for url, expected_bytes in (
                    (f"/api/v1/occurrences/{occurrence_id}/analysis", old_bytes),
                    (f"/api/v2/occurrences/{occurrence_id}/analysis", old_bytes),
                    (f"/api/v2/runs/{old_run_id}/analysis", old_bytes),
                    (f"/api/v2/runs/{run_id}/analysis", candidate_bytes),
                    (
                        f"/api/v2/occurrences/{occurrence_id}/analysis?run_id={run_id}",
                        candidate_bytes,
                    ),
                ):
                    response = client.get(url)
                    assert response.status_code == 200, response.text
                    assert response.content == expected_bytes
                    checks.append(url)
                response = client.get(
                    f"/api/v1/occurrences/{occurrence_id}/analysis",
                    params={"run_id": run_id},
                )
                assert response.status_code == 409, response.text
                assert response.json()["error"]["code"] == "CANONICAL_VERSION_UNSUPPORTED"
                result["writes_disabled_reader_checks"] = checks
                result["v1_rejects_1_1"] = True
        finally:
            reader_app.state.dispatcher.broker.close()
        with live["sessions"]() as session:
            assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
            assert (
                len(
                    session.scalars(
                        select(AnalysisRun).where(AnalysisRun.occurrence_id == occurrence_id)
                    ).all()
                )
                == 3
            )
        from crashcap_api.models import GroupMembership, ResultReview
        from crashcap_api.services import result_reviews as review_service

        review_settings = settings.model_copy(update={"result_reviews_enabled": True})
        original_projection = review_service.update_current_projections

        def fail_after_projection(*args, **kwargs):
            original_projection(*args, **kwargs)
            raise RuntimeError("injected review projection failure")

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(review_service, "update_current_projections", fail_after_projection)
            with (
                pytest.raises(RuntimeError, match="injected review projection failure"),
                live["sessions"].begin() as session,
            ):
                review_service.commit_result_review(session, prepared_review, review_settings)
        with live["sessions"]() as session:
            assert session.get(ResultReview, prepared_review.id) is None
            assert session.get(Occurrence, occurrence_id).current_run_id == old_run_id
            assert session.get(CurrentDecision, run_id).decision == "incomparable"
        if os.environ.get("CRASHCAP_QA_REVIEW_BROWSER") == "1":
            from .result_review_browser import run_browser_review

            run_browser_review(
                review_settings, live, workspace_id, occurrence_id, old_run_id, run_id
            )
            return
        review_app = create_app(review_settings)
        review_path = (
            f"/api/v2/workspaces/{workspace_id}/occurrences/{occurrence_id}/result-reviews"
        )
        request_body = json.loads(prepared_review.bound.request_bytes)
        try:
            with TestClient(review_app) as client:
                assert (
                    "result_reviews"
                    in (client.get("/api/v2/capabilities").json()["enabled_writes"])
                )
                assert (
                    client.post(
                        review_path.replace(workspace_id, "wsp_other"), json=request_body
                    ).status_code
                    == 404
                )
                from concurrent.futures import ThreadPoolExecutor
                from threading import Barrier, Event

                from crashcap_api import routes_result_reviews

                http_fault_checks = []
                for fault, damaged, status, code in (
                    ("missing", None, 503, "STORAGE_ERROR"),
                    ("truncated", old_bytes[: len(old_bytes) // 2], 409, "REVIEW_OBJECT_INVALID"),
                    (
                        "same_length_corruption",
                        bytes([old_bytes[0] ^ 1]) + old_bytes[1:],
                        409,
                        "REVIEW_OBJECT_INVALID",
                    ),
                ):
                    try:
                        if damaged is None:
                            live["store"].delete(old_key)
                        else:
                            live["store"].put_bytes(old_key, damaged, "application/json")
                        rejected_response = client.post(review_path, json=request_body)
                        assert rejected_response.status_code == status, rejected_response.text
                        assert rejected_response.json()["error"]["code"] == code
                        with live["sessions"]() as session:
                            assert (
                                session.get(Occurrence, occurrence_id).current_run_id == old_run_id
                            )
                            assert session.get(CurrentDecision, run_id).decision == "incomparable"
                            assert session.scalar(
                                select(ResultReview).where(
                                    ResultReview.occurrence_id == occurrence_id
                                )
                            ) is None
                        http_fault_checks.append(
                            {"fault": fault, "status": status, "code": code,
                             "current_preserved": True, "review_absent": True}
                        )
                    finally:
                        live["store"].put_bytes(old_key, old_bytes, "application/json")
                    assert b"".join(live["store"].stream(old_key)) == old_bytes
                result["owned_legacy_http_fault_checks"] = http_fault_checks

                original_prepare = routes_result_reviews.prepare_result_review
                ready = Barrier(3, timeout=30)
                committed = Event()
                competing_body = {**request_body, "idempotency_key": "concurrent-other-review"}

                def prepare_together(*args, **kwargs):
                    prepared = original_prepare(*args, **kwargs)
                    ready.wait()
                    if (
                        json.loads(prepared.bound.request_bytes)["idempotency_key"]
                        == competing_body["idempotency_key"]
                    ):
                        assert committed.wait(timeout=30), "winning review did not finish"
                    return prepared

                def submit_winner():
                    response = client.post(review_path, json=request_body)
                    if response.status_code == 200:
                        committed.set()
                    return response

                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(routes_result_reviews, "prepare_result_review", prepare_together)
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        pending = [pool.submit(submit_winner) for _ in range(2)]
                        competitor = pool.submit(client.post, review_path, json=competing_body)
                        responses = [future.result(timeout=45) for future in pending]
                        competing_response = competitor.result(timeout=45)
                submitted = responses[0]
                assert submitted.status_code == 200, submitted.text
                review_json = submitted.json()
                assert responses[1].status_code == 200, responses[1].text
                assert responses[1].json() == review_json
                assert competing_response.status_code == 409, competing_response.text
                assert competing_response.json()["error"]["code"] == "REVIEW_TARGET_CHANGED"
                assert (review_json["decision"], review_json["reason"]) == (
                    "promote",
                    "reviewed_transition",
                )

                # Replay must not touch storage or re-prepare a changed Current.
                def unavailable(*args, **kwargs):
                    raise AssertionError("replay must not prepare another review")

                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(routes_result_reviews, "prepare_result_review", unavailable)
                    replay_response = client.post(review_path, json=request_body)
                    assert replay_response.status_code == 200, replay_response.text
                    assert replay_response.json() == review_json
                    conflict = client.post(
                        review_path, json={**request_body, "rationale": "different request"}
                    )
                    assert conflict.status_code == 409
                    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
                stale = client.post(
                    review_path, json={**request_body, "idempotency_key": "new-stale-request"}
                )
                assert stale.status_code == 409
                assert stale.json()["error"]["code"] == "REVIEW_TARGET_CHANGED"
                assert client.get(review_path).json()["items"] == [review_json]
                assert client.get(f"{review_path}/{review_json['id']}").json() == review_json
                evidence_path = f"{review_path}/{review_json['id']}/evidence"
                audit_response = client.get(evidence_path)
                assert audit_response.status_code == 200, audit_response.text
                assert (
                    hashlib.sha256(audit_response.content).hexdigest()
                    == review_json["audit_sha256"]
                )
                assert audit_response.json()["request"] == request_body
                assert (
                    client.get(evidence_path.replace(workspace_id, "wsp_other")).status_code == 404
                )
                with pytest.MonkeyPatch.context() as patch:
                    patch.setattr(review_app.state.store, "stream", lambda key: iter([b"corrupt"]))
                    corrupt = client.get(evidence_path)
                    assert corrupt.status_code == 409
                    assert corrupt.json()["error"]["code"] == "REVIEW_OBJECT_INVALID"
                assert client.get(review_path.replace(workspace_id, "wsp_other")).status_code == 404
                review_app.state.settings = review_settings.model_copy(
                    update={"result_reviews_enabled": False}
                )
                assert client.post(review_path, json=request_body).status_code == 503
                assert client.get(review_path).json()["items"] == [review_json]
                assert (
                    "result_reviews"
                    not in (client.get("/api/v2/capabilities").json()["enabled_writes"])
                )
                assert client.get(evidence_path).content == audit_response.content
        finally:
            review_app.state.dispatcher.broker.close()
        with live["sessions"].begin() as session:
            replay = review_service.commit_result_review(session, prepared_review, review_settings)
            assert replay.id == review_json["id"]
        with live["sessions"]() as session:
            assert session.get(Occurrence, occurrence_id).current_run_id == run_id
            assert candidate["fingerprints"]["exact"] is None
            assert session.get(GroupMembership, occurrence_id) is None
            assert session.get(CurrentDecision, run_id).decision == "incomparable"
            assert session.get(AnalysisDemand, demand_id).state == "updated"
            assert len(session.scalars(select(ResultReview)).all()) == 1
            assert b"".join(live["store"].stream(old_key)) == old_bytes
        result["review_committed"] = review_json["id"]
        result["review_http_replay_verified"] = True
        result["review_concurrent_identical_requests_verified"] = True
        result["review_prepared_competitor_rejected"] = True
        result["review_audit_readback_verified"] = True
        result["review_projection_rollback_verified"] = True
        from crashcap_worker.core_runner import CoreExecutionError
        from crashcap_worker.processor import WorkerProcessor

        processor = WorkerProcessor(settings, live["sessions"], live["store"], dispatcher)
        assert processor._prepare_current_evidence(occurrence_id).run_id == run_id
        with live["sessions"]() as session:
            current_run = session.get(AnalysisRun, run_id)
            current_keys = {
                "canonical": current_run.result_object_key,
                "inspect": current_run.run_spec["inspect"]["object_key"],
            }
        integrity_checks = []
        for object_kind, object_key in current_keys.items():
            original = b"".join(live["store"].stream(object_key))
            try:
                corrupted = bytes([original[0] ^ 1]) + original[1:]
                live["store"].put_bytes(object_key, corrupted, "application/json")
                with pytest.raises(CoreExecutionError) as rejected:
                    processor._prepare_current_evidence(occurrence_id)
                assert rejected.value.code == "CURRENT_EVIDENCE_INVALID"
                with live["sessions"]() as session:
                    assert session.get(Occurrence, occurrence_id).current_run_id == run_id
                    assert len(session.scalars(select(ResultReview)).all()) == 1
                integrity_checks.append(
                    {"object": object_kind, "code": rejected.value.code, "current_preserved": True}
                )
            finally:
                live["store"].put_bytes(object_key, original, "application/json")
            assert processor._prepare_current_evidence(occurrence_id).run_id == run_id
        result["native_current_integrity_checks"] = integrity_checks
        (live["output"] / "legacy-current-result.json").write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
    finally:
        dispatcher.broker.close()


def test_automatic_planner_to_real_worker_promotes_current(live, owned_redis, pg):
    from alembic import command
    from crashcap_api.ids import new_id
    from crashcap_api.models import (
        AnalysisDemand,
        AnalysisExecutionSlot,
        AnalysisRun,
        AnalysisSummary,
        CurrentDecision,
        DumpBlob,
        Occurrence,
        TaskIntent,
        Workspace,
        utcnow,
    )
    from crashcap_api.queueing import DramatiqTaskDispatcher
    from crashcap_api.services.analysis_demands import ensure_demand
    from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
    from crashcap_worker.outbox_relay import relay_once
    from sqlalchemy import select

    pair_id, _ = admit(live, compressed=True)
    workspace_count = int(os.environ.get("QAI_AUTOMATIC_WORKSPACES", "4"))
    resident_restart = os.environ.get("QAI_AUTOMATIC_RESIDENT_RESTART") == "1"
    assert workspace_count in {4, 201}
    enumeration_limit = 200 if workspace_count == 201 else 1
    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 1,
            "automatic_analysis_capacity": 1,
            "automatic_analysis_enumeration_limit": enumeration_limit,
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
            "symbolicator_version": live["version"],
        }
    )
    payload = (FIXTURE / "null-read.dmp").read_bytes()
    uploaded_at = utcnow()
    expected = {}
    for _ in range(workspace_count):
        workspace_id, blob_id = new_id("wsp"), new_id("blob")
        dump_key = f"qualification/automatic/{blob_id}/dump.dmp"
        live["store"].put_bytes(dump_key, payload, "application/octet-stream")
        with live["sessions"].begin() as session:
            session.add(Workspace(id=workspace_id, name=workspace_id))
            session.flush()
            session.add(
                DumpBlob(
                    id=blob_id,
                    workspace_id=workspace_id,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size=len(payload),
                    object_key=dump_key,
                    verification_status="ACCEPTED",
                )
            )
            session.flush()
            occurrence_id = new_id("occ")
            session.add(
                Occurrence(
                    id=occurrence_id,
                    workspace_id=workspace_id,
                    dump_blob_id=blob_id,
                    uploaded_at=uploaded_at,
                    occurred_at=uploaded_at,
                    time_source="uploaded",
                )
            )
            session.flush()
            demand_id = ensure_demand(session, occurrence_id, now=utcnow()).id
            expected[demand_id] = (workspace_id, occurrence_id)
    planner = AutomaticAnalysisPlanner(
        settings, live["sessions"], live["store"], CoreExecutor(settings)
    )
    dispatcher = DramatiqTaskDispatcher(settings)
    completed = []
    processes = ExitStack()
    planner_pids = []
    paused_pid = None

    def start_resident():
        process = processes.enter_context(
            delivery_tests.resident_planner_process(
                settings,
                live["sessions"],
                live["output"] / f"resident-planner-{len(planner_pids)}.log",
            )
        )
        planner_pids.append(process.pid)
        return process

    def wait_for_adoption(process):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            assert process.poll() is None, "resident planner exited unexpectedly"
            with live["sessions"]() as session:
                slot = session.scalar(select(AnalysisExecutionSlot))
                if slot is not None and slot.run_id is not None:
                    return
            time.sleep(0.1)
        raise AssertionError("resident planner did not adopt a Run within 60 seconds")

    try:
        if resident_restart:
            pause_log = live["output"] / "resident-paused.log"
            with delivery_tests.resident_planner_process(
                settings.model_copy(update={"automatic_analysis_paused": True}),
                live["sessions"],
                pause_log,
            ) as paused_process:
                paused_pid = paused_process.pid
                deadline = time.monotonic() + 30
                while "recovery remains active" not in pause_log.read_text(encoding="utf-8"):
                    assert paused_process.poll() is None, "paused resident exited"
                    assert time.monotonic() < deadline, "paused resident did not become ready"
                    time.sleep(0.1)
                observe_until = time.monotonic() + 2
                while time.monotonic() < observe_until:
                    assert paused_process.poll() is None
                    with live["sessions"]() as session:
                        assert not list(session.scalars(select(AnalysisRun)))
                        assert not list(session.scalars(select(AnalysisExecutionSlot)))
                        demands = list(session.scalars(select(AnalysisDemand)))
                        assert {d.id for d in demands} == set(expected)
                        assert all(d.retry_attempt == 0 for d in demands)
                    time.sleep(0.1)
        resident = start_resident() if resident_restart else None
        for index in range(len(expected)):
            if resident_restart:
                wait_for_adoption(resident)
                if index == 0:
                    resident.kill()
                    resident.wait(timeout=15)
                    resident = start_resident()
            else:
                assert planner.run_once(owner_id="native-automatic") == 1
            with live["sessions"]() as session:
                slots = list(session.scalars(select(AnalysisExecutionSlot)))
                assert len(slots) == 1
                demand_id, run_id = slots[0].demand_id, slots[0].run_id
                assert demand_id in expected
                assert demand_id not in {row["demand_id"] for row in completed}
                workspace_id, occurrence_id = expected[demand_id]
                run = session.get(AnalysisRun, run_id)
                assert run.status == "QUEUED"
                intent = session.scalar(select(TaskIntent).where(TaskIntent.logical_key == run_id))
                queue = intent.message["queue"]
            if not resident_restart:
                assert planner.run_once(owner_id="budget-full") == 0
            assert relay_once(live["sessions"], dispatcher, settings, owner_id="automatic-relay")
            delivery_tests.consume_in_fresh_process(
                settings, live["sessions"], queue, timeout_seconds=90
            )
            with live["sessions"]() as session:
                run = session.get(AnalysisRun, run_id)
                assert run.status in {"COMPLETE", "PARTIAL"}, (
                    run.status,
                    run.error_code,
                    run.error_detail,
                )
                assert session.get(Occurrence, occurrence_id).current_run_id == run_id
                assert session.get(AnalysisDemand, demand_id).state == "updated"
                assert session.get(CurrentDecision, run_id).decision == "promote"
                assert session.get(AnalysisExecutionSlot, demand_id) is None
                assert "trigger_null_read" in session.get(AnalysisSummary, run_id).top_function
                canonical = json.loads(b"".join(live["store"].stream(run.result_object_key)))
                assert any(
                    "trigger_null_read" in (f.get("function") or "") and f["line"] == 76
                    for t in canonical["threads"]
                    for f in t["frames"]
                )
            completed.append(
                {"demand_id": demand_id, "run_id": run_id, "workspace_id": workspace_id}
            )
            (live["output"] / "automatic-worker-progress.json").write_text(
                json.dumps(
                    {"status": "RUNNING", "expected": workspace_count, "completed": completed},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    finally:
        processes.close()
        dispatcher.broker.close()
    assert completed[0]["workspace_id"] != completed[1]["workspace_id"]
    assert planner.run_once(owner_id="native-automatic-idle") == 0
    with live["sessions"]() as session:
        assert len(list(session.scalars(select(AnalysisRun)))) == len(expected)
        assert not list(session.scalars(select(AnalysisExecutionSlot)))
    if resident_restart:
        assert len(set(planner_pids)) == 2
    (live["output"] / "automatic-worker-progress.json").write_text(
        json.dumps(
            {"status": "COMPLETE", "expected": workspace_count, "completed": completed}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Retained Canonical 1.1 grouping"):
        command.downgrade(pg[2], "0019_analysis_scheduler")
    (live["output"] / "automatic-worker-result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "run_id": run_id,
                "demand_id": demand_id,
                "pair_id": pair_id,
                "delivery": "automatic-planner-redis-independent-worker",
                "resident_restart": resident_restart,
                "resident_process_ids": planner_pids,
                "paused_process_id": paused_pid,
                "current_run_id": run_id,
                "demand_state": "updated",
                "slot_released": True,
                "completed": completed,
                "enumeration_limit": enumeration_limit,
                "global_capacity": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_persistent_worker_executes_real_core_and_promotes_by_evidence(live, owned_redis):
    from crashcap_api.frozen_inputs import frozen_run_key
    from crashcap_api.ids import new_id, new_ulid
    from crashcap_api.models import (
        AnalysisDemand,
        AnalysisRun,
        AnalysisSummary,
        CurrentDecision,
        DumpBlob,
        Occurrence,
        TaskExecution,
        Workspace,
    )
    from crashcap_api.queueing import DramatiqTaskDispatcher
    from crashcap_api.task_handoff import create_task_intent
    from crashcap_worker.outbox_relay import relay_once

    from .test_analysis_demands import NOW

    pair_id, prepared = admit(live, compressed=True)
    baseline = ROOT / "target/qa-symbol-import/frozen-context"
    dump = FIXTURE / "null-read.dmp"
    dump_bytes = dump.read_bytes()
    inspect_bytes = (baseline / "inspect.json").read_bytes()
    manifest_bytes = (baseline / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert manifest["modules"][0]["selected_pair_id"] == pair_id

    workspace_id = new_id("wsp")
    blob_id = new_id("blob")
    occurrence_id = new_id("occ")
    run_id = new_id("run")
    demand_id = "dem_" + new_ulid()
    attempt_id = "att_" + new_ulid()
    dump_key = f"qualification/persistent/{blob_id}/dump.dmp"
    inspect_key = f"qualification/persistent/{blob_id}/inspect.json"
    manifest_key = f"qualification/persistent/{run_id}/resolution-manifest.json"

    run_spec = json.loads((baseline / "run.json").read_bytes())
    run_spec.update(
        run_id=run_id,
        occurrence_id=occurrence_id,
        demand_id=demand_id,
        demand_generation=1,
        dump={
            "object_key": dump_key,
            "sha256": hashlib.sha256(dump_bytes).hexdigest(),
            "size": len(dump_bytes),
        },
        inspect={
            "object_key": inspect_key,
            "sha256": hashlib.sha256(inspect_bytes).hexdigest(),
        },
        resolution_manifest={
            "object_key": manifest_key,
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        },
    )
    run_spec["context"].update(
        workspace_id=workspace_id,
        symbolicator_image_digest=live["image_id"],
        symbolicator_version=live["version"],
    )
    build_snapshot = run_spec["policy_snapshots"]["build_snapshot"]
    build_snapshot["builds"][0]["workspace_id"] = workspace_id
    run_spec["context"]["build_snapshot_sha256"] = digest(build_snapshot)
    run_spec["context_sha256"] = digest(run_spec["context"])
    run_spec["result_facts"]["dump"].update(
        blob_id=blob_id,
        sha256=hashlib.sha256(dump_bytes).hexdigest(),
        size=len(dump_bytes),
        uploaded_at=NOW.isoformat(),
        occurred_at=NOW.isoformat(),
    )
    run_spec["idempotency_key"] = frozen_run_key(run_spec)
    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
            "symbolicator_version": live["version"],
        }
    )
    live["store"].put_bytes(dump_key, dump_bytes, "application/octet-stream")
    live["store"].put_bytes(inspect_key, inspect_bytes, "application/json")
    live["store"].put_bytes(manifest_key, manifest_bytes, "application/json")
    message = {
        "schema_version": "1.2",
        "task_type": "analyze_frozen_run",
        "run_id": run_id,
        "attempt_id": attempt_id,
        "queue": "dump-small",
        "request_id": "req_persistent_real_core",
    }
    with live["sessions"].begin() as session:
        session.add(Workspace(id=workspace_id, name=workspace_id))
        session.flush()
        session.add(
            Build(
                id="bld_fixture",
                workspace_id=workspace_id,
                version="qualification",
            )
        )
        session.flush()
        session.add(
            DumpBlob(
                id=blob_id,
                workspace_id=workspace_id,
                sha256=hashlib.sha256(dump_bytes).hexdigest(),
                size=len(dump_bytes),
                object_key=dump_key,
                verification_status="ACCEPTED",
            )
        )
        session.flush()
        session.add(
            Occurrence(
                id=occurrence_id,
                workspace_id=workspace_id,
                dump_blob_id=blob_id,
                uploaded_at=NOW,
                occurred_at=NOW,
                time_source="uploaded",
            )
        )
        session.flush()
        session.add(
            AnalysisDemand(
                id=demand_id,
                occurrence_id=occurrence_id,
                workspace_id=workspace_id,
                state="queued",
                reason="initial",
                generation=1,
            )
        )
        session.flush()
        session.add(
            AnalysisRun(
                id=run_id,
                occurrence_id=occurrence_id,
                demand_id=demand_id,
                demand_generation=1,
                retry_attempt=0,
                run_spec=run_spec,
                resolution_method="unresolved",
                resolution_evidence={"candidate_build_ids": []},
                core_version="frozen-v1",
                core_image_digest=settings.core_image_digest,
                symbolicator_version=settings.symbolicator_version,
                schema_version="1.1",
                grouping_version=settings.grouping_version,
                normalization_version=settings.normalization_version,
                symbol_inventory_version=0,
                idempotency_key=run_spec["idempotency_key"],
                status="QUEUED",
                inspect_object_key=inspect_key,
                analysis_context=run_spec["context"],
                assembly_mode="core-final",
            )
        )
        session.flush()
        create_task_intent(session, message, settings.schema_root)

    dispatcher = DramatiqTaskDispatcher(settings)
    try:
        assert relay_once(live["sessions"], dispatcher, settings, owner_id="native-worker-relay")
        delivery_tests.consume_in_fresh_process(
            settings, live["sessions"], message["queue"], timeout_seconds=90
        )
    finally:
        dispatcher.broker.close()

    with live["sessions"]() as session:
        run = session.get(AnalysisRun, run_id)
        occurrence = session.get(Occurrence, occurrence_id)
        demand = session.get(AnalysisDemand, demand_id)
        execution = session.get(TaskExecution, ("analyze_frozen_run", run_id))
        summary = session.get(AnalysisSummary, run_id)
        decision = session.get(CurrentDecision, run_id)
        assert run is not None and run.status in {"COMPLETE", "PARTIAL"}
        assert run.result_object_key is not None
        assert run.winner_attempt_id == attempt_id and run.winner_generation == 1
        assert occurrence is not None and occurrence.current_run_id == run_id
        assert demand is not None and (demand.state, demand.reason) == (
            "updated",
            "initial",
        )
        assert decision is not None and (decision.decision, decision.reason) == (
            "promote",
            "initial",
        )
        assert decision.execution_attempt_id == attempt_id
        assert decision.execution_generation == 1
        assert execution is not None and execution.outcome == "succeeded"
        assert summary is not None and "trigger_null_read" in (summary.top_function or "")
        canonical_key = run.result_object_key
        canonical_payload = b"".join(live["store"].stream(canonical_key))
        canonical = json.loads(canonical_payload)
    assert canonical["analysis_id"] == run_id
    assert any(
        "trigger_null_read" in (frame.get("function") or "") and frame["line"] == 76
        for thread in canonical["threads"]
        for frame in thread["frames"]
    )
    (live["output"] / "persistent-worker-result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "delivery": "redis-outbox-independent-dramatiq-worker",
                "run_id": run_id,
                "attempt_id": attempt_id,
                "pair_id": pair_id,
                "canonical_object_key": canonical_key,
                "canonical_sha256": hashlib.sha256(canonical_payload).hexdigest(),
                "current_run_id": run_id,
                "current_decision": decision.decision,
                "current_decision_reason": decision.reason,
                "demand_state": "updated",
                "actual_pe_sha256": prepared.pe.raw_sha256,
                "actual_pdb_sha256": prepared.pdb.raw_sha256,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
