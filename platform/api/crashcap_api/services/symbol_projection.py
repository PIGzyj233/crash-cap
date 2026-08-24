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
    SYMBOL_PROJECTION_SHADOW_MISMATCHES,
    SYMBOL_PROJECTION_STRICT_FAILURES,
    SYMBOL_PROJECTION_WRITES,
)
from ..models import (
    AnalysisRun,
    Artifact,
    Build,
    BuildModule,
    MissingSymbol,
    MissingSymbolOccurrence,
    Occurrence,
    OperationLog,
    SymbolProjectionState,
    utcnow,
)
from .common import operation_log

LOGGER = logging.getLogger(__name__)

SymbolProjectionMode = Literal["legacy", "shadow-soft", "strict-writer", "projection-read"]
ProjectionSource = Literal["promotion", "backfill"]
MISSING_REASONS = frozenset({"missing_pe", "missing_pdb", "pdb_mismatch", "pe_mismatch"})
_REASON_ORDER = {"pe_mismatch": 0, "pdb_mismatch": 1, "missing_pe": 2, "missing_pdb": 3}


class SymbolProjectionError(RuntimeError):
    """A Current Analysis could not be represented by the durable projection."""


class SymbolProjectionMismatch(SymbolProjectionError):
    """The compatibility writer and durable relation produced different current sets."""


@dataclass(frozen=True)
class ProjectionWriteResult:
    identity_keys: tuple[str, ...]
    identity_digest: str
    missing_count: int


@dataclass(frozen=True)
class ProjectionComparison:
    matches: bool
    differences: tuple[dict[str, Any], ...]


def projection_mode(session: Session) -> SymbolProjectionMode:
    value = session.info.get("symbol_projection_mode", "legacy")
    if value not in {"legacy", "shadow-soft", "strict-writer", "projection-read"}:
        raise SymbolProjectionError(f"unsupported Symbol projection mode: {value}")
    return cast(SymbolProjectionMode, value)


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


def _legacy_identity_key(module: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        {"code_id": module.get("code_id"), "debug_id": module.get("debug_id")},
        sort_keys=True,
        separators=(",", ":"),
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
) -> ProjectionComparison | None:
    """Apply the selected dual-write policy inside the caller's finalize transaction."""

    _assert_current_canonical(occurrence, run, canonical)
    update_legacy_symbol_health(session, occurrence, canonical)
    if mode == "legacy":
        SYMBOL_PROJECTION_WRITES.labels(mode, "legacy_only").inc()
        return None

    if mode == "shadow-soft":
        try:
            with session.begin_nested():
                replace_current_symbol_projection(
                    session,
                    occurrence=occurrence,
                    run=run,
                    canonical=canonical,
                    source="promotion",
                )
            comparison = compare_workspace_projection(session, occurrence.workspace_id)
            _record_comparison_audit(session, occurrence, run, mode, comparison)
            SYMBOL_PROJECTION_WRITES.labels(mode, "written").inc()
            if not comparison.matches:
                SYMBOL_PROJECTION_SHADOW_MISMATCHES.inc()
            return comparison
        except Exception as error:
            SYMBOL_PROJECTION_WRITES.labels(mode, "write_failed").inc()
            LOGGER.exception(
                "Symbol projection shadow write failed",
                extra={
                    "workspace_id": occurrence.workspace_id,
                    "occurrence_id": occurrence.id,
                    "analysis_run_id": run.id,
                    "symbol_projection_mode": mode,
                },
            )
            operation_log(
                session,
                action="symbol_projection.shadow",
                target_type="occurrence",
                target_id=occurrence.id,
                workspace_id=occurrence.workspace_id,
                result="write_failed",
                details={"analysis_run_id": run.id, "error_type": type(error).__name__},
            )
            return ProjectionComparison(
                matches=False,
                differences=({"kind": "write_failed", "error_type": type(error).__name__},),
            )

    try:
        replace_current_symbol_projection(
            session,
            occurrence=occurrence,
            run=run,
            canonical=canonical,
            source="promotion",
        )
        comparison = compare_workspace_projection(session, occurrence.workspace_id)
        _record_comparison_audit(session, occurrence, run, mode, comparison)
        if not comparison.matches:
            SYMBOL_PROJECTION_SHADOW_MISMATCHES.inc()
            raise SymbolProjectionMismatch(
                f"Symbol projection differs from compatibility writer: {comparison.differences[:3]}"
            )
        SYMBOL_PROJECTION_WRITES.labels(mode, "written").inc()
        return comparison
    except Exception as error:
        SYMBOL_PROJECTION_WRITES.labels(mode, "write_failed").inc()
        SYMBOL_PROJECTION_STRICT_FAILURES.labels(type(error).__name__).inc()
        raise


