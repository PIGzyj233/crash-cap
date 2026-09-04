"""Shared projections for a Current change inside its owning transaction."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ids import new_id
from ..models import (
    AnalysisRun,
    AnalysisSummary,
    CrashGroup,
    GroupMembership,
    GroupMembershipHistory,
    Occurrence,
    utcnow,
)
from .symbol_projection import SymbolProjectionMode, update_symbol_health_for_promotion


def update_current_projections(
    session: Session,
    occurrence: Occurrence,
    run: AnalysisRun,
    canonical: dict[str, Any],
    *,
    symbol_projection_mode: SymbolProjectionMode,
) -> None:
    """Caller must hold the Occurrence lock; never commit independently."""
    if occurrence.current_run_id != run.id or run.occurrence_id != occurrence.id:
        raise ValueError("projections require the selected Current of this Occurrence")
    update_symbol_health_for_promotion(
        session,
        mode=symbol_projection_mode,
        occurrence=occurrence,
        run=run,
        canonical=canonical,
    )
    update_group_projection(session, occurrence, run, canonical)


def update_group_projection(
    session: Session, occurrence: Occurrence, run: AnalysisRun, canonical: dict[str, Any]
) -> None:
    exact = canonical["fingerprints"].get("exact")
    current = session.get(GroupMembership, occurrence.id)
    previous_group_id = current.group_id if current else None
    if not exact:
        if current is not None:
            session.delete(current)
            session.add(
                GroupMembershipHistory(
                    occurrence_id=occurrence.id,
                    previous_group_id=previous_group_id,
                    group_id=None,
                    analysis_run_id=run.id,
                    action="unclassify",
                    similarity=1.0,
                    grouping_evidence_json={
                        "decision": "unclassified",
                        "algorithm": canonical["fingerprints"]["algorithm"],
                        "grouping_version": run.grouping_version,
                    },
                )
            )
            session.flush()
            _refresh_group_count(session, previous_group_id)
        return
    group = session.scalar(
        select(CrashGroup).where(
            CrashGroup.workspace_id == occurrence.workspace_id,
            CrashGroup.group_type == "exact",
            CrashGroup.fingerprint == exact,
        )
    )
    summary = session.get(AnalysisSummary, run.id)
    if group is None:
        title = (
            " · ".join(
                part
                for part in (
                    summary.exception_name if summary else None,
                    summary.top_function if summary else None,
                )
                if part
            )
            or "Exact crash"
        )
        group = CrashGroup(
            id=new_id("grp"),
            workspace_id=occurrence.workspace_id,
            group_type="exact",
            fingerprint=exact,
            representative_run_id=run.id,
            title=title,
            status="open",
            first_seen=occurrence.occurred_at,
            last_seen=occurrence.occurred_at,
            occurrence_count=0,
            first_build_id=run.resolved_build_id,
            last_build_id=run.resolved_build_id,
        )
        session.add(group)
        session.flush()
    else:
        group.last_seen = max(group.last_seen, occurrence.occurred_at)
        group.last_build_id = run.resolved_build_id
    evidence = {
        "decision": "auto_exact",
        "algorithm": canonical["fingerprints"]["algorithm"],
        "grouping_version": run.grouping_version,
    }
    if current is None:
        current = GroupMembership(
            occurrence_id=occurrence.id,
            group_id=group.id,
            analysis_run_id=run.id,
            similarity=1.0,
            grouping_evidence_json=evidence,
        )
        session.add(current)
        action = "assign"
    else:
        action = "move" if current.group_id != group.id else "assign"
        current.group_id = group.id
        current.analysis_run_id = run.id
        current.grouping_evidence_json = evidence
        current.assigned_at = utcnow()
    session.add(
        GroupMembershipHistory(
            occurrence_id=occurrence.id,
            previous_group_id=previous_group_id,
            group_id=group.id,
            analysis_run_id=run.id,
            action=action,
            similarity=1.0,
            grouping_evidence_json=evidence,
        )
    )
    session.flush()
    _refresh_group_count(session, group.id)
    if previous_group_id and previous_group_id != group.id:
        _refresh_group_count(session, previous_group_id)


def _refresh_group_count(session: Session, group_id: str | None) -> None:
    if not group_id:
        return
    count = session.scalar(
        select(func.count())
        .select_from(GroupMembership)
        .where(
            GroupMembership.group_id == group_id,
        )
    )
    group = session.get(CrashGroup, group_id)
    if group:
        group.occurrence_count = int(count or 0)
