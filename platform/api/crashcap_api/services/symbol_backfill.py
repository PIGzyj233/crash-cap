from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..canonical_semantics import CanonicalSemanticError, validate_canonical_semantics
from ..contracts import validate_contract
from ..errors import ApiError
from ..models import (
    CURRENT_ELIGIBLE_STATUSES,
    AnalysisRun,
    Occurrence,
    SymbolProjectionCheckpoint,
    SymbolProjectionGap,
    utcnow,
)
from ..storage import ObjectNotFoundError, ObjectStore
from .symbol_projection import (
    projection_invariant_counts,
    replace_current_symbol_projection,
    update_legacy_symbol_health,
)

CHECKPOINT_NAME = "current-analysis-v1"
MAX_CANONICAL_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class _Candidate:
    occurrence_id: str
    workspace_id: str
    current_run_id: str
    run_occurrence_id: str | None
    status: str | None
    result_object_key: str | None
    analysis_context: dict[str, Any] | None


@dataclass(frozen=True)
class _Prepared:
    candidate: _Candidate
    canonical: dict[str, Any] | None
    gap_reason: str | None
    gap_detail: str | None


def backfill_symbol_projection(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    schema_root: Any,
    *,
    after: str | None = None,
    limit: int = 100,
    apply: bool = False,
    retry_gaps: bool = False,
) -> dict[str, Any]:
    """Resume Current Analysis projection without using raw Dumps or OperationLog as authority."""

    batch_limit = max(1, min(limit, 10_000))
    with sessions() as session:
        checkpoint = session.get(SymbolProjectionCheckpoint, CHECKPOINT_NAME)
        cursor = (
            after if after is not None else checkpoint.cursor_occurrence_id if checkpoint else None
        )
        candidates, has_more = _load_candidates(
            session, cursor=cursor, limit=batch_limit, retry_gaps=retry_gaps
        )

    cases: list[dict[str, Any]] = []
    scanned = 0
    projected = 0
    gaps = 0
    next_cursor = cursor
    for candidate in candidates:
        scanned += 1
        if not retry_gaps:
            next_cursor = candidate.occurrence_id
        prepared = _prepare_candidate(candidate, store, schema_root)
        if not apply:
            outcome = "gap" if prepared.gap_reason else "would_project"
            gaps += int(prepared.gap_reason is not None)
            projected += int(prepared.gap_reason is None)
            cases.append(_case(prepared, outcome))
            continue

        outcome, reason, detail = _apply_prepared(
            sessions,
            prepared,
            cursor=next_cursor,
            retry_gaps=retry_gaps,
            completed=not has_more and candidate is candidates[-1],
        )
        projected += int(outcome == "projected")
        gaps += int(outcome == "gap")
        cases.append(_case(prepared, outcome, reason=reason, detail=detail))

    if apply and not candidates and not retry_gaps:
        with sessions() as session:
            checkpoint = _checkpoint(session)
            checkpoint.completed_at = utcnow()
            checkpoint.updated_at = utcnow()
            session.commit()

    with sessions() as session:
        invariants = projection_invariant_counts(session)
        unresolved_gaps = int(
            session.scalar(
                select(func.count())
                .select_from(SymbolProjectionGap)
                .where(SymbolProjectionGap.resolved_at.is_(None))
            )
            or 0
        )
        checkpoint = session.get(SymbolProjectionCheckpoint, CHECKPOINT_NAME)
        durable_checkpoint = (
            {
                "cursor_occurrence_id": checkpoint.cursor_occurrence_id,
                "scanned_count": checkpoint.scanned_count,
                "projected_count": checkpoint.projected_count,
                "gap_count": checkpoint.gap_count,
                "completed_at": checkpoint.completed_at.isoformat()
                if checkpoint.completed_at
                else None,
            }
            if checkpoint
            else None
        )

    return {
        "schema_version": "symbol-projection-backfill-v1",
        "mode": "apply" if apply else "dry-run",
        "retry_gaps": retry_gaps,
        "input_cursor": cursor,
        "next_cursor": next_cursor,
        "limit": batch_limit,
        "has_more": has_more,
        "scanned": scanned,
        "projected": projected,
        "gaps": gaps,
        "backfill_remaining": invariants["backfill_remaining"],
        "unresolved_gaps": unresolved_gaps,
        "durable_checkpoint": durable_checkpoint,
        "cases": cases,
    }


