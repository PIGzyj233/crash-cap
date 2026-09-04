"""Pure evidence-v1 eligibility. No I/O, score ranking, or Current pointer writes.

Projectors must verify immutable input hashes before constructing these records.
Authorization is constructed from a verified platform audit record, never a
client-supplied boolean. The lifecycle service must recompare under its lock.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

RELIABLE_METHODS = frozenset({"context", "call_frame_info", "frame_pointer"})
KNOWN_METHODS = RELIABLE_METHODS | {"cfi_scan", "scan", "prewalked", "unknown", None}
TERMINAL_SUCCESS = frozenset({"COMPLETE", "PARTIAL"})


@dataclass(frozen=True)
class SourceOutcome:
    source_id: str
    stage: str
    outcome: str
    failure_class: str
    reason: str
    diagnostic_sha256: str | None


@dataclass(frozen=True)
class ModuleEvidence:
    index: int
    identity: tuple[str | None, str | None, str]
    role: str
    in_app: bool
    selection_state: str
    pair_id: str | None
    symbol_status: str
    sources: tuple[SourceOutcome, ...] = ()


@dataclass(frozen=True)
class FrameEvidence:
    thread_id: int
    module_index: int
    rva: int
    unwind_method: str | None
    in_app: bool
    function: str | None
    file: str | None
    line: int | None

    @property
    def key(self) -> tuple[int, int]:
        return self.module_index, self.rva


@dataclass(frozen=True)
class FaultAnchor:
    kind: str
    thread_id: int | None
    module_index: int | None
    rva: int | None
    exception_code: str | None
    access_type: str | None
    fault_address: str | None


@dataclass(frozen=True)
class AnalysisEvidence:
    run_id: str
    occurrence_id: str
    dump_sha256: str
    inspect_sha256: str
    context_sha256: str
    canonical_sha256: str
    status: str
    reason: str
    provenance: str
    usable: bool
    pair_evidence_complete: bool
    fault: FaultAnchor
    modules: tuple[ModuleEvidence, ...]
    frames: tuple[FrameEvidence, ...]
    schema_version: str = "comparison-evidence-v1"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(json.dumps(asdict(self)))
        return result


@dataclass(frozen=True)
class EvidenceAuthorization:
    cause: str
    current_run_id: str
    candidate_run_id: str
    current_canonical_sha256: str
    candidate_canonical_sha256: str
    audit_id: str
    audit_sha256: str

    def covers(self, current: AnalysisEvidence, candidate: AnalysisEvidence) -> bool:
        return (
            self.cause == candidate.reason
            and self.cause in {"engine_upgrade", "role_change", "evidence_correction"}
            and self.current_run_id == current.run_id
            and self.candidate_run_id == candidate.run_id
            and self.current_canonical_sha256 == current.canonical_sha256
            and self.candidate_canonical_sha256 == candidate.canonical_sha256
            and bool(self.audit_id)
            and len(self.audit_sha256) == 64
            and all(c in "0123456789abcdef" for c in self.audit_sha256)
        )


@dataclass(frozen=True)
class ComparisonDecision:
    current_run_id: str | None
    candidate_run_id: str
    decision: str
    reason: str
    retry: bool
    differences: tuple[dict[str, Any], ...]
    audit_id: str | None = None
    audit_sha256: str | None = None
    version: str = "evidence-v1"

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(json.dumps(asdict(self)))
        return result


@dataclass(frozen=True)
class _Loss:
    module_index: int
    stage: str
    business: bool


def _shape_valid(evidence: AnalysisEvidence) -> bool:
    modules = {m.index: m for m in evidence.modules}
    return (
        len(modules) == len(evidence.modules)
        and all(
            (m.selection_state == "unique") == (m.pair_id is not None) for m in evidence.modules
        )
        and all(
            f.module_index in modules
            and f.in_app == modules[f.module_index].in_app
            and f.unwind_method in KNOWN_METHODS
            for f in evidence.frames
        )
    )


def _align(old: list[FrameEvidence], new: list[FrameEvidence]) -> list[int] | None:
    """Unique monotone embedding; repeated RVAs are never collapsed into a set."""
    earliest: list[int] = []
    cursor = 0
    for frame in old:
        while cursor < len(new) and new[cursor].key != frame.key:
            cursor += 1
        if cursor == len(new):
            return None
        earliest.append(cursor)
        cursor += 1
    latest: list[int] = []
    cursor = len(new) - 1
    for frame in reversed(old):
        while cursor >= 0 and new[cursor].key != frame.key:
            cursor -= 1
        if cursor < 0:
            return None
        latest.append(cursor)
        cursor -= 1
    return earliest if earliest == list(reversed(latest)) else None


def _loss_class(module: ModuleEvidence, stage: str) -> str:
    if stage == "symbols" and module.symbol_status in {"missing", "malformed", "unsupported"}:
        return "permanent"
    stages = {"unwind", "download_pe"} if stage == "unwind" else {"symbolicate", "download_pdb"}
    outcomes = [s for s in module.sources if s.stage in stages and s.outcome != "found"]
    if not outcomes:
        return "unknown"
    if any(s.outcome == "missing" or s.failure_class == "permanent" for s in outcomes):
        return "permanent"
    if all(
        s.outcome == "failed"
        and s.failure_class == "transient"
        and s.diagnostic_sha256 is not None
        and len(s.diagnostic_sha256) == 64
        and all(c in "0123456789abcdef" for c in s.diagnostic_sha256)
        for s in outcomes
    ):
        return "transient"
    return "unknown"


def compare_evidence(
    current: AnalysisEvidence | None,
    candidate: AnalysisEvidence,
    authorization: EvidenceAuthorization | None = None,
) -> ComparisonDecision:
    differences: list[dict[str, Any]] = []
    authorized_id: str | None = None
    authorized_sha: str | None = None

    def result(decision: str, reason: str, *, retry: bool = False) -> ComparisonDecision:
        return ComparisonDecision(
            current.run_id if current else None,
            candidate.run_id,
            decision,
            reason,
            retry,
            tuple(differences),
            authorized_id,
            authorized_sha,
        )

    def delta(path: str, before: Any, after: Any) -> None:
        differences.append({"path": path, "before": before, "after": after})

    if candidate.status not in TERMINAL_SUCCESS or not candidate.usable:
        return result("retain", "candidate_not_eligible")
    if candidate.provenance not in {"native_1.1", "verified_raw_mapping"}:
        return result("incomparable", "candidate_evidence_missing")
    if not _shape_valid(candidate):
        return result("incomparable", "module_evidence_incomplete")
    if current is None:
        return result("promote", "initial")
    if (
        current.occurrence_id != candidate.occurrence_id
        or current.dump_sha256 != candidate.dump_sha256
    ):
        return result("incomparable", "occurrence_or_dump_mismatch")
    # Existing platform Run IDs contain sortable ULIDs. Old results may not be
    # promoted again by treating demand generation or finish time as creation.
    if candidate.run_id <= current.run_id:
        return result("retain", "older_candidate")
    if (
        authorization is not None
        and authorization.covers(current, candidate)
        and candidate.pair_evidence_complete
    ):
        authorized_id, authorized_sha = authorization.audit_id, authorization.audit_sha256
        delta("authorization", current.canonical_sha256, candidate.canonical_sha256)
        if candidate.reason == "evidence_correction":
            return result("correct", "verified_correction")
        return result("promote", "reviewed_transition")
    if candidate.reason not in {"symbol_refresh", "manual"}:
        return result("incomparable", "transition_requires_review")
    if current.provenance == "insufficient" or not current.usable:
        return result("incomparable", "legacy_evidence_missing")
    if not current.pair_evidence_complete or not candidate.pair_evidence_complete:
        return result("incomparable", "pair_evidence_incomplete")
    if (
        current.context_sha256 != candidate.context_sha256
        or current.inspect_sha256 != candidate.inspect_sha256
    ):
        delta("context_sha256", current.context_sha256, candidate.context_sha256)
        delta("inspect_sha256", current.inspect_sha256, candidate.inspect_sha256)
        return result("incomparable", "context_mismatch")
    if current.fault != candidate.fault:
        delta("fault_anchor", asdict(current.fault), asdict(candidate.fault))
        return result("incomparable", "fault_changed")
    old_modules = {m.index: m for m in current.modules}
    new_modules = {m.index: m for m in candidate.modules}
    if not _shape_valid(current) or old_modules.keys() != new_modules.keys():
        return result("incomparable", "module_evidence_incomplete")
    for index, old_module in old_modules.items():
        new_module = new_modules[index]
        if (old_module.identity, old_module.role, old_module.in_app) != (
            new_module.identity,
            new_module.role,
            new_module.in_app,
        ):
            return result("incomparable", "context_mismatch")

    losses: list[_Loss] = []
    improved = False
    business_improved = False
    for business in (True, False):
        old_frames = [
            f
            for f in current.frames
            if f.unwind_method in RELIABLE_METHODS
            and (f.in_app and f.thread_id == current.fault.thread_id) == business
        ]
        if any(
            f.in_app and f.thread_id == current.fault.thread_id and f.unwind_method is None
            for f in current.frames
        ):
            return result("incomparable", "legacy_evidence_missing")
        for thread_id in sorted({f.thread_id for f in old_frames}):
            before_frames = [f for f in old_frames if f.thread_id == thread_id]
            after_frames = [f for f in candidate.frames if f.thread_id == thread_id]
            present = {f.key for f in after_frames}
            retained = []
            for frame in before_frames:
                if frame.key not in present:
                    losses.append(_Loss(frame.module_index, "unwind", business))
                    delta(
                        f"threads/{thread_id}/anchors/{frame.module_index}/{frame.rva}",
                        asdict(frame),
                        None,
                    )
                else:
                    retained.append(frame)
            mapping = _align(retained, after_frames)
            if mapping is None:
                return result("incomparable", "ambiguous_alignment")
            for old_frame, index in zip(retained, mapping, strict=True):
                new_frame = after_frames[index]
                if old_frame.in_app != new_frame.in_app:
                    return result("incomparable", "context_mismatch")
                if old_frame.unwind_method != new_frame.unwind_method:
                    delta("unwind_method", old_frame.unwind_method, new_frame.unwind_method)
                    if new_frame.unwind_method not in RELIABLE_METHODS:
                        losses.append(_Loss(old_frame.module_index, "unwind", business))
                    else:
                        return result("incomparable", "unwind_changed")
                for field in ("function", "file", "line"):
                    old_value = getattr(old_frame, field)
                    new_value = getattr(new_frame, field)
                    if old_value == new_value:
                        continue
                    delta(
                        f"threads/{thread_id}/anchors/{old_frame.module_index}/{old_frame.rva}/{field}",
                        old_value,
                        new_value,
                    )
                    if old_value is not None and new_value is not None:
                        return result("incomparable", "interpretation_changed")
                    if old_value is not None:
                        losses.append(_Loss(old_frame.module_index, "symbols", business))
                    elif new_frame.unwind_method in RELIABLE_METHODS:
                        improved = True
                        business_improved |= business

    before_business = [
        f
        for f in current.frames
        if f.in_app
        and f.thread_id == current.fault.thread_id
        and f.unwind_method in RELIABLE_METHODS
    ]
    after_business = [
        f
        for f in candidate.frames
        if f.in_app
        and f.thread_id == candidate.fault.thread_id
        and f.unwind_method in RELIABLE_METHODS
    ]
    if len(after_business) > len(before_business):
        improved = business_improved = True
    for index, old_module in old_modules.items():
        new_module = new_modules[index]
        if old_module.selection_state == "unique" and (
            new_module.selection_state in {"conflict", "unavailable"}
            or (new_module.selection_state == "unique" and old_module.pair_id != new_module.pair_id)
        ):
            delta(f"modules/{index}/pair_id", old_module.pair_id, new_module.pair_id)
            return result("incomparable", "correction_required")
        if old_module.selection_state == "unique" and new_module.selection_state != "unique":
            return result("incomparable", "selection_evidence_incomplete")
        if old_module.selection_state == "none" and new_module.selection_state == "unique":
            improved = True
        if old_module.symbol_status == "found" and new_module.symbol_status != "found":
            losses.append(_Loss(index, "symbols", old_module.in_app))
            delta(
                f"modules/{index}/symbol_status", old_module.symbol_status, new_module.symbol_status
            )

    if not losses:
        # Q16 may already have promoted the degraded system evidence. Comparing
        # against that Current must not mistake the same verified source failure
        # for recovery. The demand service still owns the finite retry budget.
        retry = False
        for index, old_module in old_modules.items():
            for stage in ("symbols", "unwind"):
                new_module = new_modules[index]
                if stage == "symbols" and new_module.symbol_status == "found":
                    continue
                if stage == "unwind" and any(
                    source.stage in {"download_pe", "unwind"} and source.outcome == "found"
                    for source in new_module.sources
                ):
                    continue
                if (
                    _loss_class(old_module, stage) == "transient"
                    and _loss_class(new_module, stage) == "transient"
                ):
                    retry = True
                    delta(f"modules/{index}/{stage}/failure_class", "transient", "transient")
        return result("promote", "improved" if improved else "equivalent", retry=retry)
    classifications = [_loss_class(new_modules[loss.module_index], loss.stage) for loss in losses]
    if "unknown" in classifications:
        return result("incomparable", "unknown_loss")
    if "permanent" in classifications:
        return result("retain", "permanent_loss")
    if any(loss.business for loss in losses):
        return result("retain", "business_transient_loss", retry=True)
    only_system = all(
        old_modules[loss.module_index].role == "system"
        and not old_modules[loss.module_index].in_app
        for loss in losses
    )
    if only_system and business_improved:
        return result("promote", "q16_system_transient", retry=True)
    return result(
        "retain",
        "system_transient_loss" if only_system else "non_system_transient_loss",
        retry=True,
    )
