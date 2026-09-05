"""Read-only checks of Current and its durable projections."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AnalysisRun, GroupMembership, Occurrence
from .services.symbol_projection import projection_invariant_counts
from .storage import ObjectNotFoundError, ObjectStore


def collect_architecture_health(
    session: Session, store: ObjectStore | None = None
) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    for occurrence, run in session.execute(
        select(Occurrence, AnalysisRun)
        .outerjoin(AnalysisRun, AnalysisRun.id == Occurrence.current_run_id)
        .where(Occurrence.current_run_id.is_not(None))
    ):
        if (
            run is None
            or run.occurrence_id != occurrence.id
            or run.status not in {"COMPLETE", "PARTIAL"}
            or not run.result_object_key
            or run.schema_version != "2.0"
        ):
            problems.append({"occurrence_id": occurrence.id, "reason": "invalid_current"})
        elif store is not None:
            try:
                store.head(run.result_object_key)
            except ObjectNotFoundError:
                problems.append(
                    {"occurrence_id": occurrence.id, "reason": "current_object_missing"}
                )
    for _membership, occurrence in session.execute(
        select(GroupMembership, Occurrence)
        .join(Occurrence, Occurrence.id == GroupMembership.occurrence_id)
        .where(GroupMembership.analysis_run_id != Occurrence.current_run_id)
    ):
        problems.append({"occurrence_id": occurrence.id, "reason": "stale_group_membership"})
    projection = projection_invariant_counts(session)
    return {
        "status": "FAIL"
        if problems or any(projection.values())
        else "PASS"
        if store is not None
        else "PARTIAL",
        "problems": problems,
        "symbol_projection": projection,
    }
