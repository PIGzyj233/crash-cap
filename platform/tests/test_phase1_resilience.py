"""Phase 1 resilience, retention, and local capacity gates.

The production code deliberately keeps Core execution behind ``WorkerProcessor``
and uses explicit SQLite/local-store/in-memory doubles in tests.  These tests
exercise those boundaries without starting Docker, Redis, RustFS, or a real
Symbolicator process.  In particular, the retry test covers the platform's
whole-run retry contract; there is no Symbolicator client in the current
platform package from which to prove a live Symbolicator restart.
"""

from __future__ import annotations

import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import crashcap_worker.core_runner as core_runner
import pytest
from crashcap_api.config import Settings
from crashcap_api.models import (
    AnalysisRun,
    AnalysisSummary,
    DumpBlob,
    GroupMembershipHistory,
    Occurrence,
    OperationLog,
)
from crashcap_api.storage import ObjectNotFoundError
from crashcap_worker.core_runner import CoreExecutionError
from crashcap_worker.retention import expire_dump_blobs
from sqlalchemy import func, select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes


class FailingCore:
    """Small Core test double that exposes the worker's exit classification."""

    def __init__(self, code: str) -> None:
        self.code = code
        self.calls = 0

    def analyze(self, _task_dir: Path, _run_spec: dict[str, Any]) -> Any:
        self.calls += 1
        raise CoreExecutionError(self.code, f"simulated Core failure: {self.code}")


