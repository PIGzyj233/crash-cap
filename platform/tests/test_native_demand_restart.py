"""C20: actual native process timeout, finite Worker retries and API restart."""

import hashlib
import json
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    DumpBlob,
    Occurrence,
    TaskIntent,
    Workspace,
    utcnow,
)
from crashcap_api.queueing import DramatiqTaskDispatcher
from crashcap_api.services.analysis_demands import ensure_demand
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.outbox_relay import relay_once
from sqlalchemy import select

from .test_catalog_source_real import FIXTURE, admit
from .test_catalog_source_real import live as live
from .test_catalog_source_real import pg as pg
from .test_catalog_source_real import pytestmark as pytestmark
from .test_demand_restart_api import client_for
from .test_frozen_delivery_redis import consume_in_fresh_process
from .test_frozen_delivery_redis import owned_redis as owned_redis


def test_native_timeout_exhaustion_then_explicit_restart(live, owned_redis, tmp_path):
    admit(live)
    settings = live["settings"].model_copy(
        update={
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "automatic_analysis_enabled": True,
            "analysis_max_attempts": 2,
            "analysis_retry_base_seconds": 1,
            "analysis_retry_max_seconds": 1,
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
    sessions, store = live["sessions"], live["store"]
    workspace_id, blob_id, occurrence_id = new_id("wsp"), new_id("blob"), new_id("occ")
    payload = (FIXTURE / "null-read.dmp").read_bytes()
    dump_key = f"qualification/exhaustion/{blob_id}/dump.dmp"
    store.put_bytes(dump_key, payload, "application/octet-stream")
    uploaded_at = utcnow()
    with sessions.begin() as session:
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
    planner = AutomaticAnalysisPlanner(settings, sessions, store, CoreExecutor(settings))
    dispatcher = DramatiqTaskDispatcher(settings)
    release, observed = threading.Event(), threading.Event()

    class SlowSymbolicator(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.set()
            release.wait(30)
            self.close_connection = True

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowSymbolicator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    failed = []

    def consume(worker_settings):
        with sessions() as session:
            slot = session.get(AnalysisExecutionSlot, demand_id)
            assert slot is not None and slot.run_id
            run_id = slot.run_id
            intent = session.scalar(select(TaskIntent).where(TaskIntent.logical_key == run_id))
            queue = intent.message["queue"]
        assert relay_once(sessions, dispatcher, settings, owner_id="c20-relay")
        consume_in_fresh_process(worker_settings, sessions, queue, timeout_seconds=90)
        return run_id

    try:
        slow = settings.model_copy(
            update={
                "core_timeout_seconds": 5,
                "frozen_symbolicator_url": f"http://127.0.0.1:{server.server_port}",
            }
        )
        for attempt in range(2):
            assert (
                planner.run_once(owner_id="c20-planner", now=utcnow() + timedelta(seconds=2)) == 1
            )
            observed.clear()
            run_id = consume(slow)
            assert observed.is_set(), "Native Core never reached the delayed HTTP endpoint"
            with sessions() as session:
                run = session.get(AnalysisRun, run_id)
                demand = session.get(AnalysisDemand, demand_id)
                assert run.status == "TIMEOUT", (run.status, run.error_code, run.error_detail)
                assert demand.retry_attempt == 1  # Retry ordinal remains 1 when attempt 2 exhausts.
                assert demand.state == ("retry_wait" if attempt == 0 else "retry_exhausted")
                assert session.get(AnalysisExecutionSlot, demand_id) is None
                assert session.get(Occurrence, occurrence_id).current_run_id is None
                failed.append(
                    {"run_id": run_id, "error_code": run.error_code, "reason": demand.reason}
                )
        # A fresh coordinator and a far-future scan cannot reopen an exhausted cycle.
        restarted = AutomaticAnalysisPlanner(settings, sessions, store, CoreExecutor(settings))
        assert (
            restarted.run_once(owner_id="c20-after-restart", now=utcnow() + timedelta(days=1)) == 0
        )
        with sessions() as session:
            demand = session.get(AnalysisDemand, demand_id)
            generation = demand.generation
            body = dict(
                idempotency_key="c20-explicit-restart",
                expected_generation=generation,
                expected_sequence=demand.change_sequence,
                rationale="Delayed endpoint recovered",
            )
            assert len(list(session.scalars(select(AnalysisRun)))) == 2
        path = (
            f"/api/v3/workspaces/{workspace_id}/occurrences/{occurrence_id}"
            "/analysis-demand/restarts"
        )
        with client_for(sessions, tmp_path) as client:
            if os.environ.get("CRASHCAP_QA_DEMAND_RESTART_BROWSER") == "1":
                from .demand_restart_browser import run_browser_restart

                body, receipt = run_browser_restart(
                    settings,
                    live,
                    workspace_id,
                    occurrence_id,
                    demand_id,
                )
            else:
                response = client.post(path, json=body)
                assert response.status_code == 202, response.text
                receipt = response.json()
            assert planner.run_once(owner_id="c20-manual") == 1
            run_id = consume(settings)
            assert client.post(path, json=body).json() == receipt
        with sessions() as session:
            demand = session.get(AnalysisDemand, demand_id)
            run = session.get(AnalysisRun, run_id)
            assert run.status in {"COMPLETE", "PARTIAL"}, (run.status, run.error_detail)
            assert demand.state == "updated"
            assert demand.generation == generation + 1 and demand.retry_attempt == 0
            assert session.get(Occurrence, occurrence_id).current_run_id == run_id
            assert len(list(session.scalars(select(AnalysisRun)))) == 3
        (live["output"] / "demand-restart-native.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "failed": failed,
                    "restart_receipt": receipt,
                    "current_run_id": run_id,
                    "demand_id": demand_id,
                    "fault": "actual native Core process exceeds 5s while HTTP response is delayed",
                    "browser_verified": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        dispatcher.broker.close()
