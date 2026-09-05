"""Real publication sealing and Workspace role isolation qualification."""

from __future__ import annotations

import hashlib
import json
import zipfile

from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import Artifact, Build, BuildModule, Upload, WorkspaceModuleRole
from crashcap_api.services.catalog_backfill import backfill_catalog
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient

from .fixture_source import fixture_source_root
from .test_frozen_delivery_redis import consume_in_fresh_process


def qualify_publications(live, redis_url, fixture, *, with_source=False):
    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": redis_url,
            "build_publications_enabled": True,
            "workspace_module_roles_enabled": True,
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 1,
            "automatic_analysis_capacity": 1,
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
    files = {
        kind: fixture / f"null_read_target.{extension}"
        for kind, extension in (("pe", "exe"), ("pdb", "pdb"))
    }
    artifacts = [
        {
            "module_code_file": files["pe"].name,
            "kind": kind,
            "logical_name": path.name,
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for kind, path in files.items()
    ]
    body = {
        "schema_version": "1.0",
        "origin": "local",
        "client_publication_id": "native-sealed",
        "client_version": "crashcap/1.0.0",
        "git": {"revision": "0123456789abcdef", "worktree_state": "dirty"},
        "manifest": {
            "schema_version": "1.0",
            "product": "native sealed qualification",
            "version": "qualification",
            "architecture": "x86_64",
            "compiler": "msvc",
            "modules": [
                {
                    "code_file": files["pe"].name,
                    "debug_file": files["pdb"].name,
                    "role": "entrypoint",
                }
            ],
        },
        "artifacts": artifacts,
    }
    app = create_app(settings)
    consumers = []

    def drain(queue):
        relay_once(live["sessions"], app.state.dispatcher, settings, owner_id="native-publication")
        consume_in_fresh_process(settings, live["sessions"], queue, timeout_seconds=90)

    def snapshot():
        with live["sessions"]() as session:
            result = {}
            for model in (Build, BuildModule, Artifact):
                table = model.__table__
                owner = table.c.id if model is Build else table.c.build_id
                result[table.name] = [
                    dict(row)
                    for row in session.execute(
                        table.select()
                        .where(owner.in_([row[1] for row in consumers]))
                        .order_by(table.c.id)
                    ).mappings()
                ]
            raw = {
                row["id"]: b"".join(live["store"].stream(row["manifest_object_key"]))
                for row in result[Build.__tablename__]
            }
            return result, raw

    try:
        with TestClient(app) as client:
            for role in ("owned", "dependency"):
                response = client.post("/api/v3/workspaces", json={"name": "sealed-" + role})
                assert response.status_code == 201, response.text
                workspace_id = response.json()["id"]
                local_files, local_artifacts = dict(files), list(artifacts)
                if with_source:
                    source = live["output"] / f"{role}.zip"
                    with zipfile.ZipFile(source, "w") as archive:
                        archive.writestr(
                            "scripts/fixtures/null_read_target.cpp",
                            f"// WORKSPACE_SOURCE_{role}\n" * 200,
                        )
                    local_files["source_bundle"] = source
                    local_artifacts.append(
                        {
                            "kind": "source_bundle",
                            "logical_name": "source.zip",
                            "size": source.stat().st_size,
                            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        }
                    )
                    response = client.post(
                        f"/api/v3/workspaces/{workspace_id}/builds",
                        json={"version": "qualification", "architecture": "x86_64"},
                    )
                else:
                    response = client.post(
                        f"/api/v3/workspaces/{workspace_id}/build-publications", json=body
                    )
                assert response.status_code == 201, response.text
                build_id = response.json()["id" if with_source else "build_id"]
                if with_source:
                    manifest = {
                        **body["manifest"],
                        "schema_version": "2.0",
                        "source_bundle": {
                            "schema_version": "1.0",
                            "archive": "source.zip",
                            "source_root": fixture_source_root(fixture),
                        },
                    }
                    response = client.put(f"/api/v3/builds/{build_id}/manifest", json=manifest)
                    assert response.status_code == 200, response.text
                consumers.append((workspace_id, build_id, role))
                for artifact in local_artifacts:
                    response = client.post(
                        f"/api/v3/builds/{build_id}/artifacts/uploads:init",
                        json={
                            "file_kind": artifact["kind"],
                            "filename": artifact["logical_name"],
                            "size": artifact["size"],
                            "sha256": artifact["sha256"],
                        },
                    )
                    assert response.status_code == 201, response.text
                    upload_id = response.json()["upload_id"]
                    with live["sessions"]() as session:
                        key = session.get(Upload, upload_id).object_key
                    live["store"].put_file(
                        key, local_files[artifact["kind"]], "application/octet-stream"
                    )
                    response = client.post(f"/api/v3/uploads/{upload_id}/complete", json={})
                    assert response.status_code == 200, response.text
                    drain("verify")
                    drain("ingest")
                if not with_source:
                    status = client.get(f"/api/v3/builds/{build_id}/publication-status").json()
                    assert status["ready"] and status["sealed_at"], status
            before = snapshot()
            cursor = None
            for _ in range(10):
                backfill = backfill_catalog(
                    live["sessions"],
                    live["store"],
                    CoreExecutor(settings),
                    after=cursor,
                    limit=10,
                    apply=True,
                )
                if not backfill["has_more"]:
                    break
                cursor = backfill["next_cursor"]
            else:
                raise AssertionError("Publication backfill did not finish")
            assert snapshot() == before
            from .native_publication_analysis import prepare_runs

            verify_runs = prepare_runs(
                client, settings, live, consumers, fixture, drain, with_source=with_source
            )
            with live["sessions"]() as session:
                artifact = (
                    session.query(Artifact).filter_by(build_id=consumers[0][1], kind="pe").one()
                )
                identity = {
                    "code_id": artifact.code_id,
                    "debug_id": artifact.debug_id,
                    "architecture": "x86_64",
                }
            for workspace_id, _, role in consumers:
                response = client.post(
                    f"/api/v3/workspaces/{workspace_id}/module-roles",
                    json={"identity": identity, "role": role},
                )
                assert response.status_code == 201, response.text
                drain("ingest")
                assert snapshot() == before
            with live["sessions"]() as session:
                assert {
                    row.workspace_id: row.role for row in session.query(WorkspaceModuleRole)
                } == {workspace: role for workspace, _, role in consumers}
            runs = verify_runs()
            assert snapshot() == before
            (live["output"] / "native-publication-roles.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "runs": runs,
                        "consumers": consumers,
                        "identity": identity,
                        "sealed_history_unchanged": not with_source,
                        "legacy_source_history_unchanged": with_source,
                        "manifest_sha256": {
                            key: hashlib.sha256(value).hexdigest()
                            for key, value in before[1].items()
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        app.state.dispatcher.broker.close()
