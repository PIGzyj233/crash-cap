from dataclasses import replace

from crashcap_api.evidence_comparison import compare_evidence

from .test_current_decisions import _evidence


def pair():
    old = _evidence("run_0001", "occ_one")
    new = replace(
        old,
        run_id="run_0002",
        context_sha256="a" * 64,
        classification_context_sha256="c" * 64,
        modules=tuple(replace(m, role_source="catalog_default") for m in old.modules),
    )
    old = replace(
        old,
        classification_context_sha256="c" * 64,
        modules=tuple(
            replace(
                m,
                role="unknown",
                in_app=False,
                role_source="catalog_default",
                selection_state="none",
                pair_id=None,
                symbol_status="missing",
            )
            for m in old.modules
        ),
        frames=tuple(
            replace(f, in_app=False, function=None, file=None, line=None) for f in old.frames
        ),
    )
    return old, new


def test_default_classification_can_improve_without_review():
    old, new = pair()
    decision = compare_evidence(old, new)
    assert decision.decision == "promote" and decision.reason == "improved"
    assert old.modules[0].role == "unknown" and old.frames[0].in_app is False
    assert any(d["path"].endswith("/classification") for d in decision.differences)


def test_explicit_policy_or_engine_change_is_not_treated_as_default_growth():
    old, new = pair()
    explicit = replace(new, modules=tuple(replace(m, role_source="explicit") for m in new.modules))
    assert compare_evidence(old, explicit).decision == "incomparable"
    engine = replace(new, classification_context_sha256="e" * 64)
    assert compare_evidence(old, engine).decision == "incomparable"


def test_default_growth_still_rejects_loss_or_changed_frame_interpretation():
    old, new = pair()
    old = replace(
        old,
        frames=tuple(replace(f, function="stable", file="fixture.cpp", line=8) for f in old.frames),
    )
    lost = replace(new, frames=())
    assert compare_evidence(old, lost).decision != "promote"
    assert compare_evidence(old, new).reason == "interpretation_changed"
