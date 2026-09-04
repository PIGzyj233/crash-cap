"""C08: an unknown faulting DLL with an owned executable caller."""

import hashlib
import json
import os
import time

from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    TaskIntent,
    Upload,
    utcnow,
)
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.outbox_relay import relay_once
from fastapi.testclient import TestClient

from .test_frozen_delivery_redis import consume_in_fresh_process


def qualify_unknown_fault(live, redis_url, fixture, *, declare_owned=True):
    settings = Settings.model_validate(
        {
            **live["settings"].model_dump(),
            "queue_mode": "dramatiq",
            "redis_url": redis_url,
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
    app = create_app(settings)

    def drain(queue):
        relay_once(live["sessions"], app.state.dispatcher, settings, owner_id="c08-relay")
        consume_in_fresh_process(settings, live["sessions"], queue, timeout_seconds=90)

    try:
        with TestClient(app) as client:
            pairs = []
            for base, extension in (("null_read_target", "exe"), ("unknown_fault", "dll")):
                files = {"pe": fixture / f"{base}.{extension}", "pdb": fixture / f"{base}.pdb"}
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
                        "idempotency_key": "c08-" + base,
                        "source_label": "C08 native fixture",
                        "pairs": [{"client_pair_id": base, **claims}],
                    },
                )
                assert response.status_code == 201, response.text
                batch = response.json()
                item_id = batch["items"][0]["item_id"]
                item_path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item_id}"
                for kind, path in files.items():
                    response = client.put(item_path + "/files/" + kind, content=path.read_bytes())
                    assert response.status_code == 200, response.text
                assert client.post(item_path + "/complete").status_code == 202
                drain("ingest")
                item = client.get(f"/api/v2/symbol-imports/{batch['import_id']}").json()["items"][0]
                assert item["state"] == "available", item
                pairs.append(item["pair_id"])
            response = client.post("/api/v1/workspaces", json={"name": "c08-owned-caller"})
            assert response.status_code == 201, response.text
            workspace = response.json()["id"]
            metadata = json.loads((fixture / "pe-metadata.json").read_bytes())
            identity = {name: metadata[name] for name in ("code_id", "debug_id", "architecture")}
            if declare_owned:
                response = client.post(
                    f"/api/v2/workspaces/{workspace}/module-roles",
                    json={"identity": identity, "role": "owned"},
                )
                assert response.status_code == 201, response.text
                drain("ingest")
            payload = (fixture / "null-read.dmp").read_bytes()
            response = client.post(
                f"/api/v1/workspaces/{workspace}/dumps/uploads:init",
                json={"filename": "cross-module.dmp", "size": len(payload)},
            )
            assert response.status_code == 201, response.text
            upload_id = response.json()["upload_id"]
            with live["sessions"]() as session:
                key = session.get(Upload, upload_id).object_key
            live["store"].put_bytes(key, payload, "application/octet-stream")
            assert client.post(f"/api/v1/uploads/{upload_id}/complete", json={}).status_code == 200
            drain("verify")
            with live["sessions"]() as session:
                due = session.query(AnalysisDemand).one().not_before
            time.sleep(max(0, (due - utcnow()).total_seconds()))
            planner = AutomaticAnalysisPlanner(
                settings, live["sessions"], live["store"], CoreExecutor(settings)
            )
            assert planner.run_once(owner_id="c08-planner") == 1
            with live["sessions"]() as session:
                run_id = session.query(AnalysisExecutionSlot).one().run_id
                queue = (
                    session.query(TaskIntent).filter_by(logical_key=run_id).one().message["queue"]
                )
            drain(queue)
            with live["sessions"]() as session:
                run = session.get(AnalysisRun, run_id)
                assert run.status in {"COMPLETE", "PARTIAL"}, (run.status, run.error_code)
                raw = b"".join(live["store"].stream(run.result_object_key))
            canonical = json.loads(raw)
            (live["output"] / "c08-canonical.json").write_bytes(raw)
            modules = canonical["modules"]
            owned = next(m for m in modules if m["selection"]["selected_pair_id"] == pairs[0])
            unknown = next(m for m in modules if m["selection"]["selected_pair_id"] == pairs[1])
            assert owned["role"] == ("owned" if declare_owned else "unknown")
            assert unknown["role"] == "unknown"
            frames = [f for thread in canonical["threads"] for f in thread["frames"]]
            assert any(
                "unknown_module_fault" in (f.get("function") or "") and f.get("line")
                for f in frames
            )
            assert any(
                "owned_module_caller" in (f.get("function") or "") and f.get("line") for f in frames
            )
            assert bool(canonical["fingerprints"]["exact"]) is declare_owned
            assert (
                canonical["crash"]["fault_module_debug_id"]
                == unknown["selection"]["identity"]["debug_id"]
            )
            caller = next(f for f in frames if "owned_module_caller" in (f.get("function") or ""))
            assert caller["trust"] == "cfi" and caller["in_app"] is declare_owned
            assert caller["unwind_method"] == "call_frame_info"
            assert caller["module_index"] == owned["module_index"]
            assert canonical["quality"]["unwind_reliability"] == 1.0
            for metric in ("symbol_coverage", "artifact_completeness"):
                assert canonical["quality"][metric] == (1.0 if declare_owned else 0.0)
                if not declare_owned:
                    assert any(
                        w["message"] == f"{metric} denominator is zero"
                        for w in canonical["quality"]["warnings"]
                    )
            if not declare_owned:
                assert not any(f["in_app"] for f in frames)
                assert not any(m["in_app"] for m in modules)
            (live["output"] / "c08-result.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "case": "C08" if declare_owned else "C09",
                        "run_id": run_id,
                        "pair_ids": pairs,
                        "canonical_sha256": hashlib.sha256(raw).hexdigest(),
                        "fingerprints": canonical["fingerprints"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if os.getenv("CRASHCAP_QA_CROSS_MODULE_BROWSER") == "1":
                from .cross_module_browser import observe_report

                observe_report(settings, live, canonical, raw, "C08" if declare_owned else "C09")
            if declare_owned and os.getenv("CRASHCAP_QA_RESTORE") == "1":
                from .catalog_restore import qualify_restore

                qualify_restore(live)
    finally:
        app.state.dispatcher.broker.close()
