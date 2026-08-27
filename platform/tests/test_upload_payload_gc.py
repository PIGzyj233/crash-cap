from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import crashcap_api.services.upload_gc as upload_gc_service
from crashcap_api.models import Artifact, ArtifactBlobUploadClaim, TaskExecution, Upload
from crashcap_api.services.upload_gc import sweep_terminal_upload_payloads
from prometheus_client import REGISTRY

from .conftest import Phase1Harness, pe_bytes


def _age_upload(harness: Phase1Harness, upload_id: str, *, hours: int = 25) -> Upload:
    with harness.app.state.database.sessions() as session:
        upload = session.get(Upload, upload_id)
        assert upload is not None
        upload.completed_at = datetime.now(UTC) - timedelta(hours=hours)
        session.commit()
        return upload


def _accepted_pe_upload(
    harness: Phase1Harness, *, name: str, debug_id: str
) -> tuple[dict[str, Any], dict[str, Any], bytes, Upload]:
    workspace = harness.create_workspace(name)
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    payload = pe_bytes(debug_id)
    initialized = harness.client.post(
        f"/api/v1/builds/{build['id']}/artifacts/uploads:init",
        json={"file_kind": "pe", "filename": "app.exe", "size": len(payload)},
    ).json()
    harness._seed_upload(initialized["upload_id"], payload)
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    harness.drain()
    return workspace, build, payload, _age_upload(harness, initialized["upload_id"])


def test_upload_gc_is_dry_run_by_default_and_keeps_metadata(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("upload-gc")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    payload = pe_bytes("AABBCCDD")
    initialized = harness.client.post(
        f"/api/v1/builds/{build['id']}/artifacts/uploads:init",
        json={"file_kind": "pe", "filename": "app.exe", "size": len(payload)},
    ).json()
    harness._seed_upload(initialized["upload_id"], payload)
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    harness.drain()
    upload = _age_upload(harness, initialized["upload_id"])

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
    )

    assert report["would_delete"] == 1
    assert harness.app.state.store.head(upload.object_key).size == len(payload)
    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None and durable.payload_deleted_at is None


def test_upload_gc_apply_deletes_only_staging_and_is_retry_idempotent(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("upload-gc-apply")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    payload = pe_bytes("EEFF0011")
    initialized = harness.client.post(
        f"/api/v1/builds/{build['id']}/artifacts/uploads:init",
        json={"file_kind": "pe", "filename": "app.exe", "size": len(payload)},
    ).json()
    harness._seed_upload(initialized["upload_id"], payload)
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    harness.drain()
    upload = _age_upload(harness, initialized["upload_id"])
    with harness.app.state.database.sessions() as session:
        artifact = session.query(Artifact).filter_by(build_id=build["id"], kind="pe").one()
        authoritative_key = artifact.object_key

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )

    assert report["deleted"] == 1
    assert harness.app.state.store.head(authoritative_key).size == len(payload)
    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None
        assert durable.payload_deleted_at is not None
        assert durable.payload_deletion_attempts == 1
    rerun = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )
    assert rerun["scanned"] == 0


def test_upload_gc_refuses_active_artifact_transfer_claim(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("upload-gc-claim")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    payload = pe_bytes("11223344")
    initialized = harness.client.post(
        f"/api/v1/builds/{build['id']}/artifacts/uploads:init",
        json={"file_kind": "pe", "filename": "app.exe", "size": len(payload)},
    ).json()
    harness._seed_upload(initialized["upload_id"], payload)
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    harness.drain()
    upload = _age_upload(harness, initialized["upload_id"])
    with harness.app.state.database.sessions() as session:
        session.add(
            ArtifactBlobUploadClaim(
                workspace_id=workspace["id"],
                sha256=str(upload.verified_sha256),
                upload_id=upload.id,
                kind="pe",
                size=len(payload),
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        session.commit()

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )

    assert report["skipped"] == 1
    assert report["cases"][0]["reason"] == "artifact_transfer_claim_active"
    assert harness.app.state.store.head(upload.object_key).size == len(payload)


def test_upload_gc_refuses_active_delete_claim_then_takes_over_expired_lease(
    harness: Phase1Harness,
) -> None:
    _workspace, _build, payload, upload = _accepted_pe_upload(
        harness, name="upload-gc-delete-claim", debug_id="55667788"
    )
    now = datetime.now(UTC)
    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None
        durable.payload_delete_claim_token = "other-sweeper"  # noqa: S105 - opaque lease token
        durable.payload_delete_lease_expires_at = now + timedelta(minutes=5)
        session.commit()

    metric_labels = {"kind": "pe", "reason": "payload_delete_claim_active"}
    before = REGISTRY.get_sample_value(
        "crashcap_upload_payload_gc_ineligible_total", metric_labels
    ) or 0.0
    blocked = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=now,
        apply=True,
    )
    assert blocked["skipped"] == 1
    assert blocked["cases"][0]["reason"] == "payload_delete_claim_active"
    assert (
        REGISTRY.get_sample_value(
            "crashcap_upload_payload_gc_ineligible_total", metric_labels
        )
        == before + 1
    )
    assert harness.app.state.store.head(upload.object_key).size == len(payload)

    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None
        durable.payload_delete_lease_expires_at = now - timedelta(seconds=1)
        session.commit()
    taken_over = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=now,
        apply=True,
    )
    assert taken_over["deleted"] == 1


