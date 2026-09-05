"""Bind a result-review request to server-loaded immutable evidence.

Binding is preparation, not authorization: the transaction layer must still
verify provider review objects, lock/recheck Current, and persist the audit.
"""

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..contracts import validate_contract
from ..errors import ApiError
from ..evidence_comparison import AnalysisEvidence, EvidenceAuthorization, compare_evidence
from ..frozen_inputs import canonical_bytes
from ..ids import new_ulid
from ..models import (
    AnalysisDemand,
    AnalysisRun,
    CatalogPair,
    CatalogPairReview,
    CurrentDecision,
    Occurrence,
    ResultReview,
    utcnow,
)
from ..storage import ObjectStore
from .current_decisions import (
    MAX_EVIDENCE_JSON_BYTES,
    build_native_evidence,
    parse_evidence_json,
    select_current_run,
)
from .current_projection import update_current_projections
from .symbol_catalog import lock_catalog


@dataclass(frozen=True)
class LoadedReviewEvidence:
    canonical: dict[str, Any]
    canonical_bytes: bytes
    evidence: AnalysisEvidence


def read_review_object(store: ObjectStore, key: str, expected_sha256: str) -> bytes:
    """Bound the read and independently verify stored bytes outside a DB transaction."""
    size = store.head(key).size
    if size < 0 or size > MAX_EVIDENCE_JSON_BYTES:
        raise ApiError(
            "REVIEW_OBJECT_INVALID", "Review evidence exceeds the size limit", status_code=409
        )
    payload = bytearray()
    for chunk in store.stream(key):
        if len(payload) + len(chunk) > min(size, MAX_EVIDENCE_JSON_BYTES):
            raise ApiError(
                "REVIEW_OBJECT_INVALID", "Review evidence changed while reading", status_code=409
            )
        payload.extend(chunk)
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ApiError(
            "REVIEW_OBJECT_INVALID",
            "Review evidence size or digest does not match",
            status_code=409,
        )
    return bytes(payload)


def load_result_review_evidence(
    run: AnalysisRun,
    store: ObjectStore,
    expected_sha256: str,
    *,
    initial_decision: CurrentDecision | None,
    schema_root: Path,
) -> LoadedReviewEvidence:
    """Use detached metadata; callers must recheck it under lock before promotion."""
    if not run.result_object_key or run.status not in {"COMPLETE", "PARTIAL"}:
        raise ApiError(
            "REVIEW_CANDIDATE_INELIGIBLE", "Run has no completed report", status_code=409
        )
    if run.schema_version != "2.0":
        raise ApiError("CANONICAL_VERSION_UNSUPPORTED", "Unknown report version", status_code=409)
    if (
        run.assembly_mode != "core-final"
        or initial_decision is None
        or initial_decision.candidate_run_id != run.id
        or initial_decision.occurrence_id != run.occurrence_id
        or initial_decision.candidate_evidence.get("canonical_sha256") != expected_sha256
    ):
        raise ApiError(
            "REVIEW_EVIDENCE_MISMATCH",
            "Candidate differs from its initial decision",
            status_code=409,
        )
    payload = read_review_object(store, run.result_object_key, expected_sha256)
    canonical = parse_evidence_json(payload, "review Canonical")
    schema = "analysis-result-v2.0.schema.json"
    validate_contract(canonical, schema_root / schema, "review Canonical")
    if (canonical.get("analysis_id"), canonical.get("occurrence_id")) != (
        run.id,
        run.occurrence_id,
    ):
        raise ApiError(
            "REVIEW_EVIDENCE_MISMATCH", "Stored report belongs to a different Run", status_code=409
        )
    inspect_ref = (run.run_spec or {}).get("inspect", {})
    if not isinstance(inspect_ref.get("object_key"), str) or not isinstance(
        inspect_ref.get("sha256"), str
    ):
        raise ApiError(
            "REVIEW_EVIDENCE_MISMATCH", "Frozen inspect reference is missing", status_code=409
        )
    inspect_payload = read_review_object(store, inspect_ref["object_key"], inspect_ref["sha256"])
    evidence = build_native_evidence(
        run,
        canonical,
        payload,
        parse_evidence_json(inspect_payload, "review inspect"),
        schema_root=schema_root,
    )
    return LoadedReviewEvidence(canonical, payload, evidence)


@dataclass(frozen=True)
class BoundResultReview:
    request_bytes: bytes
    request_sha256: str
    current_run_id: str
    candidate_run_id: str
    cause: str


