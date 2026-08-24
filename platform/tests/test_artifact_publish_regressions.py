from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from crashcap_api.models import Artifact
from crashcap_worker.symbols import SymbolIngestError, SymbolIngestor
from sqlalchemy import select

from .conftest import Phase1Harness, pdb_bytes, pe_bytes

DEBUG_A = "a" * 32 + "1"
DEBUG_B = "b" * 32 + "1"


class RecordingSymbols:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Path, Path, str]] = []

    def publish_pair(self, workspace_id: str, pe_path: Path, pdb_path: Path, debug_id: str) -> None:
        self.calls.append((workspace_id, pe_path, pdb_path, debug_id))


class FailOnceSymbols(RecordingSymbols):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def publish_pair(self, workspace_id: str, pe_path: Path, pdb_path: Path, debug_id: str) -> None:
        if not self.failed:
            self.failed = True
            raise SymbolIngestError("injected symsorter failure")
        super().publish_pair(workspace_id, pe_path, pdb_path, debug_id)


def _queue_artifact(
    harness: Phase1Harness,
    build_id: str,
    kind: str,
    filename: str,
    payload: bytes,
) -> None:
    response = harness.client.post(
        f"/api/v1/builds/{build_id}/artifacts/uploads:init",
        json={"file_kind": kind, "filename": filename, "size": len(payload)},
    )
    assert response.status_code == 201, response.text
    upload = response.json()
    harness._seed_upload(upload["upload_id"], payload)
    completed = harness.client.post(f"/api/v1/uploads/{upload['upload_id']}/complete", json={})
    assert completed.status_code == 200, completed.text


def _artifacts(harness: Phase1Harness, build_id: str) -> dict[str, Artifact]:
    with harness.app.state.database.sessions() as session:
        rows = session.scalars(select(Artifact).where(Artifact.build_id == build_id)).all()
        return {row.kind: row for row in rows}


def test_pending_counterpart_is_not_published(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("pending-counterpart-no-publish")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    symbols = RecordingSymbols()
    harness.app.state.processor.symbols = symbols

    _queue_artifact(harness, build["id"], "pe", "app.exe", pe_bytes(DEBUG_A))
    _queue_artifact(harness, build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_A))
    assert harness.app.state.dispatcher.drain(limit=2) == 2
    assert {row.verification_status for row in _artifacts(harness, build["id"]).values()} == {
        "pending"
    }

    assert harness.app.state.dispatcher.drain(limit=1) == 1
    artifacts = _artifacts(harness, build["id"])
    assert artifacts["pe"].verification_status == "verified"
    assert artifacts["pdb"].verification_status == "pending"
    assert symbols.calls == []

    assert harness.app.state.dispatcher.drain(limit=1) == 1
    assert len(symbols.calls) == 1
    assert symbols.calls[0][3] == DEBUG_A


def test_debug_id_mismatch_is_not_published(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("debug-mismatch-no-publish")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    symbols = RecordingSymbols()
    harness.app.state.processor.symbols = symbols

    _queue_artifact(harness, build["id"], "pe", "app.exe", pe_bytes(DEBUG_A))
    _queue_artifact(harness, build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_B))
    harness.drain()

    artifacts = _artifacts(harness, build["id"])
    assert artifacts["pe"].verification_status == "verified"
    assert artifacts["pdb"].verification_status == "pdb_mismatch"
    assert symbols.calls == []


def test_publish_failure_keeps_artifact_pending_and_task_retry_can_commit(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("publish-failure-retry")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    symbols = FailOnceSymbols()
    harness.app.state.processor.symbols = symbols

    _queue_artifact(harness, build["id"], "pe", "app.exe", pe_bytes(DEBUG_A))
    _queue_artifact(harness, build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_A))
    assert harness.app.state.dispatcher.drain(limit=3) == 3
    with pytest.raises(SymbolIngestError, match="injected symsorter failure"):
        harness.app.state.dispatcher.drain(limit=1)

    artifacts = _artifacts(harness, build["id"])
    assert artifacts["pe"].verification_status == "verified"
    assert artifacts["pdb"].verification_status == "pending"
    assert symbols.calls == []

    harness.app.state.processor.ingest_artifact(
        {
            "schema_version": "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": artifacts["pdb"].id,
            "attempt_id": "att_retry_publish",
            "queue": "ingest",
        }
    )
    assert _artifacts(harness, build["id"])["pdb"].verification_status == "verified"
    assert len(symbols.calls) == 1


