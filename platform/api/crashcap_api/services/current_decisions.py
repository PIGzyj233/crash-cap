"""Construct, validate and persist evidence-v1 Current decisions."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..contracts import validate_contract
from ..evidence_comparison import (
    AnalysisEvidence,
    ComparisonDecision,
    FaultAnchor,
    FrameEvidence,
    ModuleEvidence,
    SourceOutcome,
    compare_evidence,
)
from ..frozen_inputs import digest
from ..models import AnalysisRun, CurrentDecision, Occurrence

MAX_EVIDENCE_JSON_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class EvidencePromotion:
    promoted: bool
    previous_run_id: str | None
    decision: ComparisonDecision


def _hex_int(value: object) -> int:
    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise ValueError("comparison address must be hexadecimal")
    result = int(value, 16)
    if result < 0 or result > 9_007_199_254_740_991:
        raise ValueError("comparison address is outside the safe integer range")
    return result


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def parse_evidence_json(payload: bytes, label: str) -> dict[str, Any]:
    """Decode bounded JSON while rejecting duplicate keys and non-finite numbers."""

    if len(payload) > MAX_EVIDENCE_JSON_BYTES:
        raise ValueError(f"{label} exceeds the evidence JSON size limit")

    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"{label} contains a duplicate object key")
            value[key] = item
        return value

    def constant(_value: str) -> None:
        raise ValueError(f"{label} contains a non-finite number")

    try:
        value = json.loads(payload, object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _fault_module(canonical: dict[str, Any]) -> tuple[int | None, int | None]:
    address = _hex_int(canonical["crash"]["address"])
    matches = []
    for module in canonical["modules"]:
        base = _hex_int(module["image_base"])
        size = int(module["image_size"])
        if base <= address < base + size:
            matches.append((int(module["module_index"]), address - base))
    if len(matches) > 1:
        raise ValueError("fault instruction belongs to overlapping modules")
    return matches[0] if matches else (None, None)


def build_native_evidence(
    run: AnalysisRun,
    canonical: dict[str, Any],
    canonical_payload: bytes,
    inspect: dict[str, Any],
    *,
    schema_root: Path,
    status: str | None = None,
) -> AnalysisEvidence:
    """Map independently validated Canonical 2.0 and inspect bytes to evidence-v1."""

    if run.schema_version != "2.0" or run.assembly_mode != "core-final":
        raise ValueError("native evidence requires a core-final Canonical 2.0 Run")
    if (canonical.get("analysis_id"), canonical.get("occurrence_id")) != (
        run.id,
        run.occurrence_id,
    ):
        raise ValueError("Canonical assignment differs from the persisted Run")
    spec = run.run_spec
    resolution = canonical.get("symbol_resolution", {})
    if (
        resolution.get("context_sha256") != spec["context_sha256"]
        or resolution.get("inspect_sha256") != spec["inspect"]["sha256"]
    ):
        raise ValueError("Canonical evidence digests differ from the frozen Run")

    modules = []
    policy_roles = spec["policy_snapshots"]["role_policy"]["modules"]
    for module in canonical["modules"]:
        selection = module["selection"]
        identity = selection["identity"]
        sources = tuple(
            SourceOutcome(
                str(source["source_id"]),
                str(source["stage"]),
                str(source["outcome"]),
                str(source["failure_class"]),
                str(source["reason"]),
                _optional_text((source.get("diagnostic_ref") or {}).get("sha256")),
            )
            for source in module.get("source_outcomes", [])
        )
        modules.append(
            ModuleEvidence(
                int(module["module_index"]),
                (
                    _optional_text(identity.get("code_id")),
                    _optional_text(identity.get("debug_id")),
                    str(identity["architecture"]),
                ),
                str(module["role"]),
                bool(module["in_app"]),
                str(selection["state"]),
                _optional_text(selection.get("selected_pair_id")),
                # Canonical `matched` describes selection, including failed
                # downloads. Only verified Symbolicator evidence proves symbols.
                "found"
                if any(s.stage == "symbolicate" and s.outcome == "found" for s in sources)
                else str(module["status"]),
                sources,
                str(policy_roles[int(module["module_index"])].get("source", "unspecified")),
            )
        )

    frames = []
    for thread in canonical["threads"]:
        thread_id = int(thread["id"])
        for frame in thread["frames"]:
            if frame.get("inline") or frame.get("module_index") is None:
                continue
            frames.append(
                FrameEvidence(
                    thread_id,
                    int(frame["module_index"]),
                    _hex_int(frame["relative_addr"]),
                    _optional_text(frame.get("unwind_method")),
                    bool(frame["in_app"]),
                    _optional_text(frame.get("function")),
                    _optional_text(frame.get("file")),
                    int(frame["line"]) if frame.get("line") is not None else None,
                )
            )

    module_index, rva = _fault_module(canonical)
    exception = inspect.get("exception", {})
    fault_address = _optional_text(exception.get("fault_address"))
    if fault_address is not None:
        fault_address = fault_address.lower()
    comparison_context = deepcopy(spec["context"])
    role_policy = deepcopy(spec["policy_snapshots"]["role_policy"])
    for item in role_policy["modules"]:
        if item.get("source") == "catalog_default":
            item["role"], item["in_app"] = "catalog_default", False
    comparison_context["role_policy_sha256"] = digest(role_policy)
    evidence = AnalysisEvidence(
        run.id,
        run.occurrence_id,
        str(spec["dump"]["sha256"]),
        str(spec["inspect"]["sha256"]),
        str(spec["context_sha256"]),
        hashlib.sha256(canonical_payload).hexdigest(),
        status or run.status,
        str(spec["reason"]),
        "native_2.0",
        True,
        all(
            module["selection"].get("candidates_complete") is True
            for module in canonical["modules"]
        ),
        FaultAnchor(
            str(canonical["crash"]["type"]),
            int(canonical["crash"]["thread_id"])
            if canonical["crash"].get("thread_id") is not None
            else None,
            module_index,
            rva,
            _optional_text(exception.get("code") or canonical["crash"].get("exception_code")),
            _optional_text(exception.get("access_type")),
            fault_address,
        ),
        tuple(modules),
        tuple(frames),
        classification_context_sha256=digest(comparison_context),
    )
    validate_contract(
        evidence.as_dict(),
        schema_root / "drafts/qa-symbol-import/comparison-evidence-v1.schema.json",
        "comparison evidence",
    )
    return evidence


def select_current_run(
    occurrence: Occurrence,
    candidate: AnalysisRun,
    *,
    expected_current_id: str | None,
) -> None:
    """Shared selection guard; caller owns the lock and complete projection transaction."""
    if occurrence.current_run_id != expected_current_id:
        raise RuntimeError("Current changed before selection")
    if candidate.occurrence_id != occurrence.id or candidate.status not in {"COMPLETE", "PARTIAL"}:
        raise ValueError("Current requires an eligible Run of this Occurrence")
    if expected_current_id is not None and candidate.id <= expected_current_id:
        raise ValueError("Current cannot move to an older Run")
    occurrence.current_run_id = candidate.id


def promote_current_by_evidence(
    session: Session,
    occurrence: Occurrence,
    candidate: AnalysisRun,
    candidate_evidence: AnalysisEvidence,
    current_evidence: AnalysisEvidence | None,
    *,
    execution_attempt_id: str,
    execution_generation: int,
    schema_root: Path,
) -> EvidencePromotion:
    """Persist one decision and update Current while the caller holds all required locks."""

    locked_occurrence = session.scalar(
        select(Occurrence)
        .where(Occurrence.id == occurrence.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    locked_candidate = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.id == candidate.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if locked_occurrence is None or locked_candidate is None:
        raise RuntimeError("Current promotion target disappeared")
    occurrence = locked_occurrence
    candidate = locked_candidate
    if candidate.occurrence_id != occurrence.id:
        raise ValueError("candidate Run does not belong to the locked Occurrence")
    observed_current = current_evidence.run_id if current_evidence is not None else None
    if occurrence.current_run_id != observed_current:
        raise RuntimeError("Current changed before evidence comparison")
    if candidate_evidence.run_id != candidate.id:
        raise ValueError("candidate evidence does not bind the candidate Run")
    existing = session.get(CurrentDecision, candidate.id)
    if existing is not None:
        raise RuntimeError("candidate already has an immutable Current decision")

    # Human authorization is accepted only by the post-result review transaction.
    decision = compare_evidence(current_evidence, candidate_evidence)
    validate_contract(
        decision.as_dict(),
        schema_root / "drafts/qa-symbol-import/comparison-decision-v1.schema.json",
        "Current comparison decision",
    )
    promoted = decision.decision in {"promote", "correct"}
    if promoted:
        select_current_run(occurrence, candidate, expected_current_id=observed_current)
    session.add(
        CurrentDecision(
            candidate_run_id=candidate.id,
            occurrence_id=occurrence.id,
            observed_current_run_id=observed_current,
            rule_version=decision.version,
            decision=decision.decision,
            reason=decision.reason,
            retry_recommended=decision.retry,
            differences=list(decision.differences),
            current_evidence=current_evidence.as_dict() if current_evidence else None,
            candidate_evidence=candidate_evidence.as_dict(),
            audit_id=decision.audit_id,
            audit_sha256=decision.audit_sha256,
            execution_attempt_id=execution_attempt_id,
            execution_generation=execution_generation,
        )
    )
    session.flush()
    return EvidencePromotion(promoted, observed_current, decision)
