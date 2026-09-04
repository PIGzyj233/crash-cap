"""Actual HTTP faults through pinned Symbolicator, Core, Redis Worker and Current."""

from __future__ import annotations

import hashlib
import json
import os
import time

import httpx
import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
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
from crashcap_api.services.analysis_demands import fanout_next
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.responses import Response

from .test_catalog_source_real import FIXTURE, ROOT, admit
from .test_catalog_source_real import live as live
from .test_catalog_source_real import owned_redis as owned_redis
from .test_catalog_source_real import pg as pg
from .test_frozen_delivery_redis import consume_in_fresh_process

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("QAI_MATERIAL_REAL"), reason="requires owned native services"),
]


@pytest.mark.parametrize("case", ["q16", "q7", "404", "422", "500"])
def test_native_source_failure_current_and_retry(live, owned_redis, case):
    fixture = ROOT / "fixtures/qai-q16-system-wait/generated" if case == "q16" else FIXTURE
    source_state = {"failed": False}
    public_cache = {}
    public_events = []
    public_root = live["source_root"].replace("/v2/pairs", "/qualification-public/")

    @live["http_app"].get("/qualification-public/{path:path}")
    async def public_source(path: str):
        # Only the Q16 case uses real Microsoft system material. Other cases
        # expose the fixture through a public source before catalog admission.
        name = path.split("/")[0].lower()
        if name in {"null_read_target.exe", "null_read_target.pdb"}:
            if case == "q16":
                return Response(status_code=404)
            if path.split("/")[-1].lower() != name:
                return Response(status_code=404)
            return Response((fixture / name).read_bytes())
        if case != "q16":
            return Response(status_code=404)
        if source_state["failed"]:
            public_events.append({"path": path, "status": 503})
            return Response(status_code=503)
        if path not in public_cache:
            async with httpx.AsyncClient(follow_redirects=True, timeout=45) as client:
                response = await client.get("https://msdl.microsoft.com/download/symbols/" + path)
            assert len(response.content) <= 64 * 1024**2
            public_cache[path] = (response.status_code, response.content)
        status, payload = public_cache[path]
        public_events.append(
            {"path": path, "status": status, "sha256": hashlib.sha256(payload).hexdigest()}
        )
        return Response(payload, status_code=status)

    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
            "automatic_analysis_enabled": True,
            "automatic_analysis_global_limit": 1,
            "automatic_analysis_capacity": 1,
            "workspace_module_roles_enabled": True,
            "frozen_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "frozen_core_enabled": True,
            "core_image_digest": "sha256:" + "0" * 64,
            "frozen_allow_local_core_sentinel": True,
            "frozen_symbolicator_url": live["endpoint"],
            "frozen_pair_source_root": live["source_root"],
            "frozen_symbolicator_image_digest": live["image_id"],
            "symbolicator_version": live["version"],
            "frozen_public_sources": [
                {
                    "id": "qualification-public",
                    "type": "http",
                    "url": public_root,
                    "layout": {"type": "symstore"},
                    "filters": {"filetypes": ["pdb", "pe"]},
                    "is_public": True,
                }
            ],
        }
    )
    sessions, store = live["sessions"], live["store"]
    planner = AutomaticAnalysisPlanner(settings, sessions, store, CoreExecutor(settings))
    app = create_app(settings)
    results = []

    def drain(queue):
        relay_once(sessions, app.state.dispatcher, settings, owner_id="source-fault-relay")
        consume_in_fresh_process(settings, sessions, queue, timeout_seconds=120)

    def execute():
        with sessions() as session:
            due = session.get(AnalysisDemand, demand_id).not_before
        assert due is not None
        time.sleep(max(0, (due - utcnow()).total_seconds()))
        assert planner.run_once(owner_id="source-fault-planner") == 1
        with sessions() as session:
            run_id = session.get(AnalysisExecutionSlot, demand_id).run_id
            queue = session.scalar(
                select(TaskIntent).where(TaskIntent.logical_key == run_id)
            ).message["queue"]
        drain(queue)
        with sessions() as session:
            run = session.get(AnalysisRun, run_id)
            assert run.status in {"COMPLETE", "PARTIAL"}, (
                run.status,
                run.error_code,
                run.error_detail,
            )
            raw = b"".join(store.stream(run.result_object_key))
            canonical = json.loads(raw)
            decision = session.get(CurrentDecision, run_id)
            demand = session.get(AnalysisDemand, demand_id)
            current_id = session.get(Occurrence, occurrence_id).current_run_id
            result = {
                "run_id": run_id,
                "decision": decision.decision,
                "reason": decision.reason,
                "retry": decision.retry_recommended,
                "state": demand.state,
                "retry_attempt": demand.retry_attempt,
                "retry_delay_seconds": (
                    (demand.not_before - demand.updated_at).total_seconds()
                    if demand.not_before is not None else None
                ),
                "current_run_id": current_id,
                "canonical_sha256": hashlib.sha256(raw).hexdigest(),
            }
        (live["output"] / f"source-fault-{len(results)}.json").write_bytes(raw)
        results.append(result)
        (live["output"] / "source-fault-result.json").write_text(
            json.dumps(
                {"case": case, "results": results, "public_requests": public_events}, indent=2
            ),
            encoding="utf-8",
        )
        return result, canonical

    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/workspaces", json={"name": "native-source-fault"})
            assert response.status_code == 201, response.text
            workspace = response.json()["id"]
            metadata = json.loads((fixture / "pe-metadata.json").read_bytes())
            response = client.post(
                f"/api/v2/workspaces/{workspace}/module-roles",
                json={
                    "identity": {
                        key: metadata[key] for key in ("code_id", "debug_id", "architecture")
                    },
                    "role": "owned",
                },
            )
            assert response.status_code == 201, response.text
            drain("ingest")
            payload = (fixture / "null-read.dmp").read_bytes()
            response = client.post(
                f"/api/v1/workspaces/{workspace}/dumps/uploads:init",
                json={"filename": "source-fault.dmp", "size": len(payload)},
            )
            assert response.status_code == 201, response.text
            upload_id = response.json()["upload_id"]
            with sessions() as session:
                key = session.get(Upload, upload_id).object_key
            store.put_bytes(key, payload, "application/octet-stream")
            assert client.post(f"/api/v1/uploads/{upload_id}/complete", json={}).status_code == 200
            drain("verify")
            with sessions() as session:
                demand = session.scalar(select(AnalysisDemand))
                demand_id, occurrence_id = demand.id, demand.occurrence_id
            before, canonical = execute()
            assert before["decision"] == "promote"
            roles = {module["module_index"]: module["role"] for module in canonical["modules"]}
            assert any(
                frame.get("function")
                and roles.get(frame.get("module_index")) == ("system" if case == "q16" else "owned")
                for thread in canonical["threads"] for frame in thread["frames"]
            ), canonical["threads"]
            admit(live, fixture=fixture)
            with sessions.begin() as session:
                page = fanout_next(session, now=utcnow())
                assert occurrence_id in page.affected
            source_state["failed"] = True
            if case != "q16":
                live["faults"]["pair_status"] = 503 if case == "q7" else int(case)
            live["cold_cache"]()
            after, _ = execute()
            expected = {
                "q16": ("promote", "q16_system_transient", True),
                "q7": ("retain", "business_transient_loss", True),
                "404": ("retain", "permanent_loss", False),
                "422": ("retain", "permanent_loss", False),
                "500": ("incomparable", "unknown_loss", False),
            }[case]
            assert (after["decision"], after["reason"], after["retry"]) == expected, after
            if case in {"q16", "q7"}:
                assert after["state"] == "retry_wait" and after["retry_attempt"] == 1
                assert after["retry_delay_seconds"] == settings.analysis_retry_base_seconds
                for attempt in (2, 3):
                    live["cold_cache"]()
                    retry, _ = execute()
                    assert retry["retry"], retry
                    if attempt == 2:
                        assert retry["retry_delay_seconds"] == min(
                            settings.analysis_retry_base_seconds * 2,
                            settings.analysis_retry_max_seconds,
                        )
                    assert retry["state"] == (
                        "retry_wait" if attempt == 2 else "retry_exhausted"
                    ), retry
                assert planner.run_once(owner_id="exhausted-must-stop") == 0
                with sessions() as session:
                    demand = session.get(AnalysisDemand, demand_id)
                    body = {
                        "idempotency_key": "source-restored-explicit-restart",
                        "expected_generation": demand.generation,
                        "expected_sequence": demand.change_sequence,
                        "rationale": "HTTP source recovered after the finite retry budget",
                    }
                source_state["failed"] = False
                live["faults"]["pair_status"] = None
                live["cold_cache"]()
                restart_path = (
                    f"/api/v2/workspaces/{workspace}/occurrences/{occurrence_id}"
                    "/analysis-demand/restarts"
                )
                response = client.post(restart_path, json=body)
                assert response.status_code == 202, response.text
                receipt = response.json()
                restored, _ = execute()
                assert restored["state"] == "updated" and not restored["retry"], restored
                assert restored["current_run_id"] == restored["run_id"]
                assert client.post(restart_path, json=body).json() == receipt
                assert planner.run_once(owner_id="restored-must-stop") == 0
            else:
                assert after["current_run_id"] == before["run_id"]
                assert planner.run_once(owner_id="nonretry-must-stop") == 0
    finally:
        app.state.dispatcher.broker.close()