def _symsorter_settings(harness: Phase1Harness, root: Path) -> Any:
    return harness.settings.model_copy(
        update={
            "symbol_ingest_mode": "symsorter",
            "unified_symbol_root": root,
            "symsorter_command": "test-symsorter",
        }
    )


def _write_sorted_pair(output: Path, debug_id: str, pe: Path, pdb: Path) -> None:
    identity = output / debug_id[:2] / debug_id[2:]
    identity.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pe, identity / "executable")
    shutil.copyfile(pdb, identity / "debuginfo")
    (identity / "executable.meta").write_text("meta", encoding="utf-8")
    (identity / "debuginfo.meta").write_text("meta", encoding="utf-8")


def test_symsorter_failure_then_retry_never_exposes_partial_identity(
    harness: Phase1Harness, tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "unified"
    pe = tmp_path / "app.exe"
    pdb = tmp_path / "app.pdb"
    pe.write_bytes(b"verified-pe")
    pdb.write_bytes(b"verified-pdb")
    ingestor = SymbolIngestor(_symsorter_settings(harness, root))
    workspace_id = harness.create_workspace("symsorter-retry-staging")["id"]
    attempts = 0

    def run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        attempts += 1
        output = Path(command[2])
        if attempts == 1:
            partial = output / DEBUG_A[:2] / DEBUG_A[2:]
            partial.mkdir(parents=True)
            (partial / "debuginfo").write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "injected failure")
        _write_sorted_pair(output, DEBUG_A, pe, pdb)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("crashcap_worker.symbols.subprocess.run", run)
    target = root / workspace_id / DEBUG_A[:2] / DEBUG_A[2:]
    with pytest.raises(SymbolIngestError, match="symsorter exited 1"):
        ingestor.publish_pair(workspace_id, pe, pdb, DEBUG_A)
    assert not target.exists()

    target.mkdir(parents=True)
    (target / "debuginfo").write_bytes(b"old-partial")
    ingestor.publish_pair(workspace_id, pe, pdb, DEBUG_A)
    assert (target / "executable").read_bytes() == pe.read_bytes()
    assert (target / "debuginfo").read_bytes() == pdb.read_bytes()
    assert not list(target.parent.glob(f".{target.name}.backup-*"))

    ingestor.publish_pair(workspace_id, pe, pdb, DEBUG_A)
    assert attempts == 3
    assert (target / "debuginfo").read_bytes() == pdb.read_bytes()


def test_atomic_replace_failure_restores_existing_complete_identity(
    harness: Phase1Harness, tmp_path: Path, monkeypatch: Any
) -> None:
    root = tmp_path / "unified"
    pe = tmp_path / "app.exe"
    pdb = tmp_path / "app.pdb"
    pe.write_bytes(b"new-verified-pe")
    pdb.write_bytes(b"new-verified-pdb")
    ingestor = SymbolIngestor(_symsorter_settings(harness, root))
    workspace_id = harness.create_workspace("symsorter-atomic-restore")["id"]
    target = root / workspace_id / DEBUG_A[:2] / DEBUG_A[2:]
    target.mkdir(parents=True)
    for name, payload in {
        "executable": b"old-pe",
        "debuginfo": b"old-pdb",
        "executable.meta": b"old-meta",
        "debuginfo.meta": b"old-meta",
    }.items():
        (target / name).write_bytes(payload)

    def run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        _write_sorted_pair(Path(command[2]), DEBUG_A, pe, pdb)
        return subprocess.CompletedProcess(command, 0, "", "")

    real_replace = os.replace
    replace_calls = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("injected atomic promotion failure")
        real_replace(source, destination)

    monkeypatch.setattr("crashcap_worker.symbols.subprocess.run", run)
    monkeypatch.setattr("crashcap_worker.symbols.os.replace", fail_second_replace)
    with pytest.raises(SymbolIngestError, match="replacement failed"):
        ingestor.publish_pair(workspace_id, pe, pdb, DEBUG_A)

    assert (target / "executable").read_bytes() == b"old-pe"
    assert (target / "debuginfo").read_bytes() == b"old-pdb"
    assert (target / "executable.meta").read_bytes() == b"old-meta"
    assert (target / "debuginfo.meta").read_bytes() == b"old-meta"
