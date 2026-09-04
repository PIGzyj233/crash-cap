"""Native continuation of exact pre-existing 1.0 Current snapshots."""

import hashlib
import json
import os
import runpy
from datetime import datetime, timedelta
from pathlib import Path

from crashcap_api.models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    Base,
    CurrentDecision,
    Occurrence,
    TaskIntent,
    utcnow,
)
from crashcap_api.queueing import DramatiqTaskDispatcher
from crashcap_api.services.analysis_demands import ensure_demand
from crashcap_api.services.catalog_backfill import backfill_catalog
from crashcap_worker.automatic_analysis import AutomaticAnalysisPlanner
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.outbox_relay import relay_once
from sqlalchemy import DateTime, select, update

from .test_catalog_source_real import ROOT
from .test_catalog_source_real import live as live
from .test_catalog_source_real import pg as pg
from .test_catalog_source_real import pytestmark as pytestmark
from .test_frozen_delivery_redis import consume_in_fresh_process
from .test_frozen_delivery_redis import owned_redis as owned_redis


def test_historical_current_native_candidate(live, owned_redis):
    snapshot_path = Path(os.environ["QAI_HISTORICAL_SNAPSHOT"])
    loader = runpy.run_path(str(ROOT / "scripts/qa_symbol_import/replay_legacy_snapshot.py"))
    old, snapshot, snapshot_sha = loader["load_snapshot"](snapshot_path, live["store"])
    order = (
        "workspaces",
        "builds",
        "build_modules",
        "artifact_blobs",
        "artifacts",
        "dump_blobs",
        "task_intents",
        "occurrences",
        "analysis_runs",
    )
    assert set(item["table"] for item in snapshot["database_rows"]) <= set(order)
    with live["sessions"].begin() as session:
        for name in order:
            for item in snapshot["database_rows"]:
                if item["table"] != name:
                    continue
                table = Base.metadata.tables[name]
                values = dict(item["row"])
                for column in table.columns:
                    if isinstance(column.type, DateTime) and values.get(column.name) is not None:
                        values[column.name] = datetime.fromisoformat(values[column.name])
                if name == "occurrences":
                    values["current_run_id"] = None
                if name == "task_intents":
                    assert values["state"] in {"published", "dead"}
                session.execute(table.insert().values(**values))
        session.execute(
            update(Occurrence)
            .where(Occurrence.id == old.occurrence_id)
            .values(current_run_id=old.id)
        )
        demand_id = ensure_demand(session, old.occurrence_id, now=utcnow()).id
    settings = live["settings"].model_copy(
        update={
            "queue_mode": "dramatiq",
            "redis_url": owned_redis[0],
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
    planner = AutomaticAnalysisPlanner(
        settings, live["sessions"], live["store"], CoreExecutor(settings)
    )
    if os.environ.get("QAI_HISTORICAL_EXPIRED") == "1":
        assert snapshot["dump_blob"]["expires_at"] is not None
        evaluated_at = datetime.fromisoformat(snapshot["dump_blob"]["expires_at"]) + timedelta(
            seconds=1
        )
        planner.run_once(owner_id="historical-expired", now=evaluated_at)
        with live["sessions"]() as session:
            demand = session.get(AnalysisDemand, demand_id)
            assert demand.state == "cannot_recompute", (demand.state, demand.reason)
            assert demand.reason == "DUMP_UNAVAILABLE"
            assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
            assert session.scalar(select(AnalysisExecutionSlot)) is None
            assert len(session.scalars(select(AnalysisRun)).all()) == 1
        assert planner.run_once(owner_id="historical-expired-again", now=evaluated_at) == 0
        import pytest
        from crashcap_api.models import DumpBlob
        from crashcap_api.storage import ObjectNotFoundError
        from crashcap_worker.retention import expire_dump_blobs

        assert expire_dump_blobs(live["sessions"], live["store"], now=evaluated_at) == 1
        with pytest.raises(ObjectNotFoundError):
            live["store"].head(snapshot["dump_blob"]["object_key"])
        with live["sessions"]() as session:
            blob = session.get(DumpBlob, snapshot["dump_blob"]["id"])
            assert blob.deleted_at == evaluated_at
            assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
        preserved = 0
        for item in snapshot["objects"]:
            if item["status"] == "present" and item["key"] != snapshot["dump_blob"]["object_key"]:
                payload = b"".join(live["store"].stream(item["key"]))
                assert hashlib.sha256(payload).hexdigest() == item["sha256"]
                preserved += 1
        assert expire_dump_blobs(live["sessions"], live["store"], now=evaluated_at) == 0
        from crashcap_api.app import create_app
        from fastapi.testclient import TestClient

        expired_app = create_app(settings.model_copy(update={"automatic_analysis_enabled": False}))
        with TestClient(expired_app) as client:
            for path in (
                f"/api/v2/runs/{old.id}/analysis",
                f"/api/v2/occurrences/{old.occurrence_id}/analysis",
            ):
                response = client.get(path)
                assert response.status_code == 200, response.text
                assert response.content == b"".join(live["store"].stream(old.result_object_key))
        report = {
            "status": "PASS",
            "snapshot_sha256": snapshot_sha,
            "old_run_id": old.id,
            "evaluated_at": evaluated_at.isoformat(),
            "state": "cannot_recompute",
            "reason": "DUMP_UNAVAILABLE",
            "current_preserved": True,
            "new_runs": 0,
            "physical_dump_deleted": True,
            "other_objects_preserved": preserved,
            "retention_idempotent": True,
            "historical_and_current_http_readable": True,
            "scope": "isolated planner and retention after recorded expiry",
            "application_database_touched": False,
        }
        (live["output"] / "historical-expired-result.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return
    material_faults = []
    if os.environ.get("QAI_HISTORICAL_INCOMPLETE") != "1":
        for item in snapshot["database_rows"]:
            if item["table"] != "artifact_blobs":
                continue
            key = item["row"]["payload_object_key"]
            original = b"".join(live["store"].stream(key))
            try:
                live["store"].delete(key)
                unavailable = backfill_catalog(
                    live["sessions"],
                    live["store"],
                    CoreExecutor(settings.model_copy(update={"symbol_imports_enabled": True})),
                    apply=True,
                )
                assert unavailable["unresolved_records"] > 0
                assert all(case["pair_id"] is None for case in unavailable["cases"])
                assert {case["reason"] for case in unavailable["cases"]} == {
                    "HISTORICAL_OBJECT_MISSING"
                }, unavailable
                with live["sessions"]() as session:
                    assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
                material_faults.append({"key": key, "fault": "missing", "result": unavailable})
                damaged = bytes([original[0] ^ 1]) + original[1:]
                live["store"].put_bytes(key, damaged, "application/octet-stream")
                corrupted = backfill_catalog(
                    live["sessions"],
                    live["store"],
                    CoreExecutor(settings.model_copy(update={"symbol_imports_enabled": True})),
                    apply=True,
                )
                assert corrupted["unresolved_records"] > 0
                assert all(case["pair_id"] is None for case in corrupted["cases"])
                assert {case["reason"] for case in corrupted["cases"]} == {
                    "payload_sha256_mismatch"
                }, corrupted
                if os.environ.get("QAI_HISTORICAL_MATERIAL_BLOCKED") == "1":
                    planning_time = utcnow()
                    for attempt in range(1, settings.analysis_max_attempts + 1):
                        assert planner.run_once(owner_id="blocked-material", now=planning_time) == 1
                        with live["sessions"]() as session:
                            assert session.scalar(select(AnalysisExecutionSlot)) is None
                            assert (
                                session.get(Occurrence, old.occurrence_id).current_run_id == old.id
                            )
                            actual_runs = {run.id for run in session.scalars(select(AnalysisRun))}
                            expected_runs = {
                                row["row"]["id"]
                                for row in snapshot["database_rows"]
                                if row["table"] == "analysis_runs"
                            }
                            assert actual_runs == expected_runs
                            demand = session.get(AnalysisDemand, demand_id)
                            assert "WORKSPACE_PAIR_BACKFILL_REQUIRED" in demand.reason
                            if attempt < settings.analysis_max_attempts:
                                assert demand.state == "retry_wait"
                                planning_time = demand.not_before
                                assert planning_time is not None
                            else:
                                assert demand.state == "retry_exhausted"
                                terminal_reason = demand.reason
                    assert (
                        planner.run_once(
                            owner_id="blocked-material-later", now=planning_time + timedelta(days=1)
                        )
                        == 0
                    )
                    (live["output"] / "historical-material-blocked-result.json").write_text(
                        json.dumps(
                            {
                                "status": "PASS",
                                "snapshot_sha256": snapshot_sha,
                                "payload_key": key,
                                "state": "retry_exhausted",
                                "reason": terminal_reason,
                                "new_runs": 0,
                                "current_preserved": True,
                                "application_database_touched": False,
                            },
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    return
                with live["sessions"]() as session:
                    assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
                material_faults.append(
                    {"key": key, "fault": "same_length_corruption", "result": corrupted}
                )
            finally:
                live["store"].put_bytes(key, original, "application/octet-stream")
    backfill = backfill_catalog(
        live["sessions"],
        live["store"],
        CoreExecutor(settings.model_copy(update={"symbol_imports_enabled": True})),
        apply=True,
    )
    assert not backfill["has_more"]
    if os.environ.get("QAI_HISTORICAL_INCOMPLETE") == "1":
        assert backfill["unresolved_records"] == 1, backfill
        assert {case["reason"] for case in backfill["cases"]} == {"HISTORICAL_PAIR_INCOMPLETE"}
    else:
        assert backfill["unresolved_records"] == 0, backfill
    dispatcher = DramatiqTaskDispatcher(settings)
    old_bytes = b"".join(live["store"].stream(old.result_object_key))
    removed_auxiliary = {}
    corrupt_auxiliary = os.environ.get("QAI_HISTORICAL_AUXILIARY_CORRUPT") == "1"
    try:
        if os.environ.get("QAI_HISTORICAL_AUXILIARY_MISSING") == "1" or corrupt_auxiliary:
            for item in snapshot["objects"]:
                key = item["key"]
                if (
                    item["status"] == "present"
                    and key != old.result_object_key
                    and (
                        key == old.inspect_object_key
                        or (old.raw_object_prefix and key.startswith(old.raw_object_prefix))
                    )
                ):
                    removed_auxiliary[key] = b"".join(live["store"].stream(key))
                    if corrupt_auxiliary:
                        live["store"].put_bytes(key, b"not-json", "application/octet-stream")
                    else:
                        live["store"].delete(key)
            assert removed_auxiliary, "snapshot has no auxiliary objects to remove"
        assert planner.run_once(owner_id="historical-current", now=utcnow()) == 1
        with live["sessions"]() as session:
            slot = session.scalar(select(AnalysisExecutionSlot))
            assert slot is not None
            candidate_id = slot.run_id
            intent = session.scalar(
                select(TaskIntent).where(TaskIntent.logical_key == candidate_id)
            )
            queue = intent.message["queue"]
        assert relay_once(live["sessions"], dispatcher, settings, owner_id="historical-relay")
        missing_run_id = candidate_id
        live["store"].delete(old.result_object_key)
        try:
            consume_in_fresh_process(settings, live["sessions"], queue, timeout_seconds=90)
            with live["sessions"]() as session:
                failed = session.get(AnalysisRun, missing_run_id)
                assert failed.status == "FAILED"
                assert failed.error_code == "CURRENT_EVIDENCE_UNAVAILABLE"
                assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
                assert session.get(CurrentDecision, missing_run_id) is None
                assert session.scalar(select(AnalysisExecutionSlot)) is None
                demand = session.get(AnalysisDemand, demand_id)
                assert demand.state == "retry_wait" and demand.retry_attempt == 1
                retry_due = demand.not_before
                assert retry_due is not None
            if os.environ.get("QAI_HISTORICAL_EXHAUSTED") == "1":
                failed_runs = [missing_run_id]
                for attempt in range(2, settings.analysis_max_attempts + 1):
                    assert planner.run_once(owner_id="historical-exhaustion", now=retry_due) == 1
                    with live["sessions"]() as session:
                        slot = session.scalar(select(AnalysisExecutionSlot))
                        assert slot is not None and slot.run_id not in failed_runs
                        failed_id = slot.run_id
                        intent = session.scalar(
                            select(TaskIntent).where(TaskIntent.logical_key == failed_id)
                        )
                        queue = intent.message["queue"]
                    assert relay_once(
                        live["sessions"],
                        dispatcher,
                        settings,
                        owner_id="historical-exhaustion-relay",
                    )
                    consume_in_fresh_process(settings, live["sessions"], queue, timeout_seconds=90)
                    failed_runs.append(failed_id)
                    with live["sessions"]() as session:
                        failed = session.get(AnalysisRun, failed_id)
                        assert failed.status == "FAILED"
                        assert failed.error_code == "CURRENT_EVIDENCE_UNAVAILABLE"
                        assert session.get(CurrentDecision, failed_id) is None
                        assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
                        assert session.scalar(select(AnalysisExecutionSlot)) is None
                        demand = session.get(AnalysisDemand, demand_id)
                        if attempt < settings.analysis_max_attempts:
                            assert demand.state == "retry_wait"
                            retry_due = demand.not_before
                            assert retry_due is not None
                        else:
                            assert demand.state == "retry_exhausted"
                            assert "CURRENT_EVIDENCE_UNAVAILABLE" in demand.reason
                            terminal_reason = demand.reason
                assert (
                    planner.run_once(
                        owner_id="historical-exhausted-again", now=retry_due + timedelta(days=1)
                    )
                    == 0
                )
                (live["output"] / "historical-exhausted-result.json").write_text(
                    json.dumps(
                        {
                            "status": "PASS",
                            "snapshot_sha256": snapshot_sha,
                            "old_run_id": old.id,
                            "failed_run_ids": failed_runs,
                            "max_attempts": settings.analysis_max_attempts,
                            "state": "retry_exhausted",
                            "reason": terminal_reason,
                            "current_preserved": True,
                            "application_database_touched": False,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return
        finally:
            live["store"].put_bytes(old.result_object_key, old_bytes, "application/json")
        assert planner.run_once(owner_id="historical-restored", now=retry_due) == 1
        with live["sessions"]() as session:
            slot = session.scalar(select(AnalysisExecutionSlot))
            assert slot is not None and slot.run_id != missing_run_id
            candidate_id = slot.run_id
            intent = session.scalar(
                select(TaskIntent).where(TaskIntent.logical_key == candidate_id)
            )
            queue = intent.message["queue"]
        assert relay_once(
            live["sessions"], dispatcher, settings, owner_id="historical-restored-relay"
        )
        consume_in_fresh_process(settings, live["sessions"], queue, timeout_seconds=90)
        with live["sessions"]() as session:
            candidate = session.get(AnalysisRun, candidate_id)
            assert candidate.status in {"COMPLETE", "PARTIAL"}, (
                candidate.status,
                candidate.error_code,
                candidate.error_detail,
            )
            assert candidate.schema_version == "1.1"
            candidate_bytes = b"".join(live["store"].stream(candidate.result_object_key))
            canonical = json.loads(candidate_bytes)
            (live["output"] / "historical-candidate-canonical.json").write_bytes(candidate_bytes)
            admitted_pairs = {case["pair_id"] for case in backfill["cases"] if case["pair_id"]}
            if os.environ.get("QAI_HISTORICAL_INCOMPLETE") == "1":
                assert not admitted_pairs
                assert all(
                    module["selection"]["selected_pair_id"] is None
                    for module in canonical["modules"]
                )
            selected = {
                module["module_index"]: module["selection"]["selected_pair_id"]
                for module in canonical["modules"]
                if module["selection"]["selected_pair_id"] in admitted_pairs
            }
            frames = [
                frame
                for thread in canonical["threads"]
                for frame in thread["frames"]
                if frame["module_index"] in selected
                and frame.get("function")
                and frame.get("file")
                and (frame.get("line") or 0) > 0
            ]
            if admitted_pairs:
                assert set(selected.values()) == admitted_pairs
                assert frames, (
                    "admitted historical symbols produced no function/source-line evidence"
                )
            decision = session.get(CurrentDecision, candidate_id)
            assert decision.decision == "incomparable"
            assert session.get(Occurrence, old.occurrence_id).current_run_id == old.id
            assert session.get(AnalysisDemand, demand_id).state == "needs_review"
            assert session.scalar(select(AnalysisExecutionSlot)) is None
            assert b"".join(live["store"].stream(old.result_object_key)) == old_bytes
            report = {
                "status": "PASS",
                "snapshot_sha256": snapshot_sha,
                "old_run_id": old.id,
                "candidate_run_id": candidate_id,
                "candidate_canonical_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                "selected_historical_pairs": sorted(set(selected.values())),
                "symbolized_frames": [
                    {key: frame.get(key) for key in ("module_index", "function", "file", "line")}
                    for frame in frames
                ],
                "old_canonical_sha256": hashlib.sha256(old_bytes).hexdigest(),
                "decision": decision.decision,
                "reason": decision.reason,
                "current_preserved": True,
                "missing_current_recovery": {
                    "failed_run_id": missing_run_id,
                    "error_code": "CURRENT_EVIDENCE_UNAVAILABLE",
                    "retry_due": retry_due.isoformat(),
                    "restored_candidate_run_id": candidate_id,
                },
                "removed_auxiliary_keys": [] if corrupt_auxiliary else sorted(removed_auxiliary),
                "corrupted_auxiliary_keys": sorted(removed_auxiliary) if corrupt_auxiliary else [],
                "catalog_backfill": backfill,
                "historical_material_missing": material_faults,
                "application_database_touched": False,
                "restored_material_rows": sum(
                    item["table"] in {"build_modules", "artifacts", "artifact_blobs"}
                    for item in snapshot["database_rows"]
                ),
                "scope": "historical snapshot restored and catalog backfilled",
            }
        from crashcap_api.app import create_app
        from crashcap_api.models import ResultReview
        from fastapi.testclient import TestClient

        review_app = create_app(settings.model_copy(update={"result_reviews_enabled": True}))
        review_path = (
            f"/api/v2/workspaces/{snapshot['occurrence']['workspace_id']}"
            f"/occurrences/{old.occurrence_id}/result-reviews"
        )
        request = {
            "schema_version": "result-review-request-v1",
            "idempotency_key": "historical-snapshot-review",
            "current_run_id": old.id,
            "candidate_run_id": candidate_id,
            "current_canonical_sha256": report["old_canonical_sha256"],
            "candidate_canonical_sha256": report["candidate_canonical_sha256"],
            "cause": "engine_upgrade",
            "reviewed_by": "isolated historical qualification",
            "rationale": "Review exact historical 1.0 report and native 1.1 candidate",
            "basis_reviews": [],
        }
        try:
            with TestClient(review_app) as client:
                historical_failed = [
                    item["row"]["id"]
                    for item in snapshot["database_rows"]
                    if item["table"] == "analysis_runs" and item["row"]["status"] == "FAILED"
                ]
                for failed_id in historical_failed:
                    response = client.get(f"/api/v2/runs/{failed_id}/analysis")
                    assert response.status_code == 409, response.text
                    assert response.json()["error"]["code"] == "CONFLICT"
                report["historical_failed_http_checked"] = historical_failed
                response = client.post(review_path, json=request)
                assert response.status_code == 200, response.text
                reviewed = response.json()
                assert reviewed["decision"] == "promote"
                replay = client.post(review_path, json=request)
                assert replay.status_code == 200 and replay.json() == reviewed
                old_response = client.get(f"/api/v2/runs/{old.id}/analysis")
                assert old_response.status_code == 200
                assert old_response.content == old_bytes
                current_response = client.get(f"/api/v2/occurrences/{old.occurrence_id}/analysis")
                assert current_response.status_code == 200
                assert current_response.content == candidate_bytes
            with live["sessions"]() as session:
                assert session.get(Occurrence, old.occurrence_id).current_run_id == candidate_id
                assert session.get(CurrentDecision, candidate_id).decision == "incomparable"
                assert len(session.scalars(select(ResultReview)).all()) == 1
                assert session.get(AnalysisDemand, demand_id).state == "updated"
            report["explicit_review"] = {
                "id": reviewed["id"],
                "current_run_id": candidate_id,
                "idempotent": True,
                "historical_bytes_readable": True,
                "initial_decision_preserved": True,
            }
        finally:
            review_app.state.dispatcher.broker.close()
        (live["output"] / "historical-current-result.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        for key, payload in removed_auxiliary.items():
            live["store"].put_bytes(key, payload, "application/octet-stream")
        dispatcher.broker.close()
