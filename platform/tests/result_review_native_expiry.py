"""Expired DMPs retain readable native reports and expose withdrawn basis."""

import hashlib
import json
import os
from datetime import timedelta

from crashcap_api.app import create_app
from crashcap_api.models import AnalysisRun, DumpBlob, Occurrence, SymbolProjectionState, utcnow
from crashcap_api.services.analysis_demands import fanout_next
from crashcap_worker.retention import expire_dump_blobs
from fastapi.testclient import TestClient
from sqlalchemy import select


def qualify_native_expiry(settings, live, occurrences, pair_id, planner):
    sessions, store = live["sessions"], live["store"]
    with sessions() as session:
        runs = set(session.scalars(select(AnalysisRun.id)))
        previous = {}
        for oid in occurrences.values():
            occurrence = session.get(Occurrence, oid)
            run = session.get(AnalysisRun, occurrence.current_run_id)
            previous[oid] = (
                occurrence.workspace_id,
                run.id,
                run.result_object_key,
                hashlib.sha256(b"".join(store.stream(run.result_object_key))).hexdigest(),
            )
        blobs = session.scalars(select(DumpBlob)).all()
        expiry = max(blob.expires_at for blob in blobs) + timedelta(seconds=1)
        blob_count = len(blobs)
    assert expire_dump_blobs(sessions, store, now=expiry) == blob_count
    with sessions() as session:
        assert all(blob.deleted_at is not None for blob in session.scalars(select(DumpBlob)))
    app = create_app(settings)
    statuses = {}
    try:
        with TestClient(app) as client:
            path = f"/api/v3/symbol-catalog/pairs/{pair_id}"
            origins = client.get(f"{path}/origins")
            assert origins.status_code == 200, origins.text
            review = client.post(
                f"{path}/reviews",
                json={
                    "expected_version": origins.json()["qualification_version"],
                    "state": "withdrawn",
                    "reason": "Qualification after actual DMP retention expiry",
                    "reviewer": "Isolated qualification reviewer",
                    "evidence": "Historical reports remain, but their symbol basis is withdrawn.",
                    "idempotency_key": "native-expired-dump-withdrawal",
                },
            )
            assert review.status_code == 200, review.text
            for _ in range(10):
                with sessions.begin() as session:
                    page = fanout_next(session, now=utcnow(), limit=1)
                if page.caught_up:
                    break
            else:
                raise AssertionError("Expiry withdrawal fanout did not finish")
            assert planner.run_once(owner_id="expired-dump-qualification", now=utcnow()) == 0
            for oid, (wid, run_id, object_key, digest) in previous.items():
                response = client.get(f"/api/v3/workspaces/{wid}/occurrences/{oid}/analysis-demand")
                assert response.status_code == 200, response.text
                status = response.json()
                assert status["state"] == "cannot_recompute", status
                assert status["current_run_id"] == run_id
                assert pair_id in status["withdrawn_basis_pair_ids"]
                assert hashlib.sha256(b"".join(store.stream(object_key))).hexdigest() == digest
                with sessions() as session:
                    assert session.get(Occurrence, oid).current_run_id == run_id
                    assert session.get(SymbolProjectionState, oid).analysis_run_id == run_id
                statuses[oid] = status
            with sessions() as session:
                assert set(session.scalars(select(AnalysisRun.id))) == runs
            (live["output"] / "native-expiry-result.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "expired_blob_count": blob_count,
                        "review": review.json(),
                        "demands": statuses,
                        "new_analysis_runs": 0,
                        "historical_canonical_bytes_preserved": True,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            if os.environ.get("CRASHCAP_QA_EXPIRY_BROWSER") == "1":
                from .result_review_expiry_browser import observe_expired_reports

                observe_expired_reports(settings, live, previous, statuses)
    finally:
        app.state.dispatcher.broker.close()
