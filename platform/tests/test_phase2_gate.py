from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, cast

import pytest
from crashcap_api.models import AnalysisRun, Build, Occurrence
from crashcap_ci.main import Publisher, PublishError
from crashcap_worker.source_bundle import SourceBundleError, inspect_source_bundle
from sqlalchemy import func, select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

DEBUG_ID = "c" * 32 + "1"


def _manifest(version: str = "1.0", *, source: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": version,
        "product": "Phase 2 Gate",
        "version": "2.0.0",
        "architecture": "x86_64",
        "compiler": "msvc",
        "toolchain": "msvc-19.40",
        "modules": [{"code_file": "app.exe", "debug_file": "app.pdb", "role": "entrypoint"}],
    }
    if source:
        payload["source_bundle"] = {
            "schema_version": "1.0",
            "archive": "source-bundle.zip",
            "source_root": "C:/agent/_work/product",
            "strip_prefixes": ["D:/src/product"],
            "context_lines": 2,
        }
    return payload


def _source_zip(path: Path, *, unsafe_name: str | None = None) -> bytes:
    source = "\n".join(f"source line {index}" for index in range(1, 60))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(unsafe_name or "fake.cpp", source)
    return path.read_bytes()


def _create_ci_build(harness: Phase1Harness, workspace_id: str) -> dict[str, Any]:
    response = harness.client.post(
        f"/api/v1/workspaces/{workspace_id}/builds",
        json={
            "version": "2.0.0",
            "architecture": "x86_64",
            "producer": "msvc",
            "producer_build_id": "pipeline-42",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ci_build_registration_is_idempotent_and_readiness_is_strict(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("phase2-ci")
    build = _create_ci_build(harness, workspace["id"])
    replay = _create_ci_build(harness, workspace["id"])
    assert replay["id"] == build["id"]
    assert replay["producer"] == "msvc"
    assert replay["producer_build_id"] == "pipeline-42"
    conflicting = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/builds",
        json={
            "version": "2.0.1",
            "architecture": "x86_64",
            "producer": "msvc",
            "producer_build_id": "pipeline-42",
        },
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["details"]["conflicting_fields"] == ["version"]

    saved = harness.client.put(f"/api/v1/builds/{build['id']}/manifest", json=_manifest())
    assert saved.status_code == 200, saved.text
    incomplete = harness.client.get(f"/api/v1/builds/{build['id']}/ci-status").json()
    assert incomplete["ready"] is False
    assert {(item["kind"], item["logical_name"]) for item in incomplete["missing_artifacts"]} == {
        ("pe", "app.exe"),
        ("pdb", "app.pdb"),
    }

    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    ready = harness.client.get(f"/api/v1/builds/{build['id']}/ci-status").json()
    assert ready["ready"] is True
    assert ready["producer_status"] == "supported"
    assert ready["missing_artifacts"] == []
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Build)) == 1

    matrix = harness.client.get("/api/v1/ci/producers").json()
    assert {row["producer"]: row["status"] for row in matrix} == {
        "msvc": "supported",
        "clang-cl": "experimental",
        "crashpad": "experimental",
    }


def test_source_bundle_v2_is_safely_ingested_and_enriches_symbolicator_frames(
    harness: Phase1Harness, tmp_path: Path
) -> None:
    workspace = harness.create_workspace("phase2-source")
    build = _create_ci_build(harness, workspace["id"])
    saved = harness.client.put(
        f"/api/v1/builds/{build['id']}/manifest", json=_manifest("2.0", source=True)
    )
    assert saved.status_code == 200, saved.text
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    bundle = harness.upload_artifact(
        build["id"],
        "source_bundle",
        "source-bundle.zip",
        _source_zip(tmp_path / "source-bundle.zip"),
    )
    assert bundle["verification_status"] == "verified"
    assert bundle["ingest_metadata"]["policy_version"] == "source-bundle-v1.0"

    completed = harness.upload_dump(workspace["id"], dump_bytes(201), reported_build_id=build["id"])
    canonical = harness.client.get(
        f"/api/v1/occurrences/{completed['occurrence_id']}/analysis"
    ).json()
    context = canonical["threads"][0]["frames"][0]["source_context"]
    assert context == {
        "pre": ["source line 40", "source line 41"],
        "line": "source line 42",
        "post": ["source line 43", "source line 44"],
    }

    v1_build = harness.create_build(workspace["id"], "1.0.0")
    harness.client.put(
        f"/api/v1/builds/{v1_build['id']}/manifest",
        json={**_manifest(), "version": "1.0.0"},
    )
    rejected = harness.client.post(
        f"/api/v1/builds/{v1_build['id']}/artifacts/uploads:init",
        json={"file_kind": "source_bundle", "filename": "source-bundle.zip", "size": 10},
    )
    assert rejected.status_code == 422


@pytest.mark.parametrize("unsafe_name", ["../fake.cpp", "C:/agent/src/fake.cpp"])
def test_source_bundle_rejects_absolute_or_traversal_before_consumption(
    tmp_path: Path, unsafe_name: str
) -> None:
    archive = tmp_path / "unsafe.zip"
    _source_zip(archive, unsafe_name=unsafe_name)
    with pytest.raises(SourceBundleError, match="relative root"):
        inspect_source_bundle(archive)


def test_late_symbol_target_and_batch_reprocess_are_observable_and_recoverable(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("phase2-late-symbol")
    build = harness.create_build(workspace["id"], "2.0.0")
    harness.client.put(f"/api/v1/builds/{build['id']}/manifest", json=_manifest())
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    completed = harness.upload_dump(workspace["id"], dump_bytes(202), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    old_run = before["current_analysis"]["id"]
    assert before["current_analysis"]["status"] == "PARTIAL"

    health = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/symbols/health").json()
    target = next(row for row in health if row["code_file"] == "app.exe")
    assert target["build_id"] == build["id"]
    assert target["module_id"]
    assert target["occurrence_ids"] == [occurrence_id]

    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    requested = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/symbols/reprocess",
        json={"module_id": target["module_id"]},
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["affected_occurrence_count"] == 1
    assert requested.json()["created_run_count"] == 1
    harness.drain()
    after = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert after["current_analysis"]["status"] == "COMPLETE"
    assert after["current_analysis"]["id"] != old_run
    assert (
        harness.client.get(
            f"/api/v1/occurrences/{occurrence_id}/analysis", params={"run_id": old_run}
        ).status_code
        == 200
    )
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_versioned_in_app_rules_trigger_reprocess_and_enforce_system_deny_floor(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("phase2-in-app")
    build = harness.create_build(workspace["id"], "2.0.0")
    harness.client.put(f"/api/v1/builds/{build['id']}/manifest", json=_manifest())
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    completed = harness.upload_dump(workspace["id"], dump_bytes(203), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert before["group"] is not None

    changed = harness.client.put(
        f"/api/v1/workspaces/{workspace['id']}/in-app-rules",
        json={"include_modules": [], "exclude_modules": ["APP.EXE"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 1
    assert changed.json()["created_run_count"] == 1
    harness.drain()
    after = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()
    assert canonical["modules"][0]["in_app"] is False
    assert canonical["threads"][0]["frames"][0]["in_app"] is False
    assert canonical["fingerprints"]["exact"] is None
    assert after["group"] is None

    denied = harness.client.put(
        f"/api/v1/workspaces/{workspace['id']}/in-app-rules",
        json={"include_modules": ["ntdll.dll"], "exclude_modules": []},
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["details"]["denied_modules"] == ["ntdll.dll"]


def test_sse_emits_authoritative_terminal_snapshot(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("phase2-sse")
    completed = harness.upload_dump(workspace["id"], dump_bytes(204))
    response = harness.client.get(f"/api/v1/occurrences/{completed['occurrence_id']}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: analysis-progress" in response.text
    assert '"status":"PARTIAL"' in response.text


def test_uploaded_run_can_be_explicitly_redispatched_after_queue_loss(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("phase2-redispatch")
    upload = harness.initialize_dump(workspace["id"], dump_bytes(205))
    assert harness.app.state.dispatcher.drain(limit=1) == 1
    terminal_upload = harness.client.get(f"/api/v1/uploads/{upload['upload_id']}").json()
    detail = harness.client.get(f"/api/v1/occurrences/{terminal_upload['occurrence_id']}").json()
    run_id = detail["latest_attempt"]["id"]
    assert detail["latest_attempt"]["status"] == "UPLOADED"
    harness.app.state.dispatcher.messages.clear()

    retried = harness.client.post(f"/api/v1/analysis-runs/{run_id}/retry-dispatch")
    assert retried.status_code == 202, retried.text
    assert retried.json()["run_id"] == run_id
    assert len(harness.app.state.dispatcher.snapshot()) == 1
    harness.drain()
    completed = harness.client.get(f"/api/v1/occurrences/{terminal_upload['occurrence_id']}").json()
    assert completed["current_analysis"]["status"] == "PARTIAL"


class _FakePublisherApi:
    def __init__(self, *, producer_status: str = "supported", multipart: bool = False) -> None:
        self.producer_status = producer_status
        self.multipart = multipart
        self.uploaded_parts: list[bytes] = []
        self.upload_index = 0

    def request(self, method: str, path: str, *, json_body: object | None = None) -> Any:
        if path == "/workspaces":
            return [{"id": "wsp_ci", "name": "ci"}]
        if path == "/ci/producers":
            return [{"producer": "msvc", "status": self.producer_status}]
        if path.endswith("/builds") and method == "POST":
            return {"id": "bld_ci", "artifacts": []}
        if path.endswith("/manifest"):
            return {"id": "bld_ci", "artifacts": []}
        if path.endswith("uploads:init"):
            self.upload_index += 1
            response: dict[str, Any] = {
                "upload_id": f"upl_{self.upload_index}",
                "url": "https://upload.invalid/object",
                "method": "PUT",
                "headers": {},
            }
            if self.multipart:
                response["multipart"] = {
                    "upload_id": "s3-multipart",
                    "parts": [
                        {"part_number": 1, "url": "https://upload.invalid/1"},
                        {"part_number": 2, "url": "https://upload.invalid/2"},
                    ],
                }
            return response
        if path.endswith("/complete"):
            return {"verification_status": "VERIFYING"}
        if path.startswith("/uploads/"):
            return {"verification_status": "ACCEPTED"}
        if path.endswith("/ci-status"):
            return {"ready": True, "rejected_artifacts": []}
        raise AssertionError((method, path, json_body))

    def put_bytes(self, _url: str, payload: bytes, _headers: dict[str, str]) -> str:
        self.uploaded_parts.append(payload)
        return f"etag-{len(self.uploaded_parts)}"


def test_ci_publisher_validates_local_completeness_and_handles_multipart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    (root / "app.exe").write_bytes(b"pe-bytes")
    (root / "app.pdb").write_bytes(b"pdb-bytes")
    manifest_path = root / "build-manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    api = _FakePublisherApi(multipart=True)
    monkeypatch.setattr("crashcap_ci.main.PART_SIZE", 5)
    result = Publisher(cast(Any, api), Path(__file__).resolve().parents[2] / "contracts").publish(
        workspace="ci",
        manifest_path=manifest_path,
        artifact_root=root,
        producer="msvc",
        producer_build_id="run-1",
        allow_experimental=False,
        wait_seconds=1,
    )
    assert result["build_id"] == "bld_ci"
    assert len(api.uploaded_parts) == 4
    assert all(api.uploaded_parts)

    (root / "app.pdb").unlink()
    with pytest.raises(PublishError, match="app.pdb"):
        Publisher(cast(Any, api), Path(__file__).resolve().parents[2] / "contracts").publish(
            workspace="ci",
            manifest_path=manifest_path,
            artifact_root=root,
            producer="msvc",
            producer_build_id="run-2",
            allow_experimental=False,
            wait_seconds=1,
        )
