from __future__ import annotations

import hashlib

from crashcap_api.analysis_states import (
    ANALYSIS_STATES,
    ANALYSIS_TRANSITIONS,
    CURRENT_ELIGIBLE_STATES,
    TERMINAL_STATES,
)
from crashcap_api.ids import new_id
from crashcap_api.models import (
    ANALYSIS_STATUSES,
    AnalysisRun,
)
from crashcap_api.services.analysis_lifecycle import (
    fail_analysis,
    transition_analysis,
)


def _run(occurrence_id: str, status: str) -> AnalysisRun:
    run_id = new_id("run")
    return AnalysisRun(
        id=run_id,
        occurrence_id=occurrence_id,
        run_spec={"run_id": run_id},
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        symbol_inventory_version=0,
        idempotency_key=hashlib.sha256(run_id.encode()).hexdigest(),
        status=status,
    )


def test_lifecycle_vocabulary_is_closed_and_terminal_states_are_immutable() -> None:
    assert ANALYSIS_STATUSES is ANALYSIS_STATES
    assert set(ANALYSIS_TRANSITIONS) == ANALYSIS_STATES
    assert set().union(*ANALYSIS_TRANSITIONS.values()) <= ANALYSIS_STATES
    assert CURRENT_ELIGIBLE_STATES <= TERMINAL_STATES
    assert all(not ANALYSIS_TRANSITIONS[state] for state in TERMINAL_STATES)
    status_constraint = next(
        constraint
        for constraint in AnalysisRun.__table__.constraints
        if constraint.name == "ck_analysis_runs_status"
    )
    constraint_sql = str(status_constraint.sqltext)
    assert all(f"'{state}'" in constraint_sql for state in ANALYSIS_STATES)

    run = _run(new_id("occ"), "VALIDATING")
    assert fail_analysis(run, "TIMEOUT") == "TIMEOUT"
    assert run.status == "TIMEOUT"
    finished_at = run.finished_at
    assert fail_analysis(run, "PLATFORM_WORKER_FAILED") is None
    assert run.status == "TIMEOUT"
    assert run.finished_at == finished_at


def test_real_milestone_chain_sets_start_and_finish_times() -> None:
    run = _run(new_id("occ"), "UPLOADED")
    for state in (
        "VALIDATING",
        "INSPECTED",
        "MATCHING_SYMBOLS",
        "SYMBOLS_READY",
        "QUEUED",
        "ANALYZING",
        "NORMALIZING",
        "GROUPING",
        "COMPLETE",
    ):
        transition_analysis(run, state)
    assert run.started_at is not None
    assert run.finished_at is not None
