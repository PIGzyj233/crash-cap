"""Metadata fixtures for browse/history tests; never used as Core execution evidence."""

from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisSummary,
    Occurrence,
    SymbolProjectionState,
    utcnow,
)

from .test_current_decisions import _run


def seed_report(
    harness, occurrence_id, *, current=True, status="PARTIAL", function="fixture::crash"
):
    with harness.app.state.database.sessions.begin() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        run = _run(occurrence_id, new_id("run"))
        run.status = status
        run.started_at = run.finished_at = utcnow()
        run.result_object_key = (
            "metadata-fixtures/" + run.id if status in {"PARTIAL", "COMPLETE"} else None
        )
        session.add(run)
        session.flush()
        if current:
            occurrence.current_run_id = run.id
            session.add(
                SymbolProjectionState(
                    occurrence_id=occurrence.id,
                    workspace_id=occurrence.workspace_id,
                    analysis_run_id=run.id,
                    identity_digest=__import__("hashlib").sha256(b"[]").hexdigest(),
                    missing_count=0,
                    source="promotion",
                )
            )
            session.add(
                AnalysisSummary(
                    analysis_run_id=run.id,
                    occurrence_id=occurrence_id,
                    crash_type="crash",
                    top_function=function,
                    exception_code="0xc0000005",
                    exception_name="EXCEPTION_ACCESS_VIOLATION",
                    fault_module="fixture.exe",
                    symbol_coverage=0.5,
                    unwind_reliability=0.5,
                    artifact_completeness=0.5,
                    crashing_frames=[],
                )
            )
        if run.result_object_key:
            harness.app.state.store.put_bytes(
                run.result_object_key, b"metadata fixture", "application/octet-stream"
            )
        return run.id
