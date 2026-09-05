"""Persistent fair capacity control for automatic frozen analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, literal, select, text
from sqlalchemy.orm import Session

from ..analysis_states import TERMINAL_STATES
from ..config import Settings
from ..ids import new_ulid
from ..models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    AnalysisSchedulerState,
)
from .analysis_demands import require


@dataclass(frozen=True)
class ExecutionSlotClaim:
    demand_id: str
    workspace_id: str
    claim_token: str
    owner_id: str
    lease_until: datetime


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scheduler_state(session: Session, now: datetime) -> AnalysisSchedulerState:
    # The migration seeds this row. create_schema test databases need the lazy path.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "automatic-analysis-scheduler-v1"},
        )
    state = session.scalar(
        select(AnalysisSchedulerState)
        .where(AnalysisSchedulerState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state is None:
        state = AnalysisSchedulerState(id=1, updated_at=now)
        session.add(state)
        session.flush()
    return state


def _reconcile_slots(session: Session, now: datetime) -> list[AnalysisExecutionSlot]:
    slots = list(
        session.scalars(
            select(AnalysisExecutionSlot)
            .order_by(AnalysisExecutionSlot.created_at, AnalysisExecutionSlot.demand_id)
            .with_for_update()
        )
    )
    active: list[AnalysisExecutionSlot] = []
    for slot in slots:
        if slot.state == "planning":
            if slot.lease_until is None or _utc(slot.lease_until) <= now:
                session.delete(slot)
            else:
                active.append(slot)
            continue
        run = session.get(AnalysisRun, slot.run_id) if slot.run_id is not None else None
        if run is None or run.status in TERMINAL_STATES:
            session.delete(slot)
        else:
            active.append(slot)
    session.flush()
    return active


def claim_execution_slots(
    session: Session,
    settings: Settings,
    *,
    owner_id: str,
    now: datetime,
) -> tuple[ExecutionSlotClaim, ...]:
    """Claim a fair bounded release page without deleting overflow work."""

    require(settings.automatic_analysis_enabled, "AUTOMATIC_ANALYSIS_DISABLED")
    if settings.automatic_analysis_paused:
        return ()
    now = _utc(now)
    state = _scheduler_state(session, now)
    active = _reconcile_slots(session, now)
    global_limit = min(
        settings.automatic_analysis_global_limit,
        settings.automatic_analysis_capacity,
    )
    available = min(
        settings.automatic_analysis_release_limit,
        max(0, global_limit - len(active)),
    )
    if available == 0:
        return ()

    occupied: dict[str, int] = defaultdict(int)
    for slot in active:
        occupied[slot.workspace_id] += 1

    priority = case(
        (AnalysisDemand.reason.in_(("new_dump", "manual")), 0),
        else_=1,
    )
    ranked = (
        select(
            AnalysisDemand.id.label("demand_id"),
            AnalysisDemand.workspace_id.label("workspace_id"),
            priority.label("priority"),
            AnalysisDemand.updated_at.label("updated_at"),
            func.row_number()
            .over(
                partition_by=AnalysisDemand.workspace_id,
                order_by=(priority, AnalysisDemand.updated_at, AnalysisDemand.id),
            )
            .label("workspace_rank"),
        )
        .where(
            AnalysisDemand.state.in_(("preparing", "coalescing", "retry_wait")),
            AnalysisDemand.not_before.is_not(None),
            AnalysisDemand.not_before <= now,
            ~select(AnalysisExecutionSlot.demand_id)
            .where(AnalysisExecutionSlot.demand_id == AnalysisDemand.id)
            .exists(),
        )
        .subquery()
    )
    workspace_rotation = (
        case((ranked.c.workspace_id > state.last_workspace_id, 0), else_=1)
        if state.last_workspace_id is not None
        else literal(0)
    )
    rows = list(
        session.execute(
            select(
                ranked.c.demand_id,
                ranked.c.workspace_id,
                ranked.c.workspace_rank,
            )
            .where(ranked.c.workspace_rank <= settings.automatic_analysis_workspace_limit)
            .order_by(
                ranked.c.workspace_rank,
                workspace_rotation,
                ranked.c.workspace_id,
                ranked.c.priority,
                ranked.c.updated_at,
                ranked.c.demand_id,
            )
            .limit(settings.automatic_analysis_enumeration_limit)
        )
    )
    by_workspace: dict[str, list[str]] = defaultdict(list)
    for demand_id, workspace_id, _rank in rows:
        if occupied[str(workspace_id)] < settings.automatic_analysis_workspace_limit:
            by_workspace[str(workspace_id)].append(str(demand_id))
    workspaces = sorted(by_workspace)
    if state.last_workspace_id is not None:
        workspaces = [w for w in workspaces if w > state.last_workspace_id] + [
            w for w in workspaces if w <= state.last_workspace_id
        ]

    claims: list[ExecutionSlotClaim] = []
    while workspaces and len(claims) < available:
        remaining = []
        for workspace_id in workspaces:
            if len(claims) >= available:
                break
            if (
                occupied[workspace_id] >= settings.automatic_analysis_workspace_limit
                or not by_workspace[workspace_id]
            ):
                continue
            demand_id = by_workspace[workspace_id].pop(0)
            token = "slot_" + new_ulid()
            lease_until = now + timedelta(
                seconds=settings.automatic_analysis_planning_lease_seconds
            )
            session.add(
                AnalysisExecutionSlot(
                    demand_id=demand_id,
                    workspace_id=workspace_id,
                    claim_token=token,
                    owner_id=owner_id,
                    state="planning",
                    lease_until=lease_until,
                    created_at=now,
                    updated_at=now,
                )
            )
            occupied[workspace_id] += 1
            state.last_workspace_id = workspace_id
            claims.append(ExecutionSlotClaim(demand_id, workspace_id, token, owner_id, lease_until))
            if (
                by_workspace[workspace_id]
                and occupied[workspace_id] < settings.automatic_analysis_workspace_limit
            ):
                remaining.append(workspace_id)
        workspaces = remaining
    state.updated_at = now
    session.flush()
    return tuple(claims)


def bind_execution_slot(
    session: Session,
    claim: ExecutionSlotClaim,
    run_id: str,
    *,
    now: datetime,
) -> None:
    slot = session.scalar(
        select(AnalysisExecutionSlot)
        .where(AnalysisExecutionSlot.demand_id == claim.demand_id)
        .with_for_update()
    )
    require(
        slot is not None
        and slot.state == "planning"
        and slot.claim_token == claim.claim_token
        and slot.owner_id == claim.owner_id
        and slot.lease_until is not None
        and _utc(slot.lease_until) > _utc(now),
        "ANALYSIS_SLOT_LOST",
    )
    assert slot is not None
    slot.state = "executing"
    slot.run_id = run_id
    slot.lease_until = None
    slot.updated_at = _utc(now)
    session.flush()


def heartbeat_planning_slot(
    session: Session,
    settings: Settings,
    claim: ExecutionSlotClaim,
    *,
    now: datetime,
) -> bool:
    current = _utc(now)
    slot = session.scalar(
        select(AnalysisExecutionSlot)
        .where(AnalysisExecutionSlot.demand_id == claim.demand_id)
        .with_for_update()
    )
    if (
        slot is None
        or slot.state != "planning"
        or slot.claim_token != claim.claim_token
        or slot.owner_id != claim.owner_id
        or slot.lease_until is None
        or _utc(slot.lease_until) <= current
    ):
        return False
    slot.lease_until = current + timedelta(
        seconds=settings.automatic_analysis_planning_lease_seconds
    )
    slot.updated_at = current
    session.flush()
    return True


def release_planning_slot(session: Session, claim: ExecutionSlotClaim) -> bool:
    result = session.scalar(
        delete(AnalysisExecutionSlot)
        .where(
            AnalysisExecutionSlot.demand_id == claim.demand_id,
            AnalysisExecutionSlot.claim_token == claim.claim_token,
            AnalysisExecutionSlot.owner_id == claim.owner_id,
            AnalysisExecutionSlot.state == "planning",
        )
        .returning(AnalysisExecutionSlot.demand_id)
    )
    return result is not None


def release_execution_slot_for_run(session: Session, run_id: str) -> bool:
    result = session.scalar(
        delete(AnalysisExecutionSlot)
        .where(
            AnalysisExecutionSlot.run_id == run_id,
            AnalysisExecutionSlot.state == "executing",
        )
        .returning(AnalysisExecutionSlot.demand_id)
    )
    return result is not None