def _load_candidates(
    session: Session,
    *,
    cursor: str | None,
    limit: int,
    retry_gaps: bool,
) -> tuple[list[_Candidate], bool]:
    query = (
        select(
            Occurrence.id,
            Occurrence.workspace_id,
            Occurrence.current_run_id,
            AnalysisRun.occurrence_id,
            AnalysisRun.status,
            AnalysisRun.result_object_key,
            AnalysisRun.analysis_context,
        )
        .outerjoin(AnalysisRun, AnalysisRun.id == Occurrence.current_run_id)
        .where(Occurrence.current_run_id.is_not(None))
        .order_by(Occurrence.id)
    )
    if retry_gaps:
        query = query.join(
            SymbolProjectionGap,
            SymbolProjectionGap.occurrence_id == Occurrence.id,
        ).where(SymbolProjectionGap.resolved_at.is_(None))
    elif cursor:
        query = query.where(Occurrence.id > cursor)
    rows = session.execute(query.limit(limit + 1)).all()
    candidates = [
        _Candidate(
            occurrence_id=str(row[0]),
            workspace_id=str(row[1]),
            current_run_id=str(row[2]),
            run_occurrence_id=str(row[3]) if row[3] is not None else None,
            status=str(row[4]) if row[4] is not None else None,
            result_object_key=str(row[5]) if row[5] is not None else None,
            analysis_context=cast(dict[str, Any] | None, row[6]),
        )
        for row in rows[:limit]
    ]
    return candidates, len(rows) > limit


def _prepare_candidate(candidate: _Candidate, store: ObjectStore, schema_root: Any) -> _Prepared:
    if candidate.run_occurrence_id is None:
        return _gap(candidate, "current_run_missing", "Current Analysis Run row is missing")
    if candidate.run_occurrence_id != candidate.occurrence_id:
        return _gap(
            candidate, "current_run_mismatch", "Current Analysis belongs to another Occurrence"
        )
    if candidate.status not in CURRENT_ELIGIBLE_STATUSES:
        return _gap(
            candidate, "current_run_ineligible", f"Current Analysis status is {candidate.status}"
        )
    if not candidate.result_object_key:
        return _gap(candidate, "result_object_key_missing", "Current Analysis has no Canonical key")
    if candidate.analysis_context is None:
        return _gap(candidate, "analysis_context_missing", "Current Analysis has no frozen context")
    try:
        payload = _read_bounded(store, candidate.result_object_key)
    except ObjectNotFoundError:
        return _gap(candidate, "object_missing", "Canonical object does not exist")
    except ValueError as error:
        return _gap(candidate, "object_too_large", str(error))
    except Exception as error:
        return _gap(candidate, "object_read_failed", type(error).__name__)
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return _gap(candidate, "object_corrupt", f"{type(error).__name__}: {error}")
    if not isinstance(value, dict):
        return _gap(candidate, "schema_invalid", "Canonical root is not an object")
    canonical = cast(dict[str, Any], value)
    try:
        validate_contract(canonical, schema_root / "analysis-result-v1.schema.json", "Canonical")
        validate_canonical_semantics(canonical, candidate.analysis_context)
    except ApiError as error:
        return _gap(candidate, "schema_invalid", str(error))
    except CanonicalSemanticError as error:
        return _gap(candidate, "semantic_invalid", str(error))
    return _Prepared(candidate, canonical, None, None)


