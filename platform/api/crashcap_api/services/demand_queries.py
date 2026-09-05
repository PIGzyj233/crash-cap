"""Read-only browser projection of a Demand and its exact current attempt."""

from datetime import UTC
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import AnalysisDemand, AnalysisRun, CatalogPair, CurrentDecision, Occurrence


def demand_status(
    session: Session, *, workspace_id: str, occurrence_id: str
) -> dict[str, Any] | None:
    # Select scalar columns in one statement: a concurrent attempt transition
    # must not pair a new Demand with a Run from a separate query/snapshot.
    statement = (
        select(
            Occurrence.id.label("occurrence_id"),
            AnalysisDemand.id.label("demand_id"),
            AnalysisDemand.state,
            AnalysisDemand.generation,
            AnalysisDemand.retry_attempt,
            AnalysisDemand.change_sequence,
            AnalysisDemand.reason,
            AnalysisDemand.not_before,
            AnalysisRun.id.label("run_id"),
            Occurrence.current_run_id,
            CurrentDecision.candidate_evidence.label("_current_evidence"),
        )
        .select_from(Occurrence)
        .outerjoin(AnalysisDemand, AnalysisDemand.occurrence_id == Occurrence.id)
        .outerjoin(CurrentDecision, CurrentDecision.candidate_run_id == Occurrence.current_run_id)
        .outerjoin(
            AnalysisRun,
            and_(
                AnalysisRun.demand_id == AnalysisDemand.id,
                AnalysisRun.demand_generation == AnalysisDemand.generation,
                AnalysisRun.retry_attempt == AnalysisDemand.retry_attempt,
            ),
        )
        .where(Occurrence.id == occurrence_id, Occurrence.workspace_id == workspace_id)
    )
    with session.no_autoflush:
        row = session.execute(statement).mappings().one_or_none()
    if row is None:
        raise ApiError("OCCURRENCE_NOT_FOUND", "Occurrence not found", status_code=404)
    if row["demand_id"] is None:
        return None
    result = dict(row)
    evidence = result.pop("_current_evidence")
    result["withdrawn_basis_pair_ids"] = None
    if isinstance(evidence, dict) and evidence.get("pair_evidence_complete") is True:
        modules = evidence.get("modules")
        if isinstance(modules, list) and all(isinstance(module, dict) for module in modules):
            pair_ids = {
                module["pair_id"] for module in modules if isinstance(module.get("pair_id"), str)
            }
            result["withdrawn_basis_pair_ids"] = (
                sorted(
                    session.scalars(
                        select(CatalogPair.id).where(
                            CatalogPair.id.in_(pair_ids), CatalogPair.state == "withdrawn"
                        )
                    )
                )
                if pair_ids
                else []
            )
    due = result["not_before"]
    if due is not None:
        due = due.replace(tzinfo=UTC) if due.tzinfo is None else due.astimezone(UTC)
        result["not_before"] = due.isoformat().replace("+00:00", "Z")
    return result
