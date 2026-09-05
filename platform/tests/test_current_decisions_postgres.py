from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest
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
    promote_current_by_evidence,
)
from sqlalchemy import select

from .test_current_decisions import _run
from .test_evidence_comparison import next_run, original, system_loss, transient
from .test_symbol_catalog_postgres import pg  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"),
        reason="requires owned catalog PostgreSQL",
    ),
]


def _seed_case(session, *, candidates: int = 1):
    workspace_id = new_id("wsp")
    blob_id = new_id("blob")
    occurrence_id = new_id("occ")
    token = new_ulid()
    current_id = f"run_{token}0"
    candidate_ids = [f"run_{token}{index + 1}" for index in range(candidates)]
    session.add(Workspace(id=workspace_id, name=workspace_id))
    session.flush()
    session.add(
        DumpBlob(
            id=blob_id,
            workspace_id=workspace_id,
            sha256="d" * 64,
            size=1,
            object_key=f"dumps/{workspace_id}/one.dmp",
            verification_status="ACCEPTED",
        )
    )
    session.flush()
    occurrence = Occurrence(
        id=occurrence_id,
        workspace_id=workspace_id,
        dump_blob_id=blob_id,
        uploaded_at=utcnow(),
        occurred_at=utcnow(),
        time_source="uploaded",
    )
    session.add(occurrence)
    session.flush()
    current = _run(occurrence_id, current_id)
    rows = [current]
    intents = []
    for candidate_id in candidate_ids:
        candidate = _run(occurrence_id, candidate_id)
        rows.append(candidate)
        intent = TaskIntent(
            attempt_id=f"att_{new_ulid()}",
            schema_version="1.2",
            task_type="analyze_frozen_run",
            queue="dump-small",
            logical_key=candidate_id,
            target_type="analysis_run",
            target_id=candidate_id,
            message={},
        )
        intents.append(intent)
    session.add_all(rows)
    session.flush()
    occurrence.current_run_id = current_id
    session.add_all(intents)
    session.flush()
    return occurrence, current, rows[1:], intents


def _evidence_pair(current_id: str, candidate_id: str, occurrence_id: str):
    current = replace(
        original(),
        run_id=current_id,
        occurrence_id=occurrence_id,
    )
    candidate = replace(
        next_run(current),
        run_id=candidate_id,
        occurrence_id=occurrence_id,
    )
    return current, candidate


