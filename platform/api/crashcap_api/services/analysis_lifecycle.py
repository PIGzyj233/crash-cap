from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..analysis_states import (
    ANALYSIS_STATES,
    ANALYSIS_TRANSITIONS,
    CURRENT_ELIGIBLE_STATES,
    TERMINAL_STATES,
    failure_state,
)
from ..errors import ApiError
from ..metrics import (
    ANALYSIS_TRANSITIONS as ANALYSIS_TRANSITION_METRIC,
)
from ..metrics import CURRENT_ANALYSIS_PROMOTIONS
from ..models import AnalysisRun, Occurrence, utcnow

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PromotionDecision:
    promoted: bool
    reason: str
    previous_run_id: str | None


def transition_analysis(run: AnalysisRun, target: str) -> None:
    """Apply the only production Analysis Run state transition authority."""

    if run.status not in ANALYSIS_STATES or target not in ANALYSIS_STATES:
        ANALYSIS_TRANSITION_METRIC.labels(
            run.status if run.status in ANALYSIS_STATES else "unknown",
            target if target in ANALYSIS_STATES else "unknown",
            "rejected_unknown",
        ).inc()
        raise ValueError("unknown analysis state")
    if target not in ANALYSIS_TRANSITIONS[run.status]:
        ANALYSIS_TRANSITION_METRIC.labels(run.status, target, "rejected_illegal").inc()
        raise ApiError(
            "CONFLICT",
            "illegal analysis state transition",
            status_code=409,
            details={"from": run.status, "to": target},
        )
    previous = run.status
    run.status = target
    ANALYSIS_TRANSITION_METRIC.labels(previous, target, "accepted").inc()
    LOGGER.debug(
        "analysis lifecycle transition",
        extra={
            "domain_identity": run.id,
            "from_status": previous,
            "to_status": target,
            "outcome": "accepted",
            "reason": "state_machine",
        },
    )
    if target == "ANALYZING" and run.started_at is None:
        run.started_at = utcnow()
    if target in TERMINAL_STATES and run.finished_at is None:
        run.finished_at = utcnow()


def fail_analysis(run: AnalysisRun, error_code: str) -> str | None:
    """Move an active Run to its classified terminal state; never rewrite a terminal Run."""

    if run.status in TERMINAL_STATES:
        return None
    target = failure_state(error_code)
    if run.status == "UPLOADED":
        transition_analysis(run, "VALIDATING")
    transition_analysis(run, target)
    return target


def promote_current_analysis(
    session: Session,
    occurrence: Occurrence,
    candidate: AnalysisRun,
) -> PromotionDecision:
    """Monotonically promote an eligible Run while the caller holds the Occurrence lock."""

    if candidate.occurrence_id != occurrence.id:
        raise ValueError("candidate Analysis Run does not belong to the Occurrence")
    if candidate.status not in CURRENT_ELIGIBLE_STATES:
        return _promotion(False, "candidate_not_eligible", occurrence.current_run_id)

    previous_id = occurrence.current_run_id
    if previous_id is None:
        occurrence.current_run_id = candidate.id
        return _promotion(True, "first_success", None)
    if previous_id == candidate.id:
        return _promotion(False, "already_current", previous_id)

    current = session.get(AnalysisRun, previous_id)
    if current is None or current.occurrence_id != occurrence.id:
        raise RuntimeError("Occurrence current_run_id violates Current Analysis integrity")
    if current.status not in CURRENT_ELIGIBLE_STATES:
        raise RuntimeError("Occurrence points to a non-eligible Current Analysis")
    if candidate.id <= current.id:
        return _promotion(False, "older_than_current", previous_id)

    occurrence.current_run_id = candidate.id
    return _promotion(True, "newer_success", previous_id)


def _promotion(promoted: bool, reason: str, previous_run_id: str | None) -> PromotionDecision:
    CURRENT_ANALYSIS_PROMOTIONS.labels("accepted" if promoted else "skipped", reason).inc()
    return PromotionDecision(promoted, reason, previous_run_id)