def _read_bounded(store: ObjectStore, key: str) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in store.stream(key):
        size += len(chunk)
        if size > MAX_CANONICAL_BYTES:
            raise ValueError(f"Canonical object exceeds {MAX_CANONICAL_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _apply_prepared(
    sessions: sessionmaker[Session],
    prepared: _Prepared,
    *,
    cursor: str | None,
    retry_gaps: bool,
    completed: bool,
) -> tuple[str, str | None, str | None]:
    candidate = prepared.candidate
    with sessions() as session:
        occurrence = session.scalar(
            select(Occurrence).where(Occurrence.id == candidate.occurrence_id).with_for_update()
        )
        if occurrence is None:
            return "skipped", "occurrence_missing", "Occurrence disappeared before apply"
        reason = prepared.gap_reason
        detail = prepared.gap_detail
        if occurrence.current_run_id != candidate.current_run_id:
            reason = "pointer_changed"
            detail = (
                f"Current Analysis changed from {candidate.current_run_id} "
                f"to {occurrence.current_run_id}"
            )
        if reason is not None or prepared.canonical is None:
            _record_gap(
                session,
                occurrence,
                candidate.current_run_id,
                candidate.result_object_key,
                reason or "canonical_unavailable",
                detail,
            )
            if not retry_gaps:
                _advance_checkpoint(session, cursor, projected=False, completed=completed)
            session.commit()
            return "gap", reason, detail

        run = session.get(AnalysisRun, candidate.current_run_id)
        if run is None:
            reason = "current_run_missing"
            detail = "Current Analysis Run row is missing at apply"
            _record_gap(
                session,
                occurrence,
                candidate.current_run_id,
                candidate.result_object_key,
                reason,
                detail,
            )
            if not retry_gaps:
                _advance_checkpoint(session, cursor, projected=False, completed=completed)
            session.commit()
            return "gap", reason, detail

        update_legacy_symbol_health(session, occurrence, prepared.canonical)
        replace_current_symbol_projection(
            session,
            occurrence=occurrence,
            run=run,
            canonical=prepared.canonical,
            source="backfill",
        )
        gap = session.get(SymbolProjectionGap, occurrence.id)
        if gap is not None:
            gap.resolved_at = utcnow()
            gap.last_seen_at = utcnow()
        if not retry_gaps:
            _advance_checkpoint(session, cursor, projected=True, completed=completed)
        session.commit()
        return "projected", None, None


def _checkpoint(session: Session) -> SymbolProjectionCheckpoint:
    checkpoint = session.get(SymbolProjectionCheckpoint, CHECKPOINT_NAME)
    if checkpoint is None:
        checkpoint = SymbolProjectionCheckpoint(name=CHECKPOINT_NAME)
        session.add(checkpoint)
        session.flush()
    return checkpoint


def _advance_checkpoint(
    session: Session, cursor: str | None, *, projected: bool, completed: bool
) -> None:
    checkpoint = _checkpoint(session)
    checkpoint.cursor_occurrence_id = cursor
    checkpoint.scanned_count += 1
    checkpoint.projected_count += int(projected)
    checkpoint.gap_count += int(not projected)
    checkpoint.updated_at = utcnow()
    checkpoint.completed_at = utcnow() if completed else None


def _record_gap(
    session: Session,
    occurrence: Occurrence,
    run_id: str | None,
    result_object_key: str | None,
    reason: str,
    detail: str | None,
) -> None:
    now = utcnow()
    gap = session.get(SymbolProjectionGap, occurrence.id)
    if gap is None:
        gap = SymbolProjectionGap(
            occurrence_id=occurrence.id,
            workspace_id=occurrence.workspace_id,
            analysis_run_id=run_id,
            result_object_key=result_object_key,
            reason=reason,
            detail=(detail or "")[:2000] or None,
            attempt_count=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(gap)
        return
    gap.workspace_id = occurrence.workspace_id
    gap.analysis_run_id = run_id
    gap.result_object_key = result_object_key
    gap.reason = reason
    gap.detail = (detail or "")[:2000] or None
    gap.attempt_count += 1
    gap.last_seen_at = now
    gap.resolved_at = None


def _gap(candidate: _Candidate, reason: str, detail: str) -> _Prepared:
    return _Prepared(candidate, None, reason, detail[:2000])


def _case(
    prepared: _Prepared,
    outcome: str,
    *,
    reason: str | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    candidate = prepared.candidate
    return {
        "occurrence_id": candidate.occurrence_id,
        "workspace_id": candidate.workspace_id,
        "current_run_id": candidate.current_run_id,
        "result_object_key": candidate.result_object_key,
        "outcome": outcome,
        "gap_reason": reason or prepared.gap_reason,
        "gap_detail": detail or prepared.gap_detail,
    }
