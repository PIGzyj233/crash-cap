from __future__ import annotations

import hashlib
import json
import logging
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Any, Literal, cast

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..metrics import (
    SYMBOL_PROJECTION_WRITES,
)
from ..models import (
    AnalysisRun,
    MissingSymbol,
    MissingSymbolOccurrence,
    Occurrence,
    SymbolProjectionState,
    utcnow,
)
from .common import operation_log

LOGGER = logging.getLogger(__name__)

SymbolProjectionMode = Literal["projection-read"]
ProjectionSource = Literal["promotion"]
MISSING_REASONS = frozenset({"missing_pe", "missing_pdb", "pdb_mismatch", "pe_mismatch"})
_REASON_ORDER = {"pe_mismatch": 0, "pdb_mismatch": 1, "missing_pe": 2, "missing_pdb": 3}


class SymbolProjectionError(RuntimeError):
    """A Current Analysis could not be represented by the durable projection."""


@dataclass(frozen=True)
class ProjectionWriteResult:
    identity_keys: tuple[str, ...]
    identity_digest: str
    missing_count: int


def projection_mode(session: Session) -> SymbolProjectionMode:
    return "projection-read"


def normalize_symbol_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized or None


def normalize_symbol_filename(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip().replace("/", "\\")
    if not normalized:
        return ""
    return PureWindowsPath(normalized).name.casefold()


def symbol_identity(module: Mapping[str, Any]) -> dict[str, str | None]:
    code_id = normalize_symbol_identifier(module.get("code_id"))
    debug_id = normalize_symbol_identifier(module.get("debug_id"))
    if code_id is not None or debug_id is not None:
        return {"kind": "ids", "code_id": code_id, "debug_id": debug_id}
    return {
        "kind": "files",
        "code_file": normalize_symbol_filename(module.get("code_file")),
        "debug_file": normalize_symbol_filename(module.get("debug_file")),
    }


def symbol_identity_key(module: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        symbol_identity(module), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return f"ms_{hashlib.sha256(encoded).hexdigest()}"


def symbol_row_id(workspace_id: str, identity_key: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}\x00{identity_key}".encode()).hexdigest()
    return f"msr_{digest}"


def extract_missing_modules(canonical: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return one deterministic observation for every missing-symbol identity."""

    selected: dict[str, dict[str, Any]] = {}
    modules = canonical.get("modules")
    if not isinstance(modules, list):
        raise SymbolProjectionError("Canonical modules must be an array")
    for value in modules:
        if not isinstance(value, dict) or value.get("status") not in MISSING_REASONS:
            continue
        module = cast(dict[str, Any], value)
        key = symbol_identity_key(module)
        existing = selected.get(key)
        if existing is None or _observation_order(module) < _observation_order(existing):
            selected[key] = dict(module)
    return selected


def _observation_order(module: Mapping[str, Any]) -> tuple[object, ...]:
    reason = str(module.get("status"))
    return (
        _REASON_ORDER.get(reason, len(_REASON_ORDER)),
        normalize_symbol_filename(module.get("code_file")),
        normalize_symbol_filename(module.get("debug_file")),
        normalize_symbol_identifier(module.get("code_id")) or "",
        normalize_symbol_identifier(module.get("debug_id")) or "",
        json.dumps(dict(module), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
    )


def identity_set_digest(identity_keys: Iterable[str]) -> str:
    payload = json.dumps(sorted(identity_keys), separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def update_symbol_health_for_promotion(
    session: Session,
    *,
    mode: SymbolProjectionMode,
    occurrence: Occurrence,
    run: AnalysisRun,
    canonical: Mapping[str, Any],
) -> None:
    replace_current_symbol_projection(
        session, occurrence=occurrence, run=run, canonical=canonical, source="promotion"
    )
    SYMBOL_PROJECTION_WRITES.labels("projection-read", "written").inc()


def replace_current_symbol_projection(
    session: Session,
    *,
    occurrence: Occurrence,
    run: AnalysisRun,
    canonical: Mapping[str, Any],
    source: ProjectionSource,
) -> ProjectionWriteResult:
    """Idempotently replace one Occurrence's relation from its Current Analysis."""

    _assert_current_canonical(occurrence, run, canonical)
    current = extract_missing_modules(canonical)
    existing = {
        row.missing_symbol_id: row
        for row in session.scalars(
            select(MissingSymbolOccurrence)
            .where(MissingSymbolOccurrence.occurrence_id == occurrence.id)
            .with_for_update()
        )
    }
    row_ids: dict[str, str] = {}
    for key, module in current.items():
        row_ids[key] = _ensure_symbol_row(
            session, occurrence.workspace_id, key, module, occurrence.occurred_at
        )

    desired_ids = set(row_ids.values())
    stale_ids = set(existing) - desired_ids
    if stale_ids:
        session.execute(
            delete(MissingSymbolOccurrence).where(
                MissingSymbolOccurrence.occurrence_id == occurrence.id,
                MissingSymbolOccurrence.missing_symbol_id.in_(stale_ids),
            )
        )

    observed_at = _aware(occurrence.occurred_at)
    for key, module in current.items():
        values = {
            "missing_symbol_id": row_ids[key],
            "occurrence_id": occurrence.id,
            "workspace_id": occurrence.workspace_id,
            "analysis_run_id": run.id,
            "reason": str(module["status"]),
            "code_file": _optional_string(module.get("code_file")),
            "debug_file": _optional_string(module.get("debug_file")),
            "observed_at": observed_at,
        }
        _insert_ignore(
            session,
            MissingSymbolOccurrence.__table__,
            values,
            ("missing_symbol_id", "occurrence_id"),
        )
        session.execute(
            update(MissingSymbolOccurrence)
            .where(
                MissingSymbolOccurrence.missing_symbol_id == row_ids[key],
                MissingSymbolOccurrence.occurrence_id == occurrence.id,
            )
            .values(
                workspace_id=occurrence.workspace_id,
                analysis_run_id=run.id,
                reason=str(module["status"]),
                code_file=_optional_string(module.get("code_file")),
                debug_file=_optional_string(module.get("debug_file")),
                observed_at=observed_at,
            )
        )

    digest = identity_set_digest(current)
    state_values = {
        "occurrence_id": occurrence.id,
        "workspace_id": occurrence.workspace_id,
        "analysis_run_id": run.id,
        "identity_digest": digest,
        "missing_count": len(current),
        "source": source,
        "projected_at": utcnow(),
    }
    _insert_ignore(
        session,
        SymbolProjectionState.__table__,
        state_values,
        ("occurrence_id",),
    )
    session.execute(
        update(SymbolProjectionState)
        .where(SymbolProjectionState.occurrence_id == occurrence.id)
        .values(**{key: value for key, value in state_values.items() if key != "occurrence_id"})
    )
    session.flush()
    _recount_symbol_rows(session, occurrence.workspace_id, set(existing) | desired_ids)
    operation_log(
        session,
        action="symbol_projection.replace",
        target_type="occurrence",
        target_id=occurrence.id,
        workspace_id=occurrence.workspace_id,
        result=source,
        details={
            "analysis_run_id": run.id,
            "missing_count": len(current),
            "identity_digest": digest,
        },
    )
    return ProjectionWriteResult(tuple(sorted(current)), digest, len(current))


def current_missing_occurrences(
    session: Session, workspace_id: str, mode: SymbolProjectionMode | None = None
) -> dict[str, set[str]]:
    activity: dict[str, set[str]] = defaultdict(set)
    for key, oid in session.execute(
        select(MissingSymbol.identity_key, MissingSymbolOccurrence.occurrence_id)
        .join(
            MissingSymbolOccurrence, MissingSymbolOccurrence.missing_symbol_id == MissingSymbol.id
        )
        .join(Occurrence, Occurrence.id == MissingSymbolOccurrence.occurrence_id)
        .where(
            MissingSymbol.workspace_id == workspace_id,
            Occurrence.workspace_id == workspace_id,
            Occurrence.current_run_id == MissingSymbolOccurrence.analysis_run_id,
        )
    ):
        if key:
            activity[key].add(oid)
    return dict(activity)


def symbol_health_rows(
    session: Session, workspace_id: str, mode: SymbolProjectionMode | None = None
) -> list[dict[str, Any]]:
    return missing_symbol_rows(session, workspace_id)


def missing_symbol_rows(
    session: Session, workspace_id: str, mode: SymbolProjectionMode | None = None
) -> list[dict[str, Any]]:
    activity = current_missing_occurrences(session, workspace_id)
    rows = _symbol_rows_by_identity(session, workspace_id, "projection-read")
    result = []
    for key, ids in activity.items():
        row = rows.get(key)
        if row is None or not ids:
            continue
        result.append(
            {
                **{name: row[name] for name in ("code_file", "debug_file", "code_id", "debug_id")},
                "status": "missing",
                "affected_occurrence_count": len(ids),
                "first_seen": row["first_seen"].isoformat(),
                "last_seen": row["last_seen"].isoformat(),
                "occurrence_ids": sorted(ids),
            }
        )
    return sorted(result, key=lambda row: (row["last_seen"], str(row["code_file"])), reverse=True)


def workspace_projection_snapshot(
    session: Session,
    workspace_id: str,
    source: Literal["projection-read"],
) -> dict[str, Any]:
    """Build the complete deterministic snapshot used before strict/read cutover."""

    activity = current_missing_occurrences(session, workspace_id, source)
    occurrence_ids = sorted({item for values in activity.values() for item in values})
    current_runs = {
        str(occurrence_id): str(run_id) if run_id is not None else None
        for occurrence_id, run_id in session.execute(
            select(Occurrence.id, Occurrence.current_run_id).where(
                Occurrence.workspace_id == workspace_id,
                Occurrence.id.in_(occurrence_ids or {"__none__"}),
            )
        )
    }
    projected_runs: dict[tuple[str, str], str | None]
    if source == "projection-read":
        projected_runs = {
            (str(identity_key), str(occurrence_id)): str(run_id)
            for identity_key, occurrence_id, run_id in session.execute(
                select(
                    MissingSymbol.identity_key,
                    MissingSymbolOccurrence.occurrence_id,
                    MissingSymbolOccurrence.analysis_run_id,
                )
                .join(
                    MissingSymbolOccurrence,
                    MissingSymbolOccurrence.missing_symbol_id == MissingSymbol.id,
                )
                .where(
                    MissingSymbol.workspace_id == workspace_id,
                    MissingSymbol.identity_key.is_not(None),
                )
            )
        }
    else:
        projected_runs = {
            (identity_key, occurrence_id): current_runs.get(occurrence_id)
            for identity_key, values in activity.items()
            for occurrence_id in values
        }
    identities = [
        {
            "identity_key": identity_key,
            "occurrence_ids": sorted(values),
            "winner_runs": [
                {
                    "occurrence_id": occurrence_id,
                    "analysis_run_id": projected_runs.get((identity_key, occurrence_id)),
                }
                for occurrence_id in sorted(values)
            ],
        }
        for identity_key, values in sorted(activity.items())
        if values
    ]
    return {
        "identities": identities,
        "symbol_health": symbol_health_rows(session, workspace_id, source),
        "missing_symbols": missing_symbol_rows(session, workspace_id, source),
    }


def projection_invariant_counts(session: Session) -> dict[str, int]:
    remaining = int(
        session.scalar(
            select(func.count())
            .select_from(Occurrence)
            .outerjoin(
                SymbolProjectionState,
                SymbolProjectionState.occurrence_id == Occurrence.id,
            )
            .where(
                Occurrence.current_run_id.is_not(None),
                (
                    SymbolProjectionState.analysis_run_id.is_(None)
                    | (SymbolProjectionState.analysis_run_id != Occurrence.current_run_id)
                ),
            )
        )
        or 0
    )
    stale_relations = int(
        session.scalar(
            select(func.count())
            .select_from(MissingSymbolOccurrence)
            .join(Occurrence, Occurrence.id == MissingSymbolOccurrence.occurrence_id)
            .where(
                (MissingSymbolOccurrence.workspace_id != Occurrence.workspace_id)
                | (MissingSymbolOccurrence.analysis_run_id != Occurrence.current_run_id)
            )
        )
        or 0
    )
    mismatch_rows = (
        select(MissingSymbol.id)
        .select_from(MissingSymbol)
        .outerjoin(
            MissingSymbolOccurrence,
            MissingSymbolOccurrence.missing_symbol_id == MissingSymbol.id,
        )
        .where(MissingSymbol.identity_key.is_not(None))
        .group_by(MissingSymbol.id, MissingSymbol.affected_occurrence_count)
        .having(
            MissingSymbol.affected_occurrence_count
            != func.count(MissingSymbolOccurrence.occurrence_id)
        )
        .subquery()
    )
    count_mismatches = int(session.scalar(select(func.count()).select_from(mismatch_rows)) or 0)
    return {
        "missing_current_projection": remaining,
        "stale_relations": stale_relations,
        "aggregate_count_mismatches": count_mismatches,
    }


def _assert_current_canonical(
    occurrence: Occurrence, run: AnalysisRun, canonical: Mapping[str, Any]
) -> None:
    expected = {
        "workspace_id": occurrence.workspace_id,
        "occurrence_id": occurrence.id,
        "analysis_id": run.id,
    }
    mismatches = [name for name, value in expected.items() if canonical.get(name) != value]
    if occurrence.current_run_id != run.id:
        mismatches.append("current_run_id")
    if run.occurrence_id != occurrence.id:
        mismatches.append("run.occurrence_id")
    if mismatches:
        raise SymbolProjectionError(
            "Canonical/current identity mismatch: " + ", ".join(sorted(mismatches))
        )


def _ensure_symbol_row(
    session: Session,
    workspace_id: str,
    identity_key: str,
    module: Mapping[str, Any],
    observed_at: datetime,
) -> str:
    table: Any = MissingSymbol.__table__
    row = (
        session.execute(
            select(table)
            .where(table.c.workspace_id == workspace_id, table.c.identity_key == identity_key)
            .with_for_update()
        )
        .mappings()
        .first()
    )
    if row is None:
        values = {
            "id": symbol_row_id(workspace_id, identity_key),
            "workspace_id": workspace_id,
            "identity_key": identity_key,
            "code_file": _optional_string(module.get("code_file")),
            "code_id": _optional_string(module.get("code_id")),
            "debug_file": _optional_string(module.get("debug_file")),
            "debug_id": _optional_string(module.get("debug_id")),
            "first_seen": _aware(observed_at),
            "last_seen": _aware(observed_at),
            "affected_occurrence_count": 0,
            "status": "open",
        }
        _insert_ignore(
            session,
            table,
            values,
            (),
        )
        row = (
            session.execute(
                select(table)
                .where(table.c.workspace_id == workspace_id, table.c.identity_key == identity_key)
                .with_for_update()
            )
            .mappings()
            .one()
        )

    row_id = str(row["id"] or symbol_row_id(workspace_id, identity_key))
    first_seen = min(_aware(row["first_seen"]), _aware(observed_at))
    last_seen = max(_aware(row["last_seen"]), _aware(observed_at))
    code_file, debug_file = _deterministic_filenames(dict(row), module)
    session.execute(
        update(table)
        .where(table.c.workspace_id == workspace_id, table.c.identity_key == identity_key)
        .values(
            id=row_id,
            first_seen=first_seen,
            last_seen=last_seen,
            code_file=code_file,
            debug_file=debug_file,
            code_id=_preferred_identifier(row["code_id"], module.get("code_id")),
            debug_id=_preferred_identifier(row["debug_id"], module.get("debug_id")),
        )
    )
    return row_id


def _insert_ignore(
    session: Session,
    table: Any,
    values: Mapping[str, Any],
    index_elements: tuple[str, ...],
) -> None:
    dialect = session.get_bind().dialect.name
    statement: Any
    if dialect == "postgresql":
        statement = postgresql_insert(table).values(**values)
        statement = (
            statement.on_conflict_do_nothing(index_elements=list(index_elements))
            if index_elements
            else statement.on_conflict_do_nothing()
        )
    elif dialect == "sqlite":
        statement = sqlite_insert(table).values(**values)
        statement = (
            statement.on_conflict_do_nothing(index_elements=list(index_elements))
            if index_elements
            else statement.on_conflict_do_nothing()
        )
    else:
        statement = insert(table).values(**values)
    session.execute(statement)


def _recount_symbol_rows(session: Session, workspace_id: str, row_ids: set[str]) -> None:
    if not row_ids:
        return
    counts = {
        str(row_id): int(count)
        for row_id, count in session.execute(
            select(
                MissingSymbolOccurrence.missing_symbol_id,
                func.count(MissingSymbolOccurrence.occurrence_id),
            )
            .where(
                MissingSymbolOccurrence.workspace_id == workspace_id,
                MissingSymbolOccurrence.missing_symbol_id.in_(row_ids),
            )
            .group_by(MissingSymbolOccurrence.missing_symbol_id)
        )
    }
    rows = session.execute(
        select(MissingSymbol.__table__).where(
            MissingSymbol.workspace_id == workspace_id, MissingSymbol.id.in_(row_ids)
        )
    ).mappings()
    for row in rows:
        count = counts.get(str(row["id"]), 0)
        values: dict[str, Any] = {"affected_occurrence_count": count}
        if row["status"] != "ignored":
            values["status"] = "open" if count else "resolved"
        session.execute(
            update(MissingSymbol)
            .where(
                MissingSymbol.workspace_id == workspace_id,
                MissingSymbol.id == row["id"],
            )
            .values(**values)
        )


def _symbol_rows_by_identity(
    session: Session, workspace_id: str, mode: SymbolProjectionMode
) -> dict[str, Mapping[str, Any]]:
    rows = list(
        session.execute(
            select(MissingSymbol.__table__).where(MissingSymbol.workspace_id == workspace_id)
        ).mappings()
    )
    if mode == "projection-read":
        rows = [row for row in rows if row["identity_key"] is not None]
    rows.sort(
        key=lambda row: (
            0 if row["identity_key"] is not None else 1,
            _aware(row["first_seen"]),
            str(row["id"] or ""),
        )
    )
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        row_value = dict(row)
        result.setdefault(_row_identity_key(row_value), row_value)
    return result


def _row_identity_key(row: Mapping[str, Any]) -> str:
    identity_key = row.get("identity_key")
    return str(identity_key) if identity_key else symbol_identity_key(row)


def _deterministic_filenames(
    row: Mapping[str, Any], module: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    candidates = [
        (_optional_string(row.get("code_file")), _optional_string(row.get("debug_file"))),
        (_optional_string(module.get("code_file")), _optional_string(module.get("debug_file"))),
    ]
    candidates.sort(
        key=lambda pair: (
            normalize_symbol_filename(pair[0]),
            normalize_symbol_filename(pair[1]),
            pair[0] or "",
            pair[1] or "",
        )
    )
    return candidates[0]


def _preferred_identifier(existing: object, candidate: object) -> str | None:
    values = [value for value in (_optional_string(existing), _optional_string(candidate)) if value]
    return min(values, key=lambda value: (value.casefold(), value)) if values else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()