def update_legacy_symbol_health(
    session: Session,
    occurrence: Occurrence,
    canonical: Mapping[str, Any],
) -> None:
    """Compatibility writer retained for rollback; OperationLog remains audit-only."""

    current = extract_missing_modules(canonical)
    raw_activity = _raw_legacy_activity(session, occurrence.workspace_id)
    previous_targets = {
        target_id
        for target_id, occurrence_ids in raw_activity.items()
        if occurrence.id in occurrence_ids
    }

    for key, module in current.items():
        _ensure_symbol_row(session, occurrence.workspace_id, key, module, occurrence.occurred_at)
        if occurrence.id not in raw_activity.get(key, set()):
            operation_log(
                session,
                action="missing_symbol.observe",
                target_type="missing_symbol",
                target_id=key,
                workspace_id=occurrence.workspace_id,
                details={
                    "occurrence_id": occurrence.id,
                    "reason": module.get("status"),
                    "identity_version": "symbol-identity-v2",
                },
            )
            raw_activity.setdefault(key, set()).add(occurrence.id)

    # Clear every historical target for this Occurrence, including the former
    # ID-only double-null key.  This makes a later legacy rollback replayable.
    for key in sorted(previous_targets - set(current)):
        operation_log(
            session,
            action="missing_symbol.clear",
            target_type="missing_symbol",
            target_id=key,
            workspace_id=occurrence.workspace_id,
            details={"occurrence_id": occurrence.id, "identity_version": "symbol-identity-v2"},
        )
        raw_activity.setdefault(key, set()).discard(occurrence.id)

    session.flush()
    activity = _compatible_legacy_activity(session, occurrence.workspace_id, raw_activity)
    rows = session.execute(
        select(MissingSymbol.__table__).where(MissingSymbol.workspace_id == occurrence.workspace_id)
    ).mappings()
    for row in rows:
        row_value = dict(row)
        key = _row_identity_key(row_value)
        count = len(activity.get(key, set()))
        values: dict[str, Any] = {"affected_occurrence_count": count}
        if row["status"] != "ignored":
            values["status"] = "open" if count else "resolved"
        session.execute(
            update(MissingSymbol)
            .where(
                MissingSymbol.workspace_id == occurrence.workspace_id,
                MissingSymbol.identity_key.is_not_distinct_from(row["identity_key"]),
                MissingSymbol.debug_id.is_not_distinct_from(row["debug_id"]),
                MissingSymbol.code_id.is_not_distinct_from(row["code_id"]),
                MissingSymbol.code_file.is_not_distinct_from(row["code_file"]),
                MissingSymbol.debug_file.is_not_distinct_from(row["debug_file"]),
            )
            .values(**values)
        )


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
    session: Session,
    workspace_id: str,
    mode: SymbolProjectionMode | None = None,
) -> dict[str, set[str]]:
    selected_mode = mode or projection_mode(session)
    if selected_mode == "projection-read":
        activity: dict[str, set[str]] = defaultdict(set)
        rows = session.execute(
            select(MissingSymbol.identity_key, MissingSymbolOccurrence.occurrence_id)
            .join(
                MissingSymbolOccurrence,
                MissingSymbolOccurrence.missing_symbol_id == MissingSymbol.id,
            )
            .join(Occurrence, Occurrence.id == MissingSymbolOccurrence.occurrence_id)
            .where(
                MissingSymbol.workspace_id == workspace_id,
                MissingSymbol.identity_key.is_not(None),
                Occurrence.workspace_id == workspace_id,
                Occurrence.current_run_id == MissingSymbolOccurrence.analysis_run_id,
            )
        )
        for identity_key, occurrence_id in rows:
            if identity_key:
                activity[str(identity_key)].add(str(occurrence_id))
        return dict(activity)
    return _compatible_legacy_activity(session, workspace_id)


def legacy_missing_occurrences(session: Session, workspace_id: str) -> dict[str, set[str]]:
    """Compatibility snapshot used only for rollback reads and shadow comparison."""

    return _compatible_legacy_activity(session, workspace_id)