@dataclass(frozen=True)
class ProviderReviewBasis:
    review_id: str
    pair_id: str
    qualification_version: int
    state: str
    reason: str
    object_key: str
    sha256: str


def snapshot_provider_review_basis(
    session: Session,
    bound: BoundResultReview,
    current_evidence: AnalysisEvidence,
    candidate_evidence: AnalysisEvidence,
) -> tuple[ProviderReviewBasis, ...]:
    """No object I/O; repeat under catalog lock before final commit."""
    request = parse_evidence_json(bound.request_bytes, "bound review request")
    old_pairs = {module.pair_id for module in current_evidence.modules if module.pair_id}
    new_pairs = {module.pair_id for module in candidate_evidence.modules if module.pair_id}
    result = []
    for reference in request["basis_reviews"]:
        review = session.get(CatalogPairReview, reference["review_id"])
        if review is None or review.evidence_sha256 != reference["evidence_sha256"]:
            raise ApiError(
                "REVIEW_BASIS_MISMATCH", "Provider review or digest does not match", status_code=409
            )
        pair = session.get(CatalogPair, review.pair_id)
        if (
            pair is None
            or pair.qualification_version != review.qualification_version
            or pair.state != review.state
        ):
            raise ApiError(
                "REVIEW_BASIS_CHANGED",
                "Provider review is no longer the current decision",
                status_code=409,
            )
        relevant = (
            review.state == "withdrawn"
            and review.pair_id in old_pairs
            and review.pair_id not in new_pairs
        ) or (
            review.state == "active"
            and review.pair_id in new_pairs
            and review.pair_id not in old_pairs
        )
        if not relevant:
            raise ApiError(
                "REVIEW_BASIS_UNRELATED",
                "Provider review does not support these reports",
                status_code=409,
            )
        result.append(
            ProviderReviewBasis(
                review.id,
                review.pair_id,
                review.qualification_version,
                review.state,
                review.reason,
                review.evidence_object_key,
                review.evidence_sha256,
            )
        )
    if bound.cause == "evidence_correction" and not result:
        raise ApiError(
            "REVIEW_BASIS_MISSING", "Correction requires provider review evidence", status_code=409
        )
    return tuple(result)


def read_provider_review_basis(store: ObjectStore, basis: ProviderReviewBasis) -> bytes:
    """Read detached evidence outside the metadata transaction."""
    payload = read_review_object(store, basis.object_key, basis.sha256)
    value = parse_evidence_json(payload, "provider review evidence")
    expected = {
        "schema_version": "catalog-provider-review-v1",
        "pair_id": basis.pair_id,
        "expected_version": basis.qualification_version - 1,
        "state": basis.state,
        "reason": basis.reason,
    }
    if (
        set(value) != set(expected) | {"reviewer", "evidence"}
        or type(value.get("expected_version")) is not int
        or any(value.get(key) != item for key, item in expected.items())
        or any(
            not isinstance(value.get(key), str) or not value[key].strip()
            for key in ("reviewer", "evidence")
        )
    ):
        raise ApiError(
            "REVIEW_BASIS_MISMATCH",
            "Provider evidence does not match its stored review",
            status_code=409,
        )
    return payload


