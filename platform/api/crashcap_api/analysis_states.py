from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

ANALYSIS_STATES = frozenset(
    {
        "UPLOADED",
        "VALIDATING",
        "INSPECTED",
        "MATCHING_SYMBOLS",
        "WAITING_FOR_SYMBOLS",
        "SYMBOLS_READY",
        "QUEUED",
        "ANALYZING",
        "NORMALIZING",
        "GROUPING",
        "COMPLETE",
        "PARTIAL",
        "FAILED",
        "REJECTED",
        "CANCELLED",
        "TIMEOUT",
        "OOM",
    }
)
CURRENT_ELIGIBLE_STATES = frozenset({"COMPLETE", "PARTIAL"})
FAILURE_STATES = frozenset({"FAILED", "REJECTED", "CANCELLED", "TIMEOUT", "OOM"})
TERMINAL_STATES = CURRENT_ELIGIBLE_STATES | FAILURE_STATES
ACTIVE_STATES = ANALYSIS_STATES - TERMINAL_STATES

_TRANSITIONS: dict[str, frozenset[str]] = {
    "UPLOADED": frozenset({"VALIDATING", "CANCELLED"}),
    "VALIDATING": frozenset(
        {"INSPECTED", "REJECTED", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}
    ),
    "INSPECTED": frozenset(
        {"MATCHING_SYMBOLS", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}
    ),
    "MATCHING_SYMBOLS": frozenset(
        {"SYMBOLS_READY", "WAITING_FOR_SYMBOLS", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}
    ),
    "WAITING_FOR_SYMBOLS": frozenset(
        {"MATCHING_SYMBOLS", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}
    ),
    "SYMBOLS_READY": frozenset({"QUEUED", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}),
    "QUEUED": frozenset({"ANALYZING", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}),
    "ANALYZING": frozenset({"NORMALIZING", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}),
    "NORMALIZING": frozenset({"GROUPING", "FAILED", "TIMEOUT", "OOM", "CANCELLED"}),
    "GROUPING": frozenset({"COMPLETE", "PARTIAL", "FAILED", "CANCELLED"}),
    **{state: frozenset() for state in TERMINAL_STATES},
}
ANALYSIS_TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(_TRANSITIONS)


def failure_state(error_code: str) -> str:
    if error_code == "TIMEOUT":
        return "TIMEOUT"
    if error_code == "OOM":
        return "OOM"
    if error_code in {"UNSUPPORTED_DUMP", "CORRUPT_DUMP"}:
        return "REJECTED"
    return "FAILED"


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_current_eligible(state: str) -> bool:
    return state in CURRENT_ELIGIBLE_STATES


def retry_is_same_run(state: str) -> bool:
    """Delivery retry is valid only while the existing Run is non-terminal."""

    return state in ACTIVE_STATES


def reprocess_requires_new_run(state: str) -> bool:
    """A terminal Run is immutable; user reprocess always creates another Run."""

    return state in TERMINAL_STATES