def symbol_health_rows(
    session: Session,
    workspace_id: str,
    mode: SymbolProjectionMode | None = None,
) -> list[dict[str, Any]]:
    selected_mode = mode or projection_mode(session)
    modules = session.execute(
        select(BuildModule, Build)
        .join(Build, Build.id == BuildModule.build_id)
        .where(Build.workspace_id == workspace_id)
        .order_by(BuildModule.code_file, BuildModule.id)
    ).all()
    module_ids = [module.id for module, _build in modules]
    artifacts = list(
        session.scalars(select(Artifact).where(Artifact.module_id.in_(module_ids or {"__none__"})))
    )
    artifacts_by_module: dict[str, list[Artifact]] = defaultdict(list)
    for artifact in artifacts:
        if artifact.module_id:
            artifacts_by_module[artifact.module_id].append(artifact)
    activity = current_missing_occurrences(session, workspace_id, selected_mode)
    rows_by_identity = _symbol_rows_by_identity(session, workspace_id, selected_mode)

    result: list[dict[str, Any]] = []
    for module, _build in modules:
        module_artifacts = artifacts_by_module.get(module.id, [])
        statuses = {artifact.verification_status for artifact in module_artifacts}
        verified_kinds = {
            artifact.kind
            for artifact in module_artifacts
            if artifact.verification_status == "verified"
        }
        status = (
            "mismatch"
            if {"pdb_mismatch", "pe_mismatch"} & statuses
            else "matched"
            if {"pe", "pdb"}.issubset(verified_kinds)
            else "missing"
        )
        identity_key = symbol_identity_key(_module_mapping(module))
        missing = rows_by_identity.get(identity_key)
        first_seen = missing["first_seen"] if missing else module.created_at
        last_seen = missing["last_seen"] if missing else module.created_at
        occurrence_ids = sorted(activity.get(identity_key, set()))
        result.append(
            {
                "build_id": module.build_id,
                "module_id": module.id,
                "code_file": module.code_file,
                "debug_file": module.debug_file,
                "code_id": module.code_id,
                "debug_id": module.debug_id,
                "status": status,
                "affected_occurrence_count": len(occurrence_ids),
                "first_seen": first_seen.isoformat(),
                "last_seen": last_seen.isoformat(),
                "occurrence_ids": occurrence_ids,
            }
        )
    return result


def missing_symbol_rows(
    session: Session,
    workspace_id: str,
    mode: SymbolProjectionMode | None = None,
) -> list[dict[str, Any]]:
    selected_mode = mode or projection_mode(session)
    activity = current_missing_occurrences(session, workspace_id, selected_mode)
    rows_by_identity = _symbol_rows_by_identity(session, workspace_id, selected_mode)
    modules = session.execute(
        select(BuildModule, Build)
        .join(Build, Build.id == BuildModule.build_id)
        .where(Build.workspace_id == workspace_id)
        .order_by(BuildModule.created_at.desc(), BuildModule.id)
    ).all()
    module_by_identity: dict[str, BuildModule] = {}
    for module, _build in modules:
        module_by_identity.setdefault(symbol_identity_key(_module_mapping(module)), module)

    mismatch_identities = {
        symbol_identity_key(_module_mapping(module))
        for artifact, module in session.execute(
            select(Artifact, BuildModule)
            .join(Build, Build.id == Artifact.build_id)
            .join(BuildModule, BuildModule.id == Artifact.module_id)
            .where(
                Build.workspace_id == workspace_id,
                Artifact.verification_status.in_(["pdb_mismatch", "pe_mismatch"]),
            )
        )
    }
    result: list[dict[str, Any]] = []
    for identity_key, occurrence_ids in activity.items():
        if not occurrence_ids:
            continue
        row = rows_by_identity.get(identity_key)
        if row is None:
            continue
        module = module_by_identity.get(identity_key)
        result.append(
            {
                "build_id": module.build_id if module else None,
                "module_id": module.id if module else None,
                "code_file": row["code_file"],
                "debug_file": row["debug_file"],
                "code_id": row["code_id"],
                "debug_id": row["debug_id"],
                "status": "mismatch" if identity_key in mismatch_identities else "missing",
                "affected_occurrence_count": len(occurrence_ids),
                "first_seen": row["first_seen"].isoformat(),
                "last_seen": row["last_seen"].isoformat(),
                "occurrence_ids": sorted(occurrence_ids),
            }
        )
    result.sort(key=lambda item: (item["last_seen"], str(item["code_file"])), reverse=True)
    return result


def module_missing_counts(
    session: Session,
    workspace_id: str,
    modules: Iterable[BuildModule],
    mode: SymbolProjectionMode | None = None,
) -> dict[str, int]:
    activity = current_missing_occurrences(session, workspace_id, mode)
    return {
        module.id: len(activity.get(symbol_identity_key(_module_mapping(module)), set()))
        for module in modules
    }


def occurrence_ids_for_symbol_filters(
    session: Session,
    workspace_id: str,
    modules: Iterable[BuildModule],
    mode: SymbolProjectionMode | None = None,
) -> set[str]:
    activity = current_missing_occurrences(session, workspace_id, mode)
    rows_by_identity = _symbol_rows_by_identity(
        session, workspace_id, mode or projection_mode(session)
    )
    selected: set[str] = set()
    module_values = list(modules)
    for module in module_values:
        selected.update(activity.get(symbol_identity_key(_module_mapping(module)), set()))
        code_file = normalize_symbol_filename(module.code_file)
        debug_file = normalize_symbol_filename(module.debug_file)
        for identity_key, row in rows_by_identity.items():
            if (
                normalize_symbol_filename(row["code_file"]) == code_file
                or normalize_symbol_filename(row["debug_file"]) == debug_file
            ):
                selected.update(activity.get(identity_key, set()))
    return selected