class FailOnceThenDelegate:
    """Simulate one Symbolicator-side failure, then let a later whole run finish."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.failed = False

    def analyze(self, task_dir: Path, run_spec: dict[str, Any]) -> Any:
        if not self.failed:
            self.failed = True
            raise CoreExecutionError(
                "SYMBOLICATOR_REQUEST_FAILED",
                "simulated Symbolicator 404 after pending; old request_id is unusable",
            )
        return self.delegate.analyze(task_dir, run_spec)


def _current_run(harness: Phase1Harness, occurrence_id: str) -> dict[str, Any]:
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}")
    assert detail.status_code == 200, detail.text
    current = detail.json()["current_analysis"]
    assert current is not None
    return current


@pytest.mark.parametrize(
    ("returncode", "expected_code"),
    (
        (1, "CORE_FAILED"),
        (2, "UNSUPPORTED_DUMP"),
        (3, "CORRUPT_DUMP"),
        (137, "OOM"),
        (-9, "OOM"),
    ),
)
def test_core_runner_maps_nonzero_exit_to_worker_failure_class(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    expected_code: str,
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["dmp-core"], returncode, stdout="", stderr="simulated child failure"
        )

    monkeypatch.setattr(core_runner.subprocess, "run", fake_run)
    with pytest.raises(CoreExecutionError) as raised:
        core_runner._run(["dmp-core", "analyze"], timeout=1)
    assert raised.value.code == expected_code
    assert raised.value.returncode == returncode


def test_core_runner_maps_deadline_expiry_to_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["dmp-core"], timeout=1)

    monkeypatch.setattr(core_runner.subprocess, "run", fake_run)
    with pytest.raises(CoreExecutionError) as raised:
        core_runner._run(["dmp-core", "analyze"], timeout=1)
    assert raised.value.code == "TIMEOUT"
    assert raised.value.returncode is None


def test_core_runner_preserves_structured_symbolicator_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["dmp-core"],
            1,
            stdout="",
            stderr=(
                '{"error":{"code":"SYMBOLICATOR_REQUEST_FAILED",'
                '"message":"upstream unavailable","details":{}}}\n'
            ),
        )

    monkeypatch.setattr(core_runner.subprocess, "run", fake_run)
    with pytest.raises(CoreExecutionError) as raised:
        core_runner._run(["dmp-core", "analyze"], timeout=1)
    assert raised.value.code == "SYMBOLICATOR_REQUEST_FAILED"
    assert str(raised.value) == "upstream unavailable"


def test_core_runner_rejects_unpinned_local_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "core_image": "crash-cap/dmp-core:phase1",
            "core_image_digest": "sha256:" + "1" * 64,
        }
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["docker", "image", "inspect"],
            returncode=0,
            stdout="sha256:" + "2" * 64 + "\n",
            stderr="",
        )

    monkeypatch.setattr(core_runner.subprocess, "run", fake_run)
    with pytest.raises(CoreExecutionError) as raised:
        core_runner._verify_core_image(settings)
    assert raised.value.code == "CORE_IMAGE_MISMATCH"


@pytest.mark.parametrize(
    ("failure_code", "expected_status"),
    (
        ("CORE_FAILED", "FAILED"),
        ("UNSUPPORTED_DUMP", "REJECTED"),
        ("CORRUPT_DUMP", "REJECTED"),
        ("TIMEOUT", "TIMEOUT"),
        ("OOM", "OOM"),
    ),
)
def test_core_failure_classes_are_isolated_and_do_not_replace_current(
    harness: Phase1Harness,
    failure_code: str,
    expected_status: str,
) -> None:
    """A failed reprocess remains historical while API and later work continue."""

    workspace = harness.create_workspace(f"core-failure-{failure_code.lower().replace('_', '-')}")
    baseline = harness.upload_dump(workspace["id"], dump_bytes(20))
    occurrence_id = baseline["occurrence_id"]
    original_core = harness.app.state.processor.core
    current_id = _current_run(harness, occurrence_id)["id"]

    failing_core = FailingCore(failure_code)
    harness.app.state.processor.core = failing_core
    retry_response = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess",
        json={"force": True},
    )
    assert retry_response.status_code == 202, retry_response.text
    failed_id = retry_response.json()["id"]
    assert failed_id != current_id
    assert retry_response.json()["created"] is True

    assert harness.drain() == 1
    assert failing_core.calls == 1

    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["current_analysis"]["id"] == current_id
    assert detail["current_analysis"]["status"] in {"COMPLETE", "PARTIAL"}
    assert detail["latest_attempt"]["id"] == failed_id
    assert detail["latest_attempt"]["status"] == expected_status
    assert detail["latest_attempt"]["error_code"] == failure_code

    with harness.app.state.database.sessions() as session:
        failed_run = session.get(AnalysisRun, failed_id)
        occurrence = session.get(Occurrence, occurrence_id)
        assert failed_run is not None
        assert occurrence is not None
        assert failed_run.status == expected_status
        assert failed_run.error_code == failure_code
        assert occurrence.current_run_id == current_id
        assert "request_id" not in failed_run.run_spec

    # The control plane remains responsive, and a later independent task still
    # completes after the failed Core child has been replaced with the test Core.
    assert harness.client.get("/healthz").status_code == 200
    assert harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").status_code == 200
    harness.app.state.processor.core = original_core
    later = harness.upload_dump(workspace["id"], dump_bytes(21))
    assert later["occurrence_id"] != occurrence_id
    later_detail = harness.client.get(f"/api/v1/occurrences/{later['occurrence_id']}").json()
    assert later_detail["current_analysis"]["status"] in {"COMPLETE", "PARTIAL"}


def test_symbolicator_failure_is_retried_as_a_new_whole_run_without_old_request_id(
    harness: Phase1Harness,
) -> None:
    """Exercise the available whole-run retry seam without claiming live Symbolicator coverage."""

    workspace = harness.create_workspace("symbolicator-retry")
    baseline = harness.upload_dump(workspace["id"], dump_bytes(30))
    occurrence_id = baseline["occurrence_id"]
    original_core = harness.app.state.processor.core
    harness.app.state.processor.core = FailOnceThenDelegate(original_core)

    first = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess",
        headers={"X-Request-ID": "req-symbolicator-old"},
        json={"force": True},
    )
    assert first.status_code == 202, first.text
    first_run_id = first.json()["id"]
    first_message = harness.app.state.dispatcher.snapshot()[0]
    assert first_message["request_id"] == "req-symbolicator-old"
    assert harness.drain() == 1

    failed = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert failed["latest_attempt"]["id"] == first_run_id
    assert failed["latest_attempt"]["status"] == "FAILED"
    assert failed["latest_attempt"]["error_code"] == "SYMBOLICATOR_REQUEST_FAILED"
    assert failed["current_analysis"]["id"] != first_run_id

    second = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess",
        headers={"X-Request-ID": "req-symbolicator-new"},
        json={"force": True},
    )
    assert second.status_code == 202, second.text
    second_run_id = second.json()["id"]
    assert second_run_id != first_run_id
    second_message = harness.app.state.dispatcher.snapshot()[0]
    assert second_message["request_id"] == "req-symbolicator-new"
    assert second_message["attempt_id"] != first_message["attempt_id"]
    assert harness.drain() == 1

    completed = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert completed["current_analysis"]["id"] == second_run_id
    assert completed["current_analysis"]["status"] in {"COMPLETE", "PARTIAL"}
    with harness.app.state.database.sessions() as session:
        old_run = session.get(AnalysisRun, first_run_id)
        new_run = session.get(AnalysisRun, second_run_id)
        assert old_run is not None and old_run.status == "FAILED"
        assert new_run is not None and new_run.status in {"COMPLETE", "PARTIAL"}
        assert "request_id" not in old_run.run_spec
        assert "request_id" not in new_run.run_spec


def test_retention_deletes_only_raw_blob_and_preserves_analysis_history(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("retention-history")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    debug_id = "c" * 32 + "1"
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(debug_id))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(debug_id))
    completed = harness.upload_dump(workspace["id"], dump_bytes(40), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]

    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        assert occurrence is not None and occurrence.current_run_id is not None
        current_run_id = occurrence.current_run_id
        blob = session.get(DumpBlob, occurrence.dump_blob_id)
        assert blob is not None and blob.expires_at is not None
        raw_key = blob.object_key
        expiration = blob.expires_at
        before_summary_count = session.scalar(select(func.count()).select_from(AnalysisSummary))
        before_history_count = session.scalar(
            select(func.count()).select_from(GroupMembershipHistory)
        )
        assert before_summary_count == 1
        assert before_history_count == 1

    raw_path = harness.app.state.store.path_for(raw_key)
    assert raw_path.is_file()
    assert (
        expire_dump_blobs(
            harness.app.state.database.sessions,
            harness.app.state.store,
            now=expiration + timedelta(seconds=1),
        )
        == 1
    )

    with pytest.raises(ObjectNotFoundError):
        harness.app.state.store.head(raw_key)
    assert not raw_path.exists()

    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
        summary = session.get(AnalysisSummary, current_run_id)
        assert occurrence is not None
        assert blob is not None and blob.deleted_at is not None
        assert occurrence.current_run_id == current_run_id
        assert summary is not None
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert (
            session.scalar(select(func.count()).select_from(AnalysisSummary))
            == before_summary_count
        )
        assert (
            session.scalar(select(func.count()).select_from(GroupMembershipHistory))
            == before_history_count
        )
        retention_logs = session.scalars(
            select(OperationLog).where(
                OperationLog.action == "retention.expire",
                OperationLog.target_id == blob.id,
            )
        ).all()
        assert len(retention_logs) == 1
        assert retention_logs[0].result == "deleted_raw_only"

    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}")
    assert detail.status_code == 200
    assert detail.json()["blob"]["deleted_at"] is not None
    # Canonical analysis is retained independently of the expired raw dump.
    analysis = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis")
    assert analysis.status_code == 200, analysis.text


def test_retention_never_marks_database_complete_after_storage_failure(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = harness.create_workspace("retention-storage-failure")
    completed = harness.upload_dump(workspace["id"], dump_bytes(41))
    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, completed["occurrence_id"])
        assert occurrence is not None
        blob = session.get(DumpBlob, occurrence.dump_blob_id)
        assert blob is not None and blob.expires_at is not None
        blob_id = blob.id
        expiration = blob.expires_at

    def timeout(_key: str) -> None:
        raise TimeoutError("simulated object-store timeout")

    monkeypatch.setattr(harness.app.state.store, "delete", timeout)
    assert (
        expire_dump_blobs(
            harness.app.state.database.sessions,
            harness.app.state.store,
            now=expiration + timedelta(seconds=1),
        )
        == 0
    )
    with harness.app.state.database.sessions() as session:
        blob = session.get(DumpBlob, blob_id)
        assert blob is not None and blob.deleted_at is None
        failed = session.scalar(
            select(OperationLog)
            .where(
                OperationLog.action == "retention.expire",
                OperationLog.target_id == blob_id,
            )
            .order_by(OperationLog.id.desc())
        )
        assert failed is not None
        assert failed.result == "object_delete_failed"
        assert failed.details == {"error_type": "TimeoutError"}

    def absent(_key: str) -> None:
        raise ObjectNotFoundError("already absent")

    monkeypatch.setattr(harness.app.state.store, "delete", absent)
    assert (
        expire_dump_blobs(
            harness.app.state.database.sessions,
            harness.app.state.store,
            now=expiration + timedelta(seconds=2),
        )
        == 1
    )
    with harness.app.state.database.sessions() as session:
        blob = session.get(DumpBlob, blob_id)
        assert blob is not None and blob.deleted_at is not None
        latest = session.scalar(
            select(OperationLog)
            .where(
                OperationLog.action == "retention.expire",
                OperationLog.target_id == blob_id,
            )
            .order_by(OperationLog.id.desc())
        )
        assert latest is not None and latest.result == "raw_already_absent"


@pytest.mark.capacity
def test_local_capacity_baseline_100_small_dumps_peak_five(
    harness: Phase1Harness,
    record_property: Any,
) -> None:
    """Run a fast deterministic 100-dump baseline with no more than five queued tasks."""

    dump_count = 100
    peak_limit = 5
    workspace = harness.create_workspace("capacity-baseline")
    dispatcher = harness.app.state.dispatcher
    max_pending = 0
    handled = 0
    upload_ids: list[str] = []
    occurrence_ids: list[str] = []
    started = time.perf_counter()

    for batch_start in range(0, dump_count, peak_limit):
        batch_upload_ids: list[str] = []
        for seed in range(batch_start, batch_start + peak_limit):
            upload = harness.initialize_dump(workspace["id"], dump_bytes(1_000 + seed))
            batch_upload_ids.append(upload["upload_id"])
            upload_ids.append(upload["upload_id"])
            max_pending = max(max_pending, len(dispatcher.snapshot()))
            assert len(dispatcher.snapshot()) <= peak_limit

        while dispatcher.snapshot():
            max_pending = max(max_pending, len(dispatcher.snapshot()))
            assert len(dispatcher.snapshot()) <= peak_limit
            handled += dispatcher.drain(limit=peak_limit)

        for upload_id in batch_upload_ids:
            terminal = harness.client.get(f"/api/v1/uploads/{upload_id}")
            assert terminal.status_code == 200, terminal.text
            body = terminal.json()
            assert body["verification_status"] == "ACCEPTED"
            assert body["occurrence_id"]
            occurrence_ids.append(body["occurrence_id"])

    elapsed = time.perf_counter() - started
    record_property("capacity_dump_count", dump_count)
    record_property("capacity_peak_pending_tasks", max_pending)
    record_property("capacity_elapsed_seconds", round(elapsed, 3))
    print(
        f"capacity baseline: dumps={dump_count} peak_pending={max_pending} "
        f"handled={handled} elapsed_seconds={elapsed:.3f}"
    )

    assert len(upload_ids) == dump_count
    assert len(occurrence_ids) == dump_count
    assert len(set(occurrence_ids)) == dump_count
    assert max_pending <= peak_limit
    assert handled == dump_count * 2  # verify + analyze per unique dump
    assert dispatcher.snapshot() == []
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DumpBlob)) == dump_count
        assert session.scalar(select(func.count()).select_from(Occurrence)) == dump_count
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == dump_count
        assert set(session.scalars(select(AnalysisRun.status))) <= {"COMPLETE", "PARTIAL"}
