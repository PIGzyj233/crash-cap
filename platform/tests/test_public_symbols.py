import hashlib
import json
import threading
import time
from contextlib import suppress
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisRun,
    CurrentDecision,
    Occurrence,
    PublicSymbolJob,
    TaskIntent,
    utcnow,
)
from crashcap_api.services.public_symbol_recovery import recover_public_symbol_jobs
from crashcap_api.task_handoff import claim_task
from crashcap_worker.public_symbols import download_pdb, pdb_identity, targets
from sqlalchemy import func, select

from .test_current_decisions import _seed

DEBUG = "a" * 32 + "1a"


def sample():
    inspect = {
        "modules": [
            {
                "code_file": "kernel32.dll",
                "code_id": "123456789",
                "debug_file": r"C:\symbols\Kernel32.pdb",
                "debug_id": DEBUG,
            },
            {
                "code_file": "avcodec-61.dll",
                "code_id": "65F46B2D57AC000",
                "debug_file": None,
                "debug_id": None,
            },
            {
                "code_file": "private.dll",
                "code_id": "123456789",
                "debug_file": "private.pdb",
                "debug_id": DEBUG,
            },
        ]
    }
    manifest = {
        "modules": [
            {
                "module_index": i,
                "identity": {"code_id": m["code_id"], "debug_id": m["debug_id"]},
                "state": "none" if i != 2 else "conflict",
            }
            for i, m in enumerate(inspect["modules"])
        ]
    }
    return inspect, manifest


def test_missing_identity_and_private_conflict_never_probe_public_source():
    inspect, manifest = sample()
    values = targets(inspect, manifest, None, 256)
    assert [(v["status"], v["reason"]) for v in values] == [
        ("pending", None),
        ("skipped", "debug_identity_unavailable"),
        ("skipped", "private_selection"),
    ]
    assert values[0]["debug_file"] == "kernel32.pdb"
    assert pdb_identity("a" * 32 + "01A") == DEBUG
    assert pdb_identity("../" + DEBUG) is None
    manifest["modules"][0]["identity"]["code_id"] = "different"
    with pytest.raises(ValueError, match="identity"):
        targets(inspect, manifest, None, 256)


@pytest.mark.parametrize("returned_identity", [DEBUG, "b" * 32 + "1"])
def test_job_deduplicates_and_does_not_create_analysis_or_change_current(
    harness, monkeypatch, returned_identity
):
    sessions, store = harness.app.state.database.sessions, harness.app.state.store
    inspect, manifest = sample()
    refs = {}
    for name, value in (("inspect", inspect), ("resolution_manifest", manifest)):
        payload = json.dumps(value).encode()
        refs[name] = {"object_key": f"test/{name}", "sha256": hashlib.sha256(payload).hexdigest()}
        store.put_bytes(refs[name]["object_key"], payload, "application/json")
    with sessions.begin() as session:
        occurrence, _, run, _ = _seed(session, with_current=False)
        run.status = "FAILED"
        run.run_spec = {**run.run_spec, **refs}
        wid, oid, rid = occurrence.workspace_id, occurrence.id, run.id
        before = [
            session.scalar(select(func.count()).select_from(table))
            for table in (AnalysisRun, AnalysisDemand, CurrentDecision)
        ]
    calls = []

    def download(_settings, item, destination, _deadline):
        calls.append(item["debug_file"])
        destination.write_bytes(
            b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00CRASHCAP_DEBUG_ID="
            + returned_identity.encode()
        )
        return {
            "status": "downloaded",
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }

    monkeypatch.setattr("crashcap_worker.public_symbols.download_pdb", download)
    endpoint = f"/api/v3/workspaces/{wid}/occurrences/{oid}/public-symbol-jobs"
    first = harness.client.post(endpoint, json={"idempotency_key": "once"})
    assert first.status_code == 202, first.text
    for key in ("once", "another-click"):
        assert (
            harness.client.post(endpoint, json={"idempotency_key": key}).json()["id"]
            == first.json()["id"]
        )
    with sessions() as session:
        task = session.scalar(
            select(TaskIntent).where(TaskIntent.task_type == "fetch_public_symbols")
        )
        message = dict(task.message)
    harness.app.state.processor.fetch_public_symbols(message)
    harness.app.state.processor.fetch_public_symbols(message)
    response = harness.client.get(endpoint).json()
    assert response["status"] == "completed", response
    assert response["source_run_id"] == rid
    assert response["items"][0]["status"] == (
        "downloaded" if returned_identity == DEBUG else "identity_mismatch"
    ), response
    assert calls == ["kernel32.pdb"]
    assert (
        harness.client.post(endpoint, json={"idempotency_key": "once"}).json()["id"]
        == first.json()["id"]
    )
    assert (
        harness.client.post(endpoint, json={"idempotency_key": "another-click"}).json()["id"]
        == first.json()["id"]
    )
    assert harness.client.get(endpoint.replace(wid, "wrong-workspace")).status_code == 404
    with sessions() as session:
        assert before == [
            session.scalar(select(func.count()).select_from(table))
            for table in (AnalysisRun, AnalysisDemand, CurrentDecision)
        ]
        assert session.get(Occurrence, oid).current_run_id is None
        assert session.scalar(select(func.count()).select_from(PublicSymbolJob)) == 1


