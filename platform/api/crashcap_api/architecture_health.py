from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    CURRENT_ELIGIBLE_STATUSES,
    AnalysisRun,
    GroupMembership,
    MissingSymbol,
    Occurrence,
    SymbolProjectionGap,
    Workspace,
)
from .services.symbol_projection import (
    legacy_missing_occurrences,
    projection_invariant_counts,
    symbol_identity_key,
)
from .storage import ObjectNotFoundError, ObjectStore


def collect_architecture_health(
    session: Session, store: ObjectStore | None = None
) -> dict[str, Any]:
    """Return a read-only pre-migration health report for the architecture gates."""

    current_violations: list[dict[str, Any]] = []
    current_rows = session.execute(
        select(
            Occurrence.id,
            Occurrence.current_run_id,
            AnalysisRun.occurrence_id,
            AnalysisRun.status,
            AnalysisRun.result_object_key,
        )
        .outerjoin(AnalysisRun, AnalysisRun.id == Occurrence.current_run_id)
        .where(Occurrence.current_run_id.is_not(None))
        .order_by(Occurrence.id)
    ).all()
    for occurrence_id, run_id, run_occurrence_id, status, result_object_key in current_rows:
        reasons: list[str] = []
        if run_occurrence_id is None:
            reasons.append("run_missing")
        elif run_occurrence_id != occurrence_id:
            reasons.append("run_belongs_to_other_occurrence")
        if status not in CURRENT_ELIGIBLE_STATUSES:
            reasons.append("run_not_current_eligible")
        if not result_object_key:
            reasons.append("result_object_key_missing")
        if reasons:
            current_violations.append(
                {"occurrence_id": occurrence_id, "run_id": run_id, "reasons": reasons}
            )

    membership_violations = [
        {
            "occurrence_id": occurrence_id,
            "membership_run_id": membership_run_id,
            "current_run_id": current_run_id,
        }
        for occurrence_id, membership_run_id, current_run_id in session.execute(
            select(
                GroupMembership.occurrence_id,
                GroupMembership.analysis_run_id,
                Occurrence.current_run_id,
            )
            .join(Occurrence, Occurrence.id == GroupMembership.occurrence_id)
            .where(GroupMembership.analysis_run_id != Occurrence.current_run_id)
            .order_by(GroupMembership.occurrence_id)
        ).all()
    ]

    result_keys = list(
        session.scalars(
            select(AnalysisRun.result_object_key).where(AnalysisRun.result_object_key.is_not(None))
        )
    )
    duplicate_result_keys = [
        {"result_object_key": key, "run_count": count}
        for key, count in sorted(Counter(result_keys).items())
        if count > 1
    ]

    missing_rows = list(
        session.execute(
            select(MissingSymbol.__table__).order_by(MissingSymbol.workspace_id)
        ).mappings()
    )
    replay_by_workspace = {
        workspace_id: legacy_missing_occurrences(session, workspace_id)
        for workspace_id in session.scalars(select(Workspace.id).order_by(Workspace.id))
    }
    missing_count_mismatches: list[dict[str, Any]] = []
    double_null_identities: list[dict[str, Any]] = []
    for row in missing_rows:
        key = symbol_identity_key(dict(row))
        replay_count = len(replay_by_workspace.get(row["workspace_id"], {}).get(key, set()))
        stored_count = int(row["affected_occurrence_count"])
        if stored_count != replay_count:
            missing_count_mismatches.append(
                {
                    "workspace_id": row["workspace_id"],
                    "missing_symbol_key": key,
                    "stored_count": stored_count,
                    "audit_replay_count": replay_count,
                }
            )
        if row["debug_id"] is None and row["code_id"] is None:
            double_null_identities.append(
                {
                    "workspace_id": row["workspace_id"],
                    "missing_symbol_key": key,
                    "debug_file": row["debug_file"],
                    "code_file": row["code_file"],
                }
            )

    missing_objects: list[dict[str, str]] = []
    if store is not None:
        for occurrence_id, run_id, _run_occurrence_id, _status, result_object_key in current_rows:
            if not result_object_key:
                continue
            try:
                store.head(result_object_key)
            except ObjectNotFoundError:
                missing_objects.append(
                    {
                        "occurrence_id": occurrence_id,
                        "run_id": run_id,
                        "result_object_key": result_object_key,
                    }
                )

    violations = (
        len(current_violations)
        + len(membership_violations)
        + len(duplicate_result_keys)
        + len(missing_count_mismatches)
        + len(missing_objects)
    )
    symbol_projection = projection_invariant_counts(session)
    symbol_projection["unresolved_gaps"] = len(
        list(
            session.scalars(
                select(SymbolProjectionGap.occurrence_id).where(
                    SymbolProjectionGap.resolved_at.is_(None)
                )
            )
        )
    )
    status = "FAIL" if violations else "PASS" if store is not None else "PARTIAL"
    return {
        "schema_version": "architecture-health-v1.0",
        "status": status,
        "object_store_checked": store is not None,
        "counts": {
            "current_analysis_violations": len(current_violations),
            "group_membership_violations": len(membership_violations),
            "duplicate_result_object_keys": len(duplicate_result_keys),
            "missing_symbol_count_mismatches": len(missing_count_mismatches),
            "missing_canonical_objects": len(missing_objects),
            "double_null_missing_symbol_identities": len(double_null_identities),
        },
        "current_analysis_violations": current_violations,
        "group_membership_violations": membership_violations,
        "duplicate_result_object_keys": duplicate_result_keys,
        "missing_symbol_count_mismatches": missing_count_mismatches,
        "missing_canonical_objects": missing_objects,
        "double_null_missing_symbol_identities": double_null_identities,
        "symbol_projection": symbol_projection,
        "note": (
            "Double-null symbol identities are migration input, not automatic corruption. "
            "PARTIAL means database checks passed but object existence was not checked."
        ),
    }