def bind_result_review_request(
    request: dict[str, Any],
    current: AnalysisRun,
    candidate: AnalysisRun,
    current_evidence: AnalysisEvidence,
    candidate_evidence: AnalysisEvidence,
    *,
    schema_root: Path,
) -> BoundResultReview:
    validate_contract(
        request,
        schema_root / "drafts/qa-symbol-import/result-review-request-v1.schema.json",
        "result review request",
    )
    if current.occurrence_id != candidate.occurrence_id or current.id == candidate.id:
        raise ApiError(
            "REVIEW_TARGET_MISMATCH", "Select two reports of the same Occurrence", status_code=409
        )
    expected = {
        "current_run_id": current.id,
        "candidate_run_id": candidate.id,
        "current_canonical_sha256": current_evidence.canonical_sha256,
        "candidate_canonical_sha256": candidate_evidence.canonical_sha256,
    }
    if any(request[key] != value for key, value in expected.items()):
        raise ApiError(
            "REVIEW_TARGET_CHANGED",
            "Review the exact current report and candidate again",
            status_code=409,
        )
    if (
        (current_evidence.run_id, current_evidence.occurrence_id)
        != (current.id, current.occurrence_id)
        or (candidate_evidence.run_id, candidate_evidence.occurrence_id)
        != (candidate.id, candidate.occurrence_id)
        or current_evidence.dump_sha256 != candidate_evidence.dump_sha256
    ):
        raise ApiError(
            "REVIEW_EVIDENCE_MISMATCH",
            "Reports do not bind the same Dump evidence",
            status_code=409,
        )
    if (
        candidate.id <= current.id
        or candidate.status not in {"COMPLETE", "PARTIAL"}
        or candidate_evidence.status != candidate.status
        or candidate.schema_version != "2.0"
        or candidate.assembly_mode != "core-final"
        or candidate_evidence.provenance != "native_2.0"
        or not candidate_evidence.usable
        or not candidate_evidence.pair_evidence_complete
    ):
        raise ApiError(
            "REVIEW_CANDIDATE_INELIGIBLE",
            "Candidate is not eligible for result review",
            status_code=409,
        )
    cause = request["cause"]
    if cause == "engine_upgrade":
        # A review reason cannot disguise an ordinary symbol interpretation change.
        engine_fields = (
            "schema_version",
            "core_version",
            "core_image_digest",
            "symbolicator_version",
        )
        if not any(getattr(current, field) != getattr(candidate, field) for field in engine_fields):
            raise ApiError(
                "REVIEW_CAUSE_MISMATCH", "The reports do not have an engine change", status_code=409
            )
    if cause == "role_change":
        old_policy = (current.run_spec or {}).get("context", {}).get("role_policy_sha256")
        new_policy = (candidate.run_spec or {}).get("context", {}).get("role_policy_sha256")
        if candidate_evidence.reason != "role_change" or not new_policy or old_policy == new_policy:
            raise ApiError(
                "REVIEW_CAUSE_MISMATCH",
                "Candidate does not represent a role change",
                status_code=409,
            )
    review_ids = [item["review_id"] for item in request["basis_reviews"]]
    if len(set(review_ids)) != len(review_ids):
        raise ApiError("VALIDATION", "A provider review may only be cited once", status_code=422)
    payload = canonical_bytes(request)
    return BoundResultReview(
        payload, hashlib.sha256(payload).hexdigest(), current.id, candidate.id, cause
    )


@dataclass(frozen=True)
class PreparedResultReview:
    id: str
    occurrence_id: str
    bound: BoundResultReview
    current_metadata: bytes
    candidate_metadata: bytes
    current: LoadedReviewEvidence
    candidate: LoadedReviewEvidence
    basis: tuple[ProviderReviewBasis, ...]
    audit_object_key: str
    audit_sha256: str
    audit_bytes: bytes


def validate_review_audit(audit: dict[str, Any], schema_root: Path) -> None:
    """Validate the immutable object and cross-bind its request and evidence."""
    validate_contract(
        audit,
        schema_root / "drafts/qa-symbol-import/result-review-audit-v1.schema.json",
        "result review audit",
    )
    request = audit["request"]
    try:
        valid = datetime.fromisoformat(audit["created_at"]).utcoffset() is not None
    except ValueError:
        valid = False
    valid = (
        valid and hashlib.sha256(canonical_bytes(request)).hexdigest() == audit["request_sha256"]
    )
    for side in ("current", "candidate"):
        evidence = audit[f"{side}_evidence"]
        valid = valid and (
            evidence["run_id"] == request[f"{side}_run_id"]
            and evidence["canonical_sha256"] == request[f"{side}_canonical_sha256"]
            and evidence["occurrence_id"] == audit["occurrence_id"]
        )
    valid = (
        valid
        and audit["current_evidence"]["dump_sha256"] == audit["candidate_evidence"]["dump_sha256"]
    )
    references = [(item["review_id"], item["evidence_sha256"]) for item in request["basis_reviews"]]
    basis = [(item["review_id"], item["sha256"]) for item in audit["provider_basis"]]
    valid = valid and references == basis and len({item[0] for item in basis}) == len(basis)
    if not valid:
        raise ApiError(
            "REVIEW_AUDIT_INVALID", "Audit does not bind its request and evidence", status_code=409
        )


