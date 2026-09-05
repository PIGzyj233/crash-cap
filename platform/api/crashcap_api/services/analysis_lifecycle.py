from __future__ import annotations

import logging

from ..analysis_states import (
    ANALYSIS_STATES,
    ANALYSIS_TRANSITIONS,
    TERMINAL_STATES,
    failure_state,
)
from ..errors import ApiError
from ..metrics import (
    ANALYSIS_TRANSITIONS as ANALYSIS_TRANSITION_METRIC,
)
from ..models import AnalysisRun, utcnow

LOGGER = logging.getLogger(__name__)


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
