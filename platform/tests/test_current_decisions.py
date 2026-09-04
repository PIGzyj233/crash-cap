from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.evidence_comparison import (
    AnalysisEvidence,
    FaultAnchor,
    FrameEvidence,
    ModuleEvidence,
)
from crashcap_api.ids import new_id, new_ulid
from crashcap_api.models import (
    AnalysisRun,
    CurrentDecision,
    DumpBlob,
    Occurrence,
    TaskIntent,
    Workspace,
    utcnow,
)
from crashcap_api.services.current_decisions import (
    build_insufficient_evidence,
    build_native_evidence,
    parse_evidence_json,
    promote_current_by_evidence,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts"


def _run(occurrence_id: str, run_id: str, *, schema_version: str = "1.1") -> AnalysisRun:
    return AnalysisRun(
        id=run_id,
        occurrence_id=occurrence_id,
        run_spec={
            "reason": "symbol_refresh",
            "dump": {"sha256": "d" * 64},
            "inspect": {"sha256": "e" * 64},
            "context_sha256": "f" * 64,
        },
        resolution_method="unresolved",
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        schema_version=schema_version,
        assembly_mode="core-final" if schema_version == "1.1" else "legacy",
        symbol_inventory_version=0,
        idempotency_key=hashlib.sha256(run_id.encode()).hexdigest(),
        status="PARTIAL",
    )


def _evidence(run_id: str, occurrence_id: str) -> AnalysisEvidence:
    return AnalysisEvidence(
        run_id=run_id,
        occurrence_id=occurrence_id,
        dump_sha256="d" * 64,
        inspect_sha256="e" * 64,
        context_sha256="f" * 64,
        canonical_sha256=hashlib.sha256(run_id.encode()).hexdigest(),
        status="PARTIAL",
        reason="symbol_refresh",
        provenance="native_1.1",
        usable=True,
        pair_evidence_complete=True,
        fault=FaultAnchor("crash", 7, 0, 16, "0xc0000005", "write", "0x0"),
        modules=(
            ModuleEvidence(
                0,
                ("123456789", "a" * 33, "x86_64"),
                "owned",
                True,
                "unique",
                "b" * 64,
                "found",
            ),
        ),
        frames=(FrameEvidence(7, 0, 16, "context", True, "crash", "app.cpp", 9),),
    )


def _seed(session, *, with_current: bool):
    workspace_id = new_id("wsp")
    workspace = Workspace(id=workspace_id, name=f"current-decision-{workspace_id}")
    blob = DumpBlob(
        id=new_id("blob"),
        workspace_id=workspace.id,
        sha256="d" * 64,
        size=1,
        object_key=f"dumps/{workspace.id}/one.dmp",
        verification_status="ACCEPTED",
    )
    occurrence = Occurrence(
        id=new_id("occ"),
        workspace_id=workspace.id,
        dump_blob_id=blob.id,
        uploaded_at=utcnow(),
        occurred_at=utcnow(),
        time_source="uploaded",
    )
    session.add(workspace)
    session.flush()
    session.add(blob)
    session.flush()
    session.add(occurrence)
    session.flush()
    current = _run(occurrence.id, "run_00000000000000000000000001") if with_current else None
    candidate = _run(occurrence.id, "run_00000000000000000000000002")
    session.add_all([row for row in (current, candidate) if row is not None])
    session.flush()
    if current is not None:
        occurrence.current_run_id = current.id
    intent = TaskIntent(
        attempt_id=f"att_{new_ulid()}",
        schema_version="1.2",
        task_type="analyze_frozen_run",
        queue="dump-small",
        logical_key=candidate.id,
        target_type="analysis_run",
        target_id=candidate.id,
        message={},
    )
    session.add(intent)
    session.flush()
    return occurrence, current, candidate, intent


def test_native_and_legacy_evidence_are_explicit() -> None:
    run = _run("occ_native", "run_native")
    canonical = {
        "analysis_id": run.id,
        "occurrence_id": run.occurrence_id,
        "crash": {"type": "crash", "thread_id": 7, "address": "0x1010"},
        "symbol_resolution": {"context_sha256": "f" * 64, "inspect_sha256": "e" * 64},
        "modules": [
            {
                "module_index": 0,
                "image_base": "0x1000",
                "image_size": 4096,
                "role": "owned",
                "in_app": True,
                "status": "found",
                "selection": {
                    "identity": {
                        "code_id": "123456789",
                        "debug_id": "a" * 33,
                        "architecture": "x86_64",
                    },
                    "state": "unique",
                    "selected_pair_id": "b" * 64,
                    "candidates_complete": True,
                },
                "source_outcomes": [],
            }
        ],
        "threads": [
            {
                "id": 7,
                "frames": [
                    {
                        "module_index": 0,
                        "relative_addr": "0x10",
                        "unwind_method": "context",
                        "in_app": True,
                        "function": "crash",
                        "file": "app.cpp",
                        "line": 9,
                        "inline": False,
                    }
                ],
            }
        ],
    }
    payload = b"canonical-result"
    evidence = build_native_evidence(
        run,
        canonical,
        payload,
        {"exception": {"code": "0xc0000005", "access_type": "write", "fault_address": "0x0"}},
        schema_root=SCHEMAS,
    )
    assert evidence.fault == FaultAnchor("crash", 7, 0, 16, "0xc0000005", "write", "0x0")
    assert evidence.frames[0].key == (0, 16)
    assert evidence.canonical_sha256 == hashlib.sha256(payload).hexdigest()

    legacy = _run("occ_legacy", "run_legacy", schema_version="1.0")
    legacy.run_spec = {"blob": {"sha256": "a" * 64}}
    legacy_evidence = build_insufficient_evidence(legacy, b"legacy", schema_root=SCHEMAS)
    assert legacy_evidence.dump_sha256 == "a" * 64
    assert (legacy_evidence.provenance, legacy_evidence.pair_evidence_complete) == (
        "insufficient",
        False,
    )


def test_evidence_writer_is_default_off_and_rejects_unsafe_configuration(tmp_path: Path) -> None:
    base = Settings.for_test(tmp_path)
    assert base.evidence_promotion_enabled is False
    with pytest.raises(ValidationError, match="requires frozen analysis"):
        Settings.model_validate({**base.model_dump(), "evidence_promotion_enabled": True})
    with pytest.raises(ValueError, match="duplicate object key"):
        parse_evidence_json(b'{"one":1,"one":2}', "test evidence")


def test_initial_promotion_persists_one_immutable_decision(tmp_path: Path) -> None:
    database = Database(Settings.for_test(tmp_path))
    try:
        with database.sessions.begin() as session:
            occurrence, _, candidate, intent = _seed(session, with_current=False)
            result = promote_current_by_evidence(
                session,
                occurrence,
                candidate,
                _evidence(candidate.id, occurrence.id),
                None,
                execution_attempt_id=intent.attempt_id,
                execution_generation=1,
                schema_root=SCHEMAS,
            )
            assert (result.promoted, result.decision.reason) == (True, "initial")
            evidence = _evidence(candidate.id, occurrence.id)
            with pytest.raises(RuntimeError, match="immutable Current decision"):
                promote_current_by_evidence(
                    session,
                    occurrence,
                    candidate,
                    evidence,
                    evidence,
                    execution_attempt_id=intent.attempt_id,
                    execution_generation=1,
                    schema_root=SCHEMAS,
                )
        with database.sessions() as session:
            decision = session.get(CurrentDecision, "run_00000000000000000000000002")
            occurrence = session.get(Occurrence, occurrence.id)
            assert decision is not None and decision.observed_current_run_id is None
            assert occurrence is not None and occurrence.current_run_id == decision.candidate_run_id
    finally:
        database.dispose()


def test_incomparable_candidate_retains_current_and_pointer_changes_fail(tmp_path: Path) -> None:
    database = Database(Settings.for_test(tmp_path))
    try:
        with database.sessions.begin() as session:
            occurrence, current, candidate, intent = _seed(session, with_current=True)
            assert current is not None
            current_evidence = _evidence(current.id, occurrence.id)
            candidate_evidence = replace(
                _evidence(candidate.id, occurrence.id),
                fault=replace(current_evidence.fault, fault_address="0x8"),
            )
            result = promote_current_by_evidence(
                session,
                occurrence,
                candidate,
                candidate_evidence,
                current_evidence,
                execution_attempt_id=intent.attempt_id,
                execution_generation=1,
                schema_root=SCHEMAS,
            )
            assert (result.promoted, result.decision.reason) == (False, "fault_changed")
            assert occurrence.current_run_id == current.id

        with database.sessions.begin() as session:
            occurrence = session.get(Occurrence, occurrence.id)
            candidate = session.get(AnalysisRun, candidate.id)
            assert occurrence is not None and candidate is not None
            with pytest.raises(RuntimeError, match="Current changed"):
                promote_current_by_evidence(
                    session,
                    occurrence,
                    candidate,
                    _evidence(candidate.id, occurrence.id),
                    None,
                    execution_attempt_id=intent.attempt_id,
                    execution_generation=1,
                    schema_root=SCHEMAS,
                )
    finally:
        database.dispose()


def test_automatic_correction_candidate_waits_for_post_result_review(tmp_path: Path) -> None:
    database = Database(Settings.for_test(tmp_path))
    try:
        with database.sessions.begin() as session:
            occurrence, current, candidate, intent = _seed(session, with_current=True)
            assert current is not None
            current_evidence = _evidence(current.id, occurrence.id)
            candidate_evidence = replace(
                _evidence(candidate.id, occurrence.id),
                reason="evidence_correction",
                frames=(),
            )
            result = promote_current_by_evidence(
                session, occurrence, candidate, candidate_evidence, current_evidence,
                execution_attempt_id=intent.attempt_id,
                execution_generation=1, schema_root=SCHEMAS,
            )
            assert not result.promoted
            assert result.decision.decision == "incomparable"
            assert occurrence.current_run_id == current.id
        with database.sessions() as session:
            decision = session.get(CurrentDecision, candidate.id)
            assert decision is not None
            assert decision.audit_id is None and decision.audit_sha256 is None
    finally:
        database.dispose()