@pytest.mark.parametrize("mode", ["missing", "redirect", "slow", "ok"])
def test_proxy_download_has_exact_path_no_redirect_and_total_deadline(harness, tmp_path, mode):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if mode == "slow":
                time.sleep(0.3)
            self.send_response(404 if mode == "missing" else 302 if mode == "redirect" else 200)
            self.send_header("Content-Length", "3")
            self.send_header("Location", "http://127.0.0.1:1/outside")
            self.end_headers()
            with suppress(OSError):
                self.wfile.write(b"pdb")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = harness.settings.model_copy(
        update={"frozen_symbolicator_url": f"http://127.0.0.1:{server.server_port}"}
    )
    try:
        item = targets(*sample(), None, 256)[0]
        if mode == "slow":
            with pytest.raises(TimeoutError):
                download_pdb(settings, item, tmp_path / "result.pdb", time.monotonic() + 0.1)
        else:
            result = download_pdb(settings, item, tmp_path / "result.pdb", time.monotonic() + 2)
            assert (
                result["status"]
                == {"missing": "not_found", "redirect": "failed", "ok": "downloaded"}[mode]
            )
        assert requests == [f"/proxy/kernel32.pdb/{DEBUG[:32]}1A/kernel32.pdb"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("case", ["fresh", "lost", "active", "expired", "exhausted"])
def test_durable_recovery_respects_leases_and_stops_after_three_deliveries(harness, case):
    sessions = harness.app.state.database.sessions
    with sessions.begin() as session:
        occurrence, _, _, _ = _seed(session, with_current=False)
        wid, oid = occurrence.workspace_id, occurrence.id
    response = harness.client.post(
        f"/api/v3/workspaces/{wid}/occurrences/{oid}/public-symbol-jobs",
        json={"idempotency_key": "recover"},
    )
    assert response.status_code == 202, response.text
    now = utcnow()
    with sessions.begin() as session:
        intent = session.scalar(
            select(TaskIntent).where(TaskIntent.task_type == "fetch_public_symbols")
        )
        intent.state, intent.delivery_attempts = "published", 3 if case == "exhausted" else 1
        intent.published_at = now - timedelta(seconds=3600 if case != "fresh" else 1)
        session.flush()
        if case in {"active", "expired", "exhausted"}:
            claim = claim_task(
                session,
                dict(intent.message),
                harness.settings.schema_root,
                lease_seconds=60,
                now=now - timedelta(seconds=120 if case != "active" else 0),
            )
            assert claim.acquired
            session.get(PublicSymbolJob, response.json()["id"]).status = "running"
        count = recover_public_symbol_jobs(session, harness.settings, now=now)
        assert count == (0 if case in {"fresh", "active"} else 1)
        assert intent.state == (
            "published"
            if case in {"fresh", "active"}
            else "dead"
            if case == "exhausted"
            else "pending"
        )
        job = session.get(PublicSymbolJob, response.json()["id"])
        assert (job.status == "failed") == (case == "exhausted")
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisDemand)) == 0
