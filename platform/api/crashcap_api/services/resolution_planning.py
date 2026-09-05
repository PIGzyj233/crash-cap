"""Freeze bounded catalog metadata; real byte validation follows outside this transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..frozen_inputs import normalize_identity
from ..models import AnalysisDemand, CatalogPairReview, DumpInspection
from .analysis_demands import require
from .catalog_materials import CatalogMaterial, CatalogMaterialError, select_material
from .symbol_catalog import candidate_page, lock_catalog


@dataclass(frozen=True)
class PlanningLimits:
    page_size: int = 200
    candidates_per_module: int = 2000
    total_candidates: int = 2000
    locations_per_file: int = 32
    validations: int = 200

    def __post_init__(self) -> None:
        require(1 <= self.page_size <= 200, "PLANNER_PAGE_LIMIT_INVALID")
        require(1 <= self.candidates_per_module <= 10000, "PLANNER_CANDIDATE_LIMIT_INVALID")
        require(1 <= self.total_candidates <= 10000, "PLANNER_TOTAL_LIMIT_INVALID")
        require(1 <= self.locations_per_file <= 200, "PLANNER_LOCATION_LIMIT_INVALID")
        require(1 <= self.validations <= 10000, "PLANNER_VALIDATION_LIMIT_INVALID")


@dataclass(frozen=True)
class PairSnapshot:
    pair_id: str
    state: str
    qualification_version: int
    identity: dict[str, Any]
    reviews: tuple[dict[str, Any], ...]
    pe: CatalogMaterial | None
    pdb: CatalogMaterial | None
    error: str | None


@dataclass(frozen=True)
class ModuleSnapshot:
    module_index: int
    identity: dict[str, Any]
    pair_ids: tuple[str, ...]
    enumeration_complete: bool
    enumeration_reason: str | None


@dataclass(frozen=True)
class ResolutionSnapshot:
    demand_id: str
    change_sequence: int
    workspace_id: str
    inspection_id: str
    inspector_version: str
    inspector_provenance: str
    inspect_object_key: str
    inspect_sha256: str
    dump_sha256: str
    dump_size: int
    catalog_revision: int
    modules: tuple[ModuleSnapshot, ...]
    pairs: dict[str, PairSnapshot]
    limits: PlanningLimits


def _pair(
    session: Session,
    row: dict[str, Any],
    limits: PlanningLimits,
    workspace_id: str,
) -> PairSnapshot:
    reviews = list(
        session.scalars(
            select(CatalogPairReview).where(
                CatalogPairReview.pair_id == row["pair_id"],
                CatalogPairReview.qualification_version == row["qualification_version"],
            )
        )
    )
    pe = pdb = None
    error = None
    try:
        if row["qualification_version"] > 1 and (
            len(reviews) != 1 or reviews[0].state != row["state"]
        ):
            raise CatalogMaterialError("CATALOG_REVIEW_MISSING", "permanent")
        pe = select_material(
            session,
            row["pair_id"],
            row["identity"]["debug_id"],
            "pe",
            max_locations=limits.locations_per_file,
            only_available=True,
            workspace_id=workspace_id,
        )
        pdb = select_material(
            session,
            row["pair_id"],
            row["identity"]["debug_id"],
            "pdb",
            max_locations=limits.locations_per_file,
            only_available=True,
            workspace_id=workspace_id,
        )
    except CatalogMaterialError as failure:
        error = failure.code
    return PairSnapshot(
        row["pair_id"],
        row["state"],
        row["qualification_version"],
        row["identity"],
        tuple(
            {
                "id": review.id,
                "object_key": review.evidence_object_key,
                "sha256": review.evidence_sha256,
                "state": review.state,
                "qualification_version": review.qualification_version,
            }
            for review in reviews
        ),
        pe,
        pdb,
        error,
    )


def snapshot_resolution(
    session: Session, demand_id: str, *, limits: PlanningLimits | None = None
) -> ResolutionSnapshot:
    """A single commit-fenced metadata snapshot. Never runs Core or reads objects."""
    limits = limits or PlanningLimits()
    watermark = lock_catalog(session)
    demand = session.scalar(
        select(AnalysisDemand)
        .where(AnalysisDemand.id == demand_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    require(demand is not None and demand.inspection_id is not None, "INSPECTION_REQUIRED")
    assert demand is not None and demand.inspection_id is not None
    inspection = session.get(DumpInspection, demand.inspection_id)
    require(inspection is not None, "INSPECTION_REQUIRED")
    assert inspection is not None
    pairs: dict[str, PairSnapshot] = {}
    modules = []
    for captured in inspection.modules:
        identity = normalize_identity(captured["identity"])
        selected: list[str] = []
        complete, reason = True, None
        after = None
        if identity["code_id"] is None and identity["debug_id"] is None:
            complete, reason = False, "incomplete_identity"
        else:
            while True:
                remaining = limits.candidates_per_module - len(selected)
                if remaining <= 0:
                    complete, reason = False, "enumeration_failed"
                    break
                page = candidate_page(
                    session,
                    identity,
                    after=after,
                    limit=min(limits.page_size, remaining),
                    include_locations=False,
                    workspace_id=demand.workspace_id,
                )
                require(page.revision == watermark.revision, "CATALOG_SNAPSHOT_CHANGED")
                for row in page.pairs:
                    pair_id = row["pair_id"]
                    if pair_id not in pairs:
                        if len(pairs) >= limits.total_candidates:
                            complete, reason = False, "enumeration_failed"
                            break
                        pairs[pair_id] = _pair(session, row, limits, demand.workspace_id)
                    selected.append(pair_id)
                if not complete or page.next_pair_id is None:
                    break
                after = page.next_pair_id
        modules.append(
            ModuleSnapshot(captured["module_index"], identity, tuple(selected), complete, reason)
        )
    return ResolutionSnapshot(
        demand.id,
        demand.change_sequence,
        demand.workspace_id,
        inspection.id,
        inspection.inspector_version,
        inspection.inspector_provenance,
        inspection.object_key,
        inspection.object_sha256,
        inspection.dump_sha256,
        inspection.dump_size,
        watermark.revision,
        tuple(modules),
        pairs,
        limits,
    )
