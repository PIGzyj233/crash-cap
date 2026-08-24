from __future__ import annotations

import hashlib
import json
from typing import Any

import crashcap_api.services.symbol_backfill as backfill_module
import pytest
from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisRun,
    DumpBlob,
    MissingSymbolOccurrence,
    Occurrence,
    SymbolProjectionGap,
    SymbolProjectionState,
    utcnow,
)
from crashcap_api.services.symbol_backfill import backfill_symbol_projection
from sqlalchemy import func, select

from .conftest import Phase1Harness, dump_bytes


def _canonical_bytes(harness: Phase1Harness, occurrence_id: str) -> tuple[str, bytes]:
    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        assert occurrence is not None and occurrence.current_run_id
        run = session.get(AnalysisRun, occurrence.current_run_id)
        assert run is not None and run.result_object_key
        key = run.result_object_key
    return key, b"".join(harness.app.state.store.stream(key))


def test_backfill_dry_run_resume_idempotency_and_expired_raw_dump(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("symbol-backfill-resume")
    first = harness.upload_dump(workspace["id"], dump_bytes(701))["occurrence_id"]
    second = harness.upload_dump(workspace["id"], dump_bytes(702))["occurrence_id"]
    assert first and second

    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, first)
        assert occurrence is not None
        blob = session.get(DumpBlob, occurrence.dump_blob_id)
        assert blob is not None
        blob.deleted_at = utcnow()
        raw_key = blob.object_key
        session.commit()
    harness.app.state.store.delete(raw_key)

    dry_run = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        limit=1,
    )
    assert dry_run["mode"] == "dry-run"
    assert dry_run["scanned"] == 1
    assert dry_run["projected"] == 1
    assert dry_run["has_more"] is True
    assert dry_run["durable_checkpoint"] is None

    first_batch = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        limit=1,
        apply=True,
    )
    assert first_batch["projected"] == 1
    assert first_batch["backfill_remaining"] == 1
    assert first_batch["next_cursor"]
    assert first_batch["durable_checkpoint"]["completed_at"] is None

    second_batch = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        limit=1,
        apply=True,
    )
    assert second_batch["projected"] == 1
    assert second_batch["backfill_remaining"] == 0
    assert second_batch["unresolved_gaps"] == 0
    assert second_batch["durable_checkpoint"]["scanned_count"] == 2
    assert second_batch["durable_checkpoint"]["projected_count"] == 2
    assert second_batch["durable_checkpoint"]["completed_at"] is not None

    idempotent = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        apply=True,
    )
    assert idempotent["scanned"] == 0
    assert idempotent["backfill_remaining"] == 0
    with harness.app.state.database.sessions() as session:
        states = list(session.scalars(select(SymbolProjectionState)))
        assert {state.occurrence_id for state in states} == {first, second}
        assert all(state.source == "backfill" for state in states)
        assert (
            int(session.scalar(select(func.count()).select_from(MissingSymbolOccurrence)) or 0) == 2
        )


def test_backfill_records_missing_corrupt_and_semantic_gaps_then_retries(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("symbol-backfill-gaps")
    occurrence_ids = [
        harness.upload_dump(workspace["id"], dump_bytes(seed))["occurrence_id"]
        for seed in (711, 712, 713)
    ]
    assert all(occurrence_ids)
    originals: dict[str, bytes] = {}
    keys: list[str] = []
    for occurrence_id in occurrence_ids:
        key, payload = _canonical_bytes(harness, occurrence_id)
        keys.append(key)
        originals[key] = payload

    harness.app.state.store.delete(keys[0])
    harness.app.state.store.put_bytes(keys[1], b"{not-json", "application/json")
    invalid_identity = json.loads(originals[keys[2]])
    invalid_identity["workspace_id"] = "wsp_semantically_wrong"
    harness.app.state.store.put_bytes(
        keys[2],
        json.dumps(invalid_identity, separators=(",", ":")).encode(),
        "application/json",
    )

    report = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        limit=10,
        apply=True,
    )
    assert report["projected"] == 0
    assert report["gaps"] == 3
    assert report["backfill_remaining"] == 3
    assert report["unresolved_gaps"] == 3
    assert {case["gap_reason"] for case in report["cases"]} == {
        "object_missing",
        "object_corrupt",
        "semantic_invalid",
    }
    with harness.app.state.database.sessions() as session:
        gaps = list(session.scalars(select(SymbolProjectionGap)))
        assert all(gap.resolved_at is None and gap.attempt_count == 1 for gap in gaps)

    for key, payload in originals.items():
        harness.app.state.store.put_bytes(key, payload, "application/json")
    retried = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        limit=10,
        apply=True,
        retry_gaps=True,
    )
    assert retried["projected"] == 3
    assert retried["gaps"] == 0
    assert retried["backfill_remaining"] == 0
    assert retried["unresolved_gaps"] == 0
    with harness.app.state.database.sessions() as session:
        gaps = list(session.scalars(select(SymbolProjectionGap)))
        assert all(gap.resolved_at is not None for gap in gaps)


def test_backfill_rechecks_current_pointer_under_lock(
    harness: Phase1Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = harness.create_workspace("symbol-backfill-pointer-race")
    occurrence_id = harness.upload_dump(workspace["id"], dump_bytes(721))["occurrence_id"]
    assert occurrence_id
    original_prepare = backfill_module._prepare_candidate

    def prepare_and_advance(*args: Any, **kwargs: Any) -> Any:
        prepared = original_prepare(*args, **kwargs)
        with harness.app.state.database.sessions() as session:
            occurrence = session.get(Occurrence, occurrence_id)
            assert occurrence is not None
            newer = AnalysisRun(
                id=new_id("run"),
                occurrence_id=occurrence.id,
                run_spec={},
                resolution_method="unresolved",
                core_version="test",
                core_image_digest="sha256:" + "0" * 64,
                symbolicator_version="test",
                symbol_inventory_version=0,
                idempotency_key=hashlib.sha256(new_id("run").encode()).hexdigest(),
                status="PARTIAL",
            )
            session.add(newer)
            session.flush()
            occurrence.current_run_id = newer.id
            session.commit()
        return prepared

    monkeypatch.setattr(backfill_module, "_prepare_candidate", prepare_and_advance)
    report = backfill_symbol_projection(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings.schema_root,
        apply=True,
    )
    assert report["projected"] == 0
    assert report["gaps"] == 1
    assert report["cases"][0]["gap_reason"] == "pointer_changed"
    with harness.app.state.database.sessions() as session:
        assert session.get(SymbolProjectionState, occurrence_id) is None
        gap = session.get(SymbolProjectionGap, occurrence_id)
        assert gap is not None and gap.reason == "pointer_changed"