@pytest.mark.skipif(
    os.getenv("QAI_NATIVE_FAILURE_COMPARISON") != "1",
    reason="requires explicit current native source qualification artifacts",
)
def test_native_failure_reports_preserve_postgres_current(pg):  # noqa: F811
    from crashcap_api.services.current_decisions import build_native_evidence

    base = ROOT / "target/qa-symbol-import"
    native = base / "native-source"
    receipt = json.loads((native / "progress.json").read_bytes())
    assert receipt["status"] == "PASS"
    for name, digest in receipt["files"].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    inspection = json.loads((base / "frozen-context/inspect.json").read_bytes())
    rows, evidence = [], []
    for mode in (None, "native-missing", "native-unavailable"):
        spec_path = native / f"{mode}-run.json" if mode else base / "frozen-context/run.json"
        report_path = native / (f"{mode}-canonical.json" if mode else "canonical.json")
        spec, payload = json.loads(spec_path.read_bytes()), report_path.read_bytes()
        row = _run(spec["occurrence_id"], spec["run_id"])
        row.run_spec = spec
        row.idempotency_key = spec["idempotency_key"]
        rows.append(row)
        evidence.append(
            build_native_evidence(
                row,
                json.loads(payload),
                payload,
                inspection,
                schema_root=SCHEMAS,
            )
        )
    _, sessions, _ = pg
    workspace_id = rows[0].run_spec["context"]["workspace_id"]
    with sessions.begin() as session:
        session.add(Workspace(id=workspace_id, name="native fault comparison"))
        session.flush()
        session.add(
            DumpBlob(
                id="blob_native_fault",
                workspace_id=workspace_id,
                sha256=evidence[0].dump_sha256,
                size=rows[0].run_spec["dump"]["size"],
                object_key="native-fault/dump",
                verification_status="ACCEPTED",
            )
        )
        session.flush()
        occurrence = Occurrence(
            id=rows[0].occurrence_id,
            workspace_id=workspace_id,
            dump_blob_id="blob_native_fault",
            uploaded_at=utcnow(),
            occurred_at=utcnow(),
            time_source="uploaded",
        )
        session.add(occurrence)
        session.flush()
        session.add_all(rows)
        session.flush()
        occurrence.current_run_id = rows[0].id
        for row in rows[1:]:
            session.add(
                TaskIntent(
                    attempt_id=f"att_{row.id}",
                    schema_version="1.2",
                    task_type="analyze_frozen_run",
                    queue="dump-small",
                    logical_key=row.id,
                    target_type="analysis_run",
                    target_id=row.id,
                    message={},
                )
            )
    results = []
    for row, candidate, expected in zip(
        rows[1:],
        evidence[1:],
        ("permanent_loss", "business_transient_loss"),
        strict=True,
    ):
        with sessions.begin() as session:
            outcome = promote_current_by_evidence(
                session,
                occurrence,
                row,
                candidate,
                evidence[0],
                execution_attempt_id=f"att_{row.id}",
                execution_generation=1,
                schema_root=SCHEMAS,
            )
            assert not outcome.promoted
            assert outcome.decision.reason == expected
            assert session.get(Occurrence, occurrence.id).current_run_id == rows[0].id
        with (
            pytest.raises(RuntimeError, match="already has an immutable"),
            sessions.begin() as session,
        ):
            promote_current_by_evidence(
                session,
                occurrence,
                row,
                candidate,
                evidence[0],
                execution_attempt_id=f"att_{row.id}",
                execution_generation=1,
                schema_root=SCHEMAS,
            )
        results.append(outcome.decision.as_dict())
    with sessions() as session:
        assert session.query(CurrentDecision).count() == 2
        assert session.get(Occurrence, occurrence.id).current_run_id == rows[0].id
    (base / "native-failure-postgres-result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "current_run_id": rows[0].id,
                "decisions": results,
                "duplicate_decisions_rejected": True,
                "scope": "product Current transaction; no fault Worker execution",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_postgres_result_review_history_constraints(pg) -> None:  # noqa: F811
    from alembic import command
    from crashcap_api.models import ResultReview
    from sqlalchemy import delete, inspect, update
    from sqlalchemy.exc import DBAPIError, IntegrityError

    engine, sessions, config = pg
    assert {c["name"] for c in inspect(engine).get_columns("result_reviews")} == set(
        ResultReview.__table__.columns.keys()
    )
    with sessions.begin() as session:
        occurrence, current, candidates, intents = _seed_case(session)
        candidate, intent = candidates[0], intents[0]
        old, new = _evidence_pair(current.id, candidate.id, occurrence.id)
        promote_current_by_evidence(
            session,
            occurrence,
            candidate,
            new,
            old,
            execution_attempt_id=intent.attempt_id,
            execution_generation=1,
            schema_root=SCHEMAS,
        )
        session.flush()
        original_decision = session.get(CurrentDecision, candidate.id).decision
        row = {
            "id": f"rrv_{new_ulid()}",
            "occurrence_id": occurrence.id,
            "current_run_id": current.id,
            "candidate_run_id": candidate.id,
            "idempotency_key": "fixture-review",
            "request_sha256": "a" * 64,
            "request": {},
            "audit_object_key": "fixture/review.json",
            "audit_sha256": "b" * 64,
            "cause": "engine_upgrade",
            "decision": "promote",
            "reason": "reviewed_transition",
            "current_evidence": old.as_dict(),
            "candidate_evidence": new.as_dict(),
            "differences": [],
        }
        session.add(ResultReview(**row))
    for changes in (
        {"id": f"rrv_{new_ulid()}"},
        {
            "id": f"rrv_{new_ulid()}",
            "idempotency_key": "missing-first-decision",
            "candidate_run_id": current.id,
        },
        {"id": f"rrv_{new_ulid()}", "idempotency_key": "same-run", "current_run_id": candidate.id},
    ):
        with pytest.raises(IntegrityError), sessions.begin() as session:
            session.add(ResultReview(**{**row, **changes}))
            session.flush()
    for statement in (
        update(ResultReview).where(ResultReview.id == row["id"]).values(reason="rewritten"),
        delete(ResultReview).where(ResultReview.id == row["id"]),
    ):
        with (
            pytest.raises(DBAPIError, match="immutable history cannot be changed"),
            sessions.begin() as session,
        ):
            session.execute(statement)
    with pytest.raises(RuntimeError, match="Restore"):
        command.downgrade(config, "base")
    with sessions() as session:
        assert session.get(ResultReview, row["id"]).reason == "reviewed_transition"
        assert session.get(CurrentDecision, candidate.id).decision == original_decision
        assert session.get(Occurrence, occurrence.id).current_run_id == candidate.id


def test_postgres_persists_full_evidence_decision_matrix(pg) -> None:  # noqa: F811
    _, sessions, _ = pg
    cases = (
        ("equivalent", lambda old, new: new, "promote", "equivalent"),
        (
            "improved",
            lambda old, new: replace(new, frames=(replace(old.frames[0], line=7), old.frames[1])),
            "promote",
            "improved",
        ),
        (
            "q16",
            lambda old, new: replace(system_loss(old), run_id=new.run_id),
            "promote",
            "q16_system_transient",
        ),
        (
            "business-retain",
            lambda old, new: replace(
                new,
                frames=(replace(old.frames[0], function=None), old.frames[1]),
                modules=(replace(old.modules[0], sources=(transient(),)), old.modules[1]),
            ),
            "retain",
            "business_transient_loss",
        ),
        (
            "permanent-retain",
            lambda old, new: replace(
                system_loss(old),
                run_id=new.run_id,
                modules=(old.modules[0], replace(old.modules[1], symbol_status="missing")),
            ),
            "retain",
            "permanent_loss",
        ),
        (
            "incomparable",
            lambda old, new: replace(
                new, frames=(replace(old.frames[0], function="different"), old.frames[1])
            ),
            "incomparable",
            "interpretation_changed",
        ),
    )
    observed = []
    for name, mutate, expected_decision, expected_reason in cases:
        with sessions.begin() as session:
            occurrence, current_run, candidates, intents = _seed_case(session)
            candidate_run = candidates[0]
            current, candidate = _evidence_pair(current_run.id, candidate_run.id, occurrence.id)
            candidate = mutate(current, candidate)
            result = promote_current_by_evidence(
                session,
                occurrence,
                candidate_run,
                candidate,
                current,
                execution_attempt_id=intents[0].attempt_id,
                execution_generation=1,
                schema_root=SCHEMAS,
            )
            assert (result.decision.decision, result.decision.reason) == (
                expected_decision,
                expected_reason,
            )
            expected_current = (
                candidate_run.id if expected_decision == "promote" else current_run.id
            )
            assert occurrence.current_run_id == expected_current
            observed.append((name, result.decision.decision, result.decision.reason))
    assert len(observed) == len(cases)


def test_postgres_automatic_correction_requires_post_result_review(pg) -> None:  # noqa: F811
    _, sessions, _ = pg
    with sessions.begin() as session:
        occurrence, current_run, candidates, intents = _seed_case(session)
        candidate_run = candidates[0]
        current, candidate = _evidence_pair(current_run.id, candidate_run.id, occurrence.id)
        candidate = replace(candidate, reason="evidence_correction", frames=())
        result = promote_current_by_evidence(
            session,
            occurrence,
            candidate_run,
            candidate,
            current,
            execution_attempt_id=intents[0].attempt_id,
            execution_generation=1,
            schema_root=SCHEMAS,
        )
        assert not result.promoted
        assert result.decision.decision == "incomparable"
    with sessions() as session:
        decision = session.get(CurrentDecision, candidate_run.id)
        occurrence = session.get(Occurrence, occurrence.id)
        assert decision is not None and decision.audit_sha256 is None
        assert occurrence is not None and occurrence.current_run_id == current_run.id


def test_postgres_occurrence_lock_rejects_late_competing_current(pg) -> None:  # noqa: F811
    _, sessions, _ = pg
    with sessions.begin() as session:
        occurrence, current_run, candidates, intents = _seed_case(session, candidates=2)
        occurrence_id = occurrence.id
        current, first = _evidence_pair(current_run.id, candidates[0].id, occurrence_id)
        _, second = _evidence_pair(current_run.id, candidates[1].id, occurrence_id)
        first_id, second_id = candidates[0].id, candidates[1].id
        first_attempt, second_attempt = intents[0].attempt_id, intents[1].attempt_id

    second_started = threading.Event()
    second_result: list[str] = []

    def compete() -> None:
        second_started.set()
        try:
            with sessions.begin() as session:
                occurrence_row = session.get(Occurrence, occurrence_id)
                candidate_row = session.get(AnalysisRun, second_id)
                assert occurrence_row is not None and candidate_row is not None
                promote_current_by_evidence(
                    session,
                    occurrence_row,
                    candidate_row,
                    second,
                    current,
                    execution_attempt_id=second_attempt,
                    execution_generation=1,
                    schema_root=SCHEMAS,
                )
        except RuntimeError as error:
            second_result.append(str(error))

    with sessions.begin() as session:
        occurrence_row = session.scalar(
            select(Occurrence).where(Occurrence.id == occurrence_id).with_for_update()
        )
        candidate_row = session.get(AnalysisRun, first_id)
        assert occurrence_row is not None and candidate_row is not None
        thread = threading.Thread(target=compete)
        thread.start()
        assert second_started.wait(timeout=5)
        result = promote_current_by_evidence(
            session,
            occurrence_row,
            candidate_row,
            first,
            current,
            execution_attempt_id=first_attempt,
            execution_generation=1,
            schema_root=SCHEMAS,
        )
        assert result.promoted is True
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert second_result == ["Current changed before evidence comparison"]
    with sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        assert occurrence is not None and occurrence.current_run_id == first_id
        assert session.get(CurrentDecision, first_id) is not None
        assert session.get(CurrentDecision, second_id) is None


def test_postgres_projection_transaction_fault_rolls_back_pointer_and_decision(
    pg,  # noqa: F811
) -> None:
    _, sessions, _ = pg
    with sessions.begin() as session:
        occurrence, current_run, candidates, intents = _seed_case(session)
        occurrence_id = occurrence.id
        candidate_id = candidates[0].id
        current_id = current_run.id
        attempt_id = intents[0].attempt_id
        current, candidate = _evidence_pair(current_id, candidate_id, occurrence_id)
    with (
        pytest.raises(RuntimeError, match="qualified transaction fault"),
        sessions.begin() as session,
    ):
        occurrence = session.get(Occurrence, occurrence_id)
        candidate_run = session.get(AnalysisRun, candidate_id)
        assert occurrence is not None and candidate_run is not None
        promote_current_by_evidence(
            session,
            occurrence,
            candidate_run,
            candidate,
            current,
            execution_attempt_id=attempt_id,
            execution_generation=1,
            schema_root=SCHEMAS,
        )
        raise RuntimeError("qualified transaction fault")
    with sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        assert occurrence is not None and occurrence.current_run_id == current_id
        assert session.get(CurrentDecision, candidate_id) is None