def commit_result_review(
    session: Session,
    prepared: PreparedResultReview,
    settings: Settings,
) -> ResultReview:
    """No object I/O or commit here: audit, selection and projections are atomic."""
    if not settings.result_reviews_enabled or not settings.evidence_promotion_enabled:
        raise ApiError("QUALIFICATION_PENDING", "Result reviews are disabled", status_code=503)
    request = parse_evidence_json(prepared.bound.request_bytes, "review request")
    if hashlib.sha256(prepared.audit_bytes).hexdigest() != prepared.audit_sha256:
        raise ValueError("prepared audit digest mismatch")
    audit = parse_evidence_json(prepared.audit_bytes, "prepared review audit")
    validate_review_audit(audit, settings.schema_root)
    if (
        audit.get("review_id") != prepared.id
        or audit.get("request") != request
        or audit.get("occurrence_id") != prepared.occurrence_id
        or audit.get("request_sha256") != prepared.bound.request_sha256
        or audit.get("current_evidence") != prepared.current.evidence.as_dict()
        or audit.get("candidate_evidence") != prepared.candidate.evidence.as_dict()
        or audit.get("provider_basis") != [asdict(item) for item in prepared.basis]
    ):
        raise ValueError("prepared audit does not bind the evidence")
    lock_catalog(session)
    occurrence = session.scalar(
        select(Occurrence)
        .where(Occurrence.id == prepared.occurrence_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if occurrence is None:
        raise ApiError("NOT_FOUND", "Occurrence not found", status_code=404)
    existing = session.scalar(
        select(ResultReview).where(
            ResultReview.occurrence_id == occurrence.id,
            ResultReview.idempotency_key == request["idempotency_key"],
        )
    )
    if existing is not None:
        if existing.request_sha256 != prepared.bound.request_sha256:
            raise ApiError(
                "IDEMPOTENCY_CONFLICT", "Review key was used for another request", status_code=409
            )
        return existing
    if occurrence.current_run_id != prepared.bound.current_run_id:
        raise ApiError(
            "REVIEW_TARGET_CHANGED", "Current changed; review the reports again", status_code=409
        )
    current = session.get(AnalysisRun, prepared.bound.current_run_id, populate_existing=True)
    candidate = session.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.id == prepared.bound.candidate_run_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        current is None
        or candidate is None
        or review_run_metadata(current) != prepared.current_metadata
        or review_run_metadata(candidate) != prepared.candidate_metadata
    ):
        raise ApiError(
            "REVIEW_TARGET_CHANGED", "Run metadata changed during review", status_code=409
        )
    bound = bind_result_review_request(
        request,
        current,
        candidate,
        prepared.current.evidence,
        prepared.candidate.evidence,
        schema_root=settings.schema_root,
    )
    if bound != prepared.bound:
        raise ValueError("prepared request digest mismatch")
    first = session.get(CurrentDecision, candidate.id, populate_existing=True)
    if (
        first is None
        or first.candidate_evidence.get("canonical_sha256") != request["candidate_canonical_sha256"]
    ):
        raise ApiError(
            "REVIEW_EVIDENCE_MISMATCH", "Initial candidate decision changed", status_code=409
        )
    basis = snapshot_provider_review_basis(
        session, bound, prepared.current.evidence, prepared.candidate.evidence
    )
    if basis != prepared.basis:
        raise ApiError(
            "REVIEW_BASIS_CHANGED", "Provider evidence changed during review", status_code=409
        )
    for module in prepared.candidate.evidence.modules:
        if module.pair_id is None:
            continue
        query = select(CatalogPair.id).where(CatalogPair.state == "active")
        for field, value in zip(
            ("code_id", "debug_id", "architecture"), module.identity, strict=True
        ):
            if value not in {None, "unknown"}:
                query = query.where(getattr(CatalogPair, field) == value)
        active_pairs = list(session.scalars(query.limit(2)))
        if active_pairs != [module.pair_id]:
            raise ApiError(
                "REVIEW_BASIS_CHANGED",
                "Candidate pair is no longer uniquely eligible",
                status_code=409,
            )
    reviewed = replace(prepared.candidate.evidence, reason=bound.cause)
    authorization = EvidenceAuthorization(
        cause=bound.cause,
        current_run_id=current.id,
        candidate_run_id=candidate.id,
        current_canonical_sha256=prepared.current.evidence.canonical_sha256,
        candidate_canonical_sha256=reviewed.canonical_sha256,
        audit_id=prepared.id,
        audit_sha256=prepared.audit_sha256,
    )
    decision = compare_evidence(prepared.current.evidence, reviewed, authorization)
    validate_contract(
        decision.as_dict(),
        settings.schema_root / "drafts/qa-symbol-import/comparison-decision-v1.schema.json",
        "review comparison decision",
    )
    row = ResultReview(
        id=prepared.id,
        occurrence_id=occurrence.id,
        current_run_id=current.id,
        candidate_run_id=candidate.id,
        idempotency_key=request["idempotency_key"],
        request_sha256=bound.request_sha256,
        request=request,
        audit_object_key=prepared.audit_object_key,
        audit_sha256=prepared.audit_sha256,
        cause=bound.cause,
        decision=decision.decision,
        reason=decision.reason,
        current_evidence=prepared.current.evidence.as_dict(),
        candidate_evidence=prepared.candidate.evidence.as_dict(),
        differences=list(decision.differences),
    )
    session.add(row)
    if decision.decision in {"promote", "correct"}:
        select_current_run(occurrence, candidate, expected_current_id=current.id)
        update_current_projections(
            session,
            occurrence,
            candidate,
            prepared.candidate.canonical,
            symbol_projection_mode=settings.symbol_projection_mode,
        )
        demand = session.scalar(
            select(AnalysisDemand)
            .where(AnalysisDemand.occurrence_id == occurrence.id)
            .with_for_update()
        )
        if (
            demand is not None
            and demand.generation == candidate.demand_generation
            and demand.state == "needs_review"
        ):
            demand.state, demand.reason, demand.not_before = "updated", decision.reason, None
            demand.updated_at = utcnow()
    session.flush()
    return row


def review_run_metadata(run: AnalysisRun) -> bytes:
    fields = (
        "id",
        "occurrence_id",
        "status",
        "schema_version",
        "assembly_mode",
        "run_spec",
        "result_object_key",
        "core_version",
        "core_image_digest",
        "symbolicator_version",
        "grouping_version",
        "winner_attempt_id",
        "winner_generation",
    )
    return canonical_bytes({field: getattr(run, field) for field in fields})


def prepare_result_review(
    sessions: sessionmaker[Session],
    store: ObjectStore,
    occurrence_id: str,
    request: dict[str, Any],
    *,
    schema_root: Path,
) -> PreparedResultReview:
    """Read/verify all evidence and persist an audit object without changing Current."""
    validate_contract(
        request,
        schema_root / "drafts/qa-symbol-import/result-review-request-v1.schema.json",
        "result review request",
    )
    with sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        if occurrence is None:
            raise ApiError("NOT_FOUND", "Occurrence not found", status_code=404)
        if occurrence.current_run_id != request["current_run_id"]:
            raise ApiError(
                "REVIEW_TARGET_CHANGED",
                "Current changed; review the reports again",
                status_code=409,
            )
        current = session.get(AnalysisRun, request["current_run_id"])
        candidate = session.get(AnalysisRun, request["candidate_run_id"])
        if (
            current is None
            or candidate is None
            or current.occurrence_id != occurrence_id
            or candidate.occurrence_id != occurrence_id
        ):
            raise ApiError(
                "REVIEW_TARGET_MISMATCH",
                "Reports do not belong to this Occurrence",
                status_code=409,
            )
        current_decision = session.get(CurrentDecision, current.id)
        candidate_decision = session.get(CurrentDecision, candidate.id)
        current_metadata, candidate_metadata = (
            review_run_metadata(current),
            review_run_metadata(candidate),
        )
        session.expunge_all()
    old = load_result_review_evidence(
        current,
        store,
        request["current_canonical_sha256"],
        initial_decision=current_decision,
        schema_root=schema_root,
    )
    new = load_result_review_evidence(
        candidate,
        store,
        request["candidate_canonical_sha256"],
        initial_decision=candidate_decision,
        schema_root=schema_root,
    )
    bound = bind_result_review_request(
        request, current, candidate, old.evidence, new.evidence, schema_root=schema_root
    )
    with sessions() as session:
        basis = snapshot_provider_review_basis(session, bound, old.evidence, new.evidence)
    for item in basis:
        read_provider_review_basis(store, item)
    review_id = f"rrv_{new_ulid()}"
    audit = canonical_bytes(
        {
            "schema_version": "result-review-audit-v1",
            "review_id": review_id,
            "occurrence_id": occurrence_id,
            "request": parse_evidence_json(bound.request_bytes, "request"),
            "request_sha256": bound.request_sha256,
            "created_at": utcnow().isoformat(),
            "current_evidence": old.evidence.as_dict(),
            "candidate_evidence": new.evidence.as_dict(),
            "provider_basis": [asdict(item) for item in basis],
        }
    )
    sha = hashlib.sha256(audit).hexdigest()
    validate_review_audit(parse_evidence_json(audit, "prepared review audit"), schema_root)
    key = f"result-reviews/{occurrence_id}/{review_id}/{sha}.json"
    store.put_bytes(key, audit, "application/json")
    read_review_object(store, key, sha)
    return PreparedResultReview(
        review_id,
        occurrence_id,
        bound,
        current_metadata,
        candidate_metadata,
        old,
        new,
        basis,
        key,
        sha,
        audit,
    )