def compare_workspace_projection(session: Session, workspace_id: str) -> ProjectionComparison:
    legacy = workspace_projection_snapshot(session, workspace_id, "legacy")
    projection = workspace_projection_snapshot(session, workspace_id, "projection-read")
    differences: list[dict[str, Any]] = []
    for section in sorted(set(legacy) | set(projection)):
        legacy_value = legacy.get(section)
        projection_value = projection.get(section)
        if legacy_value != projection_value:
            differences.append(
                {
                    "section": section,
                    "legacy_sha256": _json_digest(legacy_value),
                    "projection_sha256": _json_digest(projection_value),
                }
            )
    return ProjectionComparison(not differences, tuple(differences))


def workspace_projection_snapshot(
    session: Session,
    workspace_id: str,
    source: Literal["legacy", "projection-read"],
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
    count_mismatches = int(
        session.scalar(select(func.count()).select_from(mismatch_rows)) or 0
    )
    return {
        "backfill_remaining": remaining,
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
        legacy_rows = list(
            session.execute(
                select(table)
                .where(table.c.workspace_id == workspace_id, table.c.identity_key.is_(None))
                .with_for_update()
            ).mappings()
        )
        candidate = next(
            (item for item in legacy_rows if _row_identity_key(dict(item)) == identity_key), None
        )
        if candidate is not None:
            row_id = symbol_row_id(workspace_id, identity_key)
            session.execute(
                update(table)
                .where(
                    table.c.workspace_id == workspace_id,
                    table.c.identity_key.is_(None),
                    table.c.debug_id.is_not_distinct_from(candidate["debug_id"]),
                    table.c.code_id.is_not_distinct_from(candidate["code_id"]),
                    table.c.code_file.is_not_distinct_from(candidate["code_file"]),
                    table.c.debug_file.is_not_distinct_from(candidate["debug_file"]),
                )
                .values(id=row_id, identity_key=identity_key)
            )
        else:
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


def _raw_legacy_activity(session: Session, workspace_id: str) -> dict[str, set[str]]:
    activity: dict[str, set[str]] = defaultdict(set)
    rows = session.scalars(
        select(OperationLog)
        .where(
            OperationLog.workspace_id == workspace_id,
            OperationLog.action.in_(["missing_symbol.observe", "missing_symbol.clear"]),
        )
        .order_by(OperationLog.id)
    )
    for row in rows:
        details = row.details or {}
        occurrence_id = details.get("occurrence_id")
        if not isinstance(occurrence_id, str) or not row.target_id:
            continue
        if row.action == "missing_symbol.observe":
            activity[row.target_id].add(occurrence_id)
        else:
            activity[row.target_id].discard(occurrence_id)
    return dict(activity)


def _compatible_legacy_activity(
    session: Session,
    workspace_id: str,
    raw_activity: dict[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    raw = raw_activity or _raw_legacy_activity(session, workspace_id)
    aliases: dict[str, set[str]] = defaultdict(set)
    identity_keys: set[str] = set()
    rows = session.execute(
        select(MissingSymbol.__table__).where(MissingSymbol.workspace_id == workspace_id)
    ).mappings()
    for row in rows:
        row_value = dict(row)
        key = _row_identity_key(row_value)
        identity_keys.add(key)
        aliases[_legacy_identity_key(row_value)].add(key)
    compatible: dict[str, set[str]] = defaultdict(set)
    for target_id, occurrence_ids in raw.items():
        if target_id in identity_keys:
            target = target_id
        elif len(aliases.get(target_id, set())) == 1:
            target = next(iter(aliases[target_id]))
        else:
            target = target_id
        compatible[target].update(occurrence_ids)
    return {key: values for key, values in compatible.items() if values}


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


def _module_mapping(module: BuildModule) -> dict[str, Any]:
    return {
        "code_file": module.code_file,
        "code_id": module.code_id,
        "debug_file": module.debug_file,
        "debug_id": module.debug_id,
    }


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


def _record_comparison_audit(
    session: Session,
    occurrence: Occurrence,
    run: AnalysisRun,
    mode: SymbolProjectionMode,
    comparison: ProjectionComparison,
) -> None:
    operation_log(
        session,
        action="symbol_projection.compare",
        target_type="occurrence",
        target_id=occurrence.id,
        workspace_id=occurrence.workspace_id,
        result="match" if comparison.matches else "mismatch",
        details={
            "analysis_run_id": run.id,
            "mode": mode,
            "difference_count": len(comparison.differences),
            "differences": list(comparison.differences[:20]),
        },
    )


def _json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()
