from __future__ import annotations

import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from crashcap_api.evidence_comparison import (
    AnalysisEvidence,
    ComparisonDecision,
    EvidenceAuthorization,
    FaultAnchor,
    FrameEvidence,
    ModuleEvidence,
    SourceOutcome,
)
from crashcap_api.evidence_comparison import (
    compare_evidence as _compare_evidence,
)
from jsonschema import Draft202012Validator

DRAFTS = Path(__file__).resolve().parents[2] / "contracts/drafts/qa-symbol-import"
EVIDENCE_SCHEMA = Draft202012Validator(
    json.loads((DRAFTS / "comparison-evidence-v1.schema.json").read_text(encoding="utf-8"))
)
DECISION_SCHEMA = Draft202012Validator(
    json.loads((DRAFTS / "comparison-decision-v1.schema.json").read_text(encoding="utf-8"))
)
VECTORS: list[dict[str, Any]] = []


@pytest.fixture(scope="module", autouse=True)
def export_qualification_vectors():
    VECTORS.clear()
    yield
    destination = os.environ.get("QAI_COMPARISON_VECTORS_OUTPUT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(VECTORS, indent=2) + "\n", encoding="utf-8")


def compare_evidence(
    current: AnalysisEvidence | None,
    candidate: AnalysisEvidence,
    authorization: EvidenceAuthorization | None = None,
) -> ComparisonDecision:
    """Every behavioral vector also checks the serialized machine contract."""
    if current is not None:
        EVIDENCE_SCHEMA.validate(current.as_dict())
    EVIDENCE_SCHEMA.validate(candidate.as_dict())
    decision = _compare_evidence(current, candidate, authorization)
    DECISION_SCHEMA.validate(decision.as_dict())
    VECTORS.append(
        {
            "current": current.as_dict() if current else None,
            "candidate": candidate.as_dict(),
            "authorization": asdict(authorization) if authorization else None,
            "decision": decision.as_dict(),
        }
    )
    return decision


def original() -> AnalysisEvidence:
    return AnalysisEvidence(
        run_id="run_00000000000000000000000001",
        occurrence_id="occ_one",
        dump_sha256="d" * 64,
        inspect_sha256="e" * 64,
        context_sha256="f" * 64,
        canonical_sha256="a" * 64,
        status="PARTIAL",
        reason="initial",
        provenance="native_1.1",
        usable=True,
        pair_evidence_complete=True,
        fault=FaultAnchor("crash", 7, 0, 4096, "0xc0000005", "read", "0x0"),
        modules=(
            ModuleEvidence(
                0, ("123456789", "a" * 33, "x86_64"), "owned", True, "unique", "a" * 64, "found"
            ),
            ModuleEvidence(
                1, ("987654321", "b" * 33, "x86_64"), "system", False, "none", None, "found"
            ),
        ),
        frames=(
            FrameEvidence(7, 0, 4096, "context", True, "app", None, None),
            FrameEvidence(7, 1, 8192, "call_frame_info", False, "kernel", "kernel.cpp", 9),
        ),
    )


def next_run(old: AnalysisEvidence, **changes: object) -> AnalysisEvidence:
    return replace(
        old,
        run_id="run_00000000000000000000000002",
        canonical_sha256="b" * 64,
        reason="symbol_refresh",
        **changes,
    )


def transient(stage: str = "download_pdb") -> SourceOutcome:
    return SourceOutcome(
        "managed-source", stage, "failed", "transient", "upstream_unavailable", "1" * 64
    )


def system_loss(old: AnalysisEvidence, *, business_gain: bool = True) -> AnalysisEvidence:
    return next_run(
        old,
        frames=(
            replace(old.frames[0], file="app.cpp", line=10) if business_gain else old.frames[0],
            replace(old.frames[1], function=None, file=None, line=None),
        ),
        modules=(
            old.modules[0],
            replace(old.modules[1], symbol_status="fetching_failed", sources=(transient(),)),
        ),
    )


def authorize(old: AnalysisEvidence, candidate: AnalysisEvidence) -> EvidenceAuthorization:
    return EvidenceAuthorization(
        candidate.reason,
        old.run_id,
        candidate.run_id,
        old.canonical_sha256,
        candidate.canonical_sha256,
        "audit_verified",
        "9" * 64,
    )


def test_first_unknown_role_report_can_be_current() -> None:
    candidate = replace(
        original(),
        modules=(replace(original().modules[0], role="unknown", in_app=False),),
        frames=(),
    )
    assert compare_evidence(None, candidate).reason == "initial"


def test_equivalent_and_strict_business_gain_promote() -> None:
    old = original()
    assert compare_evidence(old, next_run(old)).reason == "equivalent"
    candidate = next_run(old, frames=(replace(old.frames[0], line=7), old.frames[1]))
    assert compare_evidence(old, candidate).reason == "improved"


def test_q16_requires_business_gain_preserved_anchors_and_system_transient() -> None:
    old = original()
    decision = compare_evidence(old, system_loss(old))
    assert (decision.decision, decision.reason, decision.retry) == (
        "promote",
        "q16_system_transient",
        True,
    )
    decision = compare_evidence(old, system_loss(old, business_gain=False))
    assert (decision.decision, decision.reason, decision.retry) == (
        "retain",
        "system_transient_loss",
        True,
    )


def test_q16_promotion_does_not_erase_an_ongoing_transient_failure() -> None:
    current = system_loss(original())
    candidate = replace(current, run_id="run_00000000000000000000000003")
    decision = compare_evidence(current, candidate)
    assert (decision.decision, decision.reason, decision.retry) == (
        "promote", "equivalent", True,
    )
    restored = replace(
        candidate,
        modules=(candidate.modules[0], original().modules[1]),
        frames=(candidate.frames[0], original().frames[1]),
    )
    assert compare_evidence(current, restored).retry is False


@pytest.mark.parametrize("failure_class", ["permanent", "unknown"])
def test_q16_retry_stops_when_the_current_diagnostic_is_not_transient(failure_class) -> None:
    current = system_loss(original())
    candidate = replace(
        current,
        run_id="run_00000000000000000000000003",
        modules=(
            current.modules[0],
            replace(
                current.modules[1], sources=(replace(transient(), failure_class=failure_class),)
            ),
        ),
    )
    assert compare_evidence(current, candidate).retry is False


def test_equivalent_success_does_not_retry_an_unused_failing_source() -> None:
    old = original()
    old = replace(old, modules=(old.modules[0], replace(old.modules[1], sources=(transient(),))))
    assert compare_evidence(old, next_run(old)).retry is False


@pytest.mark.parametrize("role", ["dependency", "unknown", "owned"])
def test_q16_never_calls_dependency_unknown_or_owned_system(role: str) -> None:
    old = original()
    old = replace(old, modules=(old.modules[0], replace(old.modules[1], role=role)))
    decision = compare_evidence(old, system_loss(old))
    assert (decision.decision, decision.reason) == ("retain", "non_system_transient_loss")


@pytest.mark.parametrize("status", ["missing", "malformed", "unsupported"])
def test_real_permanent_failure_cannot_use_transient_exception(status: str) -> None:
    old = original()
    candidate = system_loss(old)
    candidate = replace(
        candidate,
        modules=(candidate.modules[0], replace(candidate.modules[1], symbol_status=status)),
    )
    assert compare_evidence(old, candidate).reason == "permanent_loss"
    assert compare_evidence(old, candidate).retry is False


def test_unknown_failure_and_unrelated_stage_do_not_justify_q16() -> None:
    old = original()
    candidate = system_loss(old)
    for sources in (
        (),
        (replace(transient(), diagnostic_sha256=None),),
        (transient("download_pe"),),
    ):
        candidate = replace(
            candidate,
            modules=(candidate.modules[0], replace(candidate.modules[1], sources=sources)),
        )
        assert compare_evidence(old, candidate).reason == "unknown_loss"
        assert compare_evidence(old, candidate).retry is False


def test_business_temporary_loss_retains_current_and_retries() -> None:
    old = original()
    candidate = next_run(
        old,
        frames=(replace(old.frames[0], function=None), old.frames[1]),
        modules=(replace(old.modules[0], sources=(transient(),)), old.modules[1]),
    )
    decision = compare_evidence(old, candidate)
    assert (decision.decision, decision.reason, decision.retry) == (
        "retain",
        "business_transient_loss",
        True,
    )


def test_all_business_anchors_are_protected_not_only_first_five() -> None:
    old = original()
    frames = tuple(
        replace(old.frames[0], rva=4096 + i * 16, function=f"frame{i}") for i in range(7)
    )
    old = replace(old, frames=frames)
    candidate = next_run(
        old,
        frames=frames[:-1] + (replace(frames[-1], function=None),),
        modules=(replace(old.modules[0], sources=(transient(),)), old.modules[1]),
    )
    assert compare_evidence(old, candidate).reason == "business_transient_loss"


def test_unwind_loss_only_uses_relevant_pe_failure() -> None:
    old = original()
    old = replace(
        old, frames=(replace(old.frames[0], unwind_method="call_frame_info"), old.frames[1])
    )
    candidate = next_run(
        old,
        frames=(replace(old.frames[0], unwind_method="scan"), old.frames[1]),
        modules=(replace(old.modules[0], sources=(transient("download_pe"),)), old.modules[1]),
    )
    assert compare_evidence(old, candidate).reason == "business_transient_loss"
    candidate = replace(
        candidate, modules=(replace(old.modules[0], sources=(transient(),)), old.modules[1])
    )
    assert compare_evidence(old, candidate).reason == "unknown_loss"


def test_reliability_is_not_a_weight_order() -> None:
    old = original()
    candidate = next_run(
        old, frames=(replace(old.frames[0], unwind_method="frame_pointer"), old.frames[1])
    )
    assert compare_evidence(old, candidate).reason == "unwind_changed"


def test_recursive_alignment_ambiguity_retains_candidate_for_review() -> None:
    old = original()
    candidate = next_run(old, frames=(old.frames[0], old.frames[0], old.frames[1]))
    decision = compare_evidence(old, candidate)
    assert (decision.decision, decision.reason, decision.retry) == (
        "incomparable",
        "ambiguous_alignment",
        False,
    )


def test_equal_recursive_occurrences_are_preserved_individually() -> None:
    old = original()
    old = replace(old, frames=(old.frames[0], old.frames[0], old.frames[1]))
    assert compare_evidence(old, next_run(old)).reason == "equivalent"


def test_changed_explanation_is_not_an_improvement() -> None:
    old = original()
    candidate = next_run(
        old, frames=(replace(old.frames[0], function="different", line=7), old.frames[1])
    )
    assert compare_evidence(old, candidate).reason == "interpretation_changed"


def test_unknown_module_pair_gain_does_not_make_q16_a_business_gain() -> None:
    old = original()
    old = replace(
        old,
        modules=old.modules
        + (
            ModuleEvidence(
                2, (None, "c" * 33, "x86_64"), "unknown", False, "none", None, "missing"
            ),
        ),
    )
    candidate = system_loss(old, business_gain=False)
    candidate = replace(
        candidate,
        modules=candidate.modules
        + (
            replace(
                old.modules[2], selection_state="unique", pair_id="c" * 64, symbol_status="found"
            ),
        ),
    )
    assert compare_evidence(old, candidate).reason == "system_transient_loss"


@pytest.mark.parametrize(
    "field", ["context_sha256", "inspect_sha256", "dump_sha256", "occurrence_id"]
)
def test_incompatible_context_cannot_compare(field: str) -> None:
    old = original()
    decision = compare_evidence(old, next_run(old, **{field: "7" * 64}))
    assert decision.decision == "incomparable"


def test_old_folded_trust_does_not_become_verified_cfi() -> None:
    old = original()
    old = replace(old, frames=(replace(old.frames[0], unwind_method=None), old.frames[1]))
    assert compare_evidence(old, next_run(old)).reason == "legacy_evidence_missing"


def test_missing_legacy_pair_evidence_is_explicit() -> None:
    old = replace(original(), pair_evidence_complete=False)
    assert compare_evidence(old, next_run(old)).reason == "pair_evidence_incomplete"


def test_new_conflict_needs_auditable_correction_not_score_protection() -> None:
    old = original()
    candidate = next_run(
        old,
        modules=(replace(old.modules[0], selection_state="conflict", pair_id=None), old.modules[1]),
    )
    assert compare_evidence(old, candidate).reason == "correction_required"
    candidate = replace(candidate, reason="evidence_correction", frames=())
    decision = compare_evidence(old, candidate, authorize(old, candidate))
    assert (decision.decision, decision.reason) == ("correct", "verified_correction")
    assert decision.audit_id == "audit_verified"


def test_legacy_version_upgrade_has_reviewed_continuity_without_inventing_trust() -> None:
    old = replace(original(), provenance="insufficient", pair_evidence_complete=False)
    candidate = replace(next_run(original()), reason="engine_upgrade", context_sha256="7" * 64)
    assert compare_evidence(old, candidate).reason == "transition_requires_review"
    assert (
        compare_evidence(old, candidate, authorize(old, candidate)).reason == "reviewed_transition"
    )
    assert old.provenance == "insufficient"


def test_review_is_bound_to_both_immutable_results_and_cannot_bypass_creation_order() -> None:
    old = original()
    candidate = replace(next_run(old), reason="engine_upgrade")
    wrong = replace(authorize(old, candidate), current_canonical_sha256="0" * 64)
    assert compare_evidence(old, candidate, wrong).reason == "transition_requires_review"
    assert compare_evidence(old, candidate, wrong).audit_id is None
    older = replace(candidate, run_id="run_00000000000000000000000000")
    assert compare_evidence(old, older, authorize(old, older)).reason == "older_candidate"


def test_ineligible_result_never_promotes_even_with_authorization() -> None:
    old = original()
    candidate = replace(next_run(old), reason="evidence_correction", status="FAILED")
    assert (
        compare_evidence(old, candidate, authorize(old, candidate)).reason
        == "candidate_not_eligible"
    )


def test_review_does_not_invent_candidate_provenance() -> None:
    old = original()
    candidate = replace(next_run(old), reason="engine_upgrade", provenance="insufficient")
    decision = compare_evidence(old, candidate, authorize(old, candidate))
    assert decision.reason == "candidate_evidence_missing"
    assert decision.audit_id is None
    assert compare_evidence(None, candidate).decision == "incomparable"


def test_fault_address_change_requires_review() -> None:
    old = original()
    candidate = next_run(old, fault=replace(old.fault, fault_address="0x8"))
    assert compare_evidence(old, candidate).reason == "fault_changed"


def test_incomplete_selection_cannot_silently_replace_a_pair() -> None:
    old = original()
    candidate = next_run(
        old,
        modules=(
            replace(old.modules[0], selection_state="indeterminate", pair_id=None),
            old.modules[1],
        ),
    )
    assert compare_evidence(old, candidate).reason == "selection_evidence_incomplete"


@pytest.mark.parametrize(
    "defect", ["duplicate_module", "unknown_module", "wrong_in_app", "missing_pair"]
)
def test_inconsistent_candidate_cannot_use_review_or_initial_promotion(defect: str) -> None:
    old = original()
    candidate = replace(next_run(old), reason="engine_upgrade")
    if defect == "duplicate_module":
        candidate = replace(candidate, modules=candidate.modules + (candidate.modules[0],))
    elif defect == "unknown_module":
        candidate = replace(candidate, frames=(replace(candidate.frames[0], module_index=9),))
    elif defect == "wrong_in_app":
        candidate = replace(candidate, frames=(replace(candidate.frames[0], in_app=False),))
    else:
        candidate = replace(
            candidate, modules=(replace(candidate.modules[0], pair_id=None), candidate.modules[1])
        )
    assert (
        compare_evidence(old, candidate, authorize(old, candidate)).reason
        == "module_evidence_incomplete"
    )
    assert compare_evidence(None, candidate).reason == "module_evidence_incomplete"