def test_upload_gc_refuses_running_verification_task(harness: Phase1Harness) -> None:
    _workspace, _build, payload, upload = _accepted_pe_upload(
        harness, name="upload-gc-running-task", debug_id="66778899"
    )
    now = datetime.now(UTC)
    with harness.app.state.database.sessions() as session:
        execution = session.get(
            TaskExecution,
            {"task_type": "verify_upload", "logical_key": upload.id},
        )
        assert execution is not None
        execution.outcome = "running"
        execution.lease_until = now + timedelta(minutes=5)
        session.commit()

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=now,
        apply=True,
    )
    assert report["skipped"] == 1
    assert report["cases"][0]["reason"] == "verification_task_active"
    assert harness.app.state.store.head(upload.object_key).size == len(payload)


def test_upload_gc_refuses_same_size_corrupt_authoritative_artifact(
    harness: Phase1Harness,
) -> None:
    _workspace, build, payload, upload = _accepted_pe_upload(
        harness, name="upload-gc-corrupt-authority", debug_id="77889900"
    )
    with harness.app.state.database.sessions() as session:
        artifact = session.query(Artifact).filter_by(build_id=build["id"], kind="pe").one()
        authoritative_key = artifact.object_key
    corrupt = bytearray(payload)
    corrupt[-1] ^= 0xFF
    harness.app.state.store.put_bytes(
        authoritative_key, bytes(corrupt), "application/octet-stream"
    )

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )
    assert report["skipped"] == 1
    assert report["cases"][0]["reason"] == "authoritative_artifact_object_missing"
    assert harness.app.state.store.head(upload.object_key).size == len(payload)


def test_upload_gc_does_not_use_other_workspace_authoritative_object(
    harness: Phase1Harness,
) -> None:
    _workspace_a, build_a, payload, upload_a = _accepted_pe_upload(
        harness, name="upload-gc-workspace-a", debug_id="88990011"
    )
    workspace_b = harness.create_workspace("upload-gc-workspace-b")
    build_b = harness.create_build(workspace_b["id"])
    harness.put_manifest(build_b["id"])
    harness.upload_artifact(build_b["id"], "pe", "app.exe", payload)
    with harness.app.state.database.sessions() as session:
        artifact_a = session.query(Artifact).filter_by(build_id=build_a["id"], kind="pe").one()
        session.delete(artifact_a)
        session.commit()

    report = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )
    assert report["scanned"] == 1
    assert report["skipped"] == 1
    assert report["cases"][0]["reason"] == "authoritative_artifact_missing"
    assert harness.app.state.store.head(upload_a.object_key).size == len(payload)


def test_upload_gc_replays_after_object_delete_before_database_commit(
    harness: Phase1Harness, monkeypatch: Any
) -> None:
    _workspace, _build, _payload, upload = _accepted_pe_upload(
        harness, name="upload-gc-post-delete-replay", debug_id="99001122"
    )
    original_operation_log = upload_gc_service.operation_log
    calls = 0

    def fail_first_operation_log(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected database write failure after object delete")
        return original_operation_log(*args, **kwargs)

    monkeypatch.setattr(upload_gc_service, "operation_log", fail_first_operation_log)
    first = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )
    assert first["failed"] == 1
    assert first["storage_reconciliation"]["objects"]["missing_retained"] == 1
    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None
        assert durable.payload_deleted_at is None
        assert durable.payload_deletion_attempts == 1

    second = sweep_terminal_upload_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
        apply=True,
    )
    assert second["deleted"] == 1
    assert second["cases"][0]["outcome"] == "already_absent_after_retry"
    assert second["storage_reconciliation"]["objects"]["missing_retained"] == 0
    with harness.app.state.database.sessions() as session:
        durable = session.get(Upload, upload.id)
        assert durable is not None
        assert durable.payload_deleted_at is not None
        assert durable.payload_deletion_attempts == 2
