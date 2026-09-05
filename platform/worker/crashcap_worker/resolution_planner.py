"""Actually validate one frozen catalog snapshot and retain its resolution manifest."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from crashcap_api.frozen_inputs import (
    canonical_bytes,
    normalize_identity,
    resolution_fingerprint,
    verify_selection,
)
from crashcap_api.ids import new_ulid
from crashcap_api.services.analysis_demands import inspection_evidence
from crashcap_api.services.catalog_materials import CatalogMaterialError, materialize_catalog_file
from crashcap_api.services.resolution_planning import PairSnapshot, ResolutionSnapshot
from crashcap_api.storage import ObjectStore

from .catalog_validation import catalog_validator_version, inspect_catalog_pair
from .core_runner import CoreExecutionError, CoreExecutor


@dataclass(frozen=True)
class PreparedResolution:
    demand_id: str
    change_sequence: int
    inspection_id: str
    manifest: dict[str, Any]
    manifest_bytes: bytes
    manifest_object_key: str
    manifest_sha256: str
    resolution_fingerprint: str
    validator_version: str


def _read_verified(store: ObjectStore, key: str, expected_sha: str, limit: int) -> bytes:
    data = bytearray()
    for block in store.stream(key, 1024 * 1024):
        if len(data) + len(block) > limit:
            raise CoreExecutionError("PLANNER_OBJECT_LIMIT", "Planning object exceeds bounded size")
        data.extend(block)
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise CoreExecutionError("PLANNER_OBJECT_HASH_MISMATCH", "Planning object failed readback")
    return bytes(data)


def _retain(store: ObjectStore, key: str, value: dict[str, Any]) -> tuple[bytes, str]:
    data = canonical_bytes(value)
    sha = hashlib.sha256(data).hexdigest()
    store.put_bytes(key, data, "application/json")
    _read_verified(store, key, sha, len(data))
    return data, sha


def _material_evidence(material: Any) -> Any:
    if material is None:
        return None
    value = asdict(material)
    value["locations"] = [asdict(location) for location in material.locations]
    return value


def _validate(
    core: CoreExecutor, store: ObjectStore, pair: PairSnapshot, root: Path
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "pair_id": pair.pair_id,
        "identity": pair.identity,
        "qualification_version": pair.qualification_version,
        "reviews": list(pair.reviews),
        "validation": "pending",
        "availability": "active",
        "materials": {
            kind: _material_evidence(value) for kind, value in (("pe", pair.pe), ("pdb", pair.pdb))
        },
    }
    if pair.error:
        return {**result, "error": pair.error, "failure_class": "unknown"}
    assert pair.pe is not None and pair.pdb is not None
    if pair.state == "withdrawn":
        return {
            **result,
            "validation": "verified",
            "availability": "withdrawn",
            "validation_basis": "retained_catalog_qualification",
        }
    if not pair.pe.locations or not pair.pdb.locations:
        return {
            **result,
            "validation": "verified",
            "availability": "location_unavailable",
            "validation_basis": "retained_catalog_qualification",
        }
    try:
        # This per-pair directory is discarded even when a replica or validator fails.
        with tempfile.TemporaryDirectory(prefix="pair-", dir=root) as temporary:
            directory = Path(temporary)
            selected = {}
            for kind, material in (("pe", pair.pe), ("pdb", pair.pdb)):
                part = directory / kind
                part.mkdir()
                selected[kind] = materialize_catalog_file(store, material, part / "raw").id
            reports = inspect_catalog_pair(core, directory / "pe/raw", directory / "pdb/raw")
            for kind, material in (("pe", pair.pe), ("pdb", pair.pdb)):
                if (reports[kind]["sha256"], reports[kind]["size"]) != (
                    material.raw_sha256,
                    material.raw_size,
                ):
                    raise CoreExecutionError(
                        "PLANNER_ACTUAL_CONTENT_MISMATCH",
                        "Core disagrees with retained raw content",
                    )
            actual = normalize_identity(reports["pe"])
            if actual != pair.identity:
                raise CoreExecutionError(
                    "PLANNER_CATALOG_IDENTITY_MISMATCH",
                    "Actual identity disagrees with catalog snapshot",
                )
            return {
                **result,
                "validation": "verified",
                "identity": actual,
                "validation_basis": "actual_core",
                "selected_locations": selected,
                "actual_reports": reports,
            }
    except CatalogMaterialError as error:
        return {**result, "error": error.code, "failure_class": error.failure_class}
    except CoreExecutionError as error:
        # Only a typed, completed invalid pair check proves exclusion. Process,
        # environment and integrity failures remain unfinished validation.
        invalid = error.code == "CATALOG_PAIR_INVALID"
        return {
            **result,
            "validation": "invalid" if invalid else "pending",
            "error": error.code,
            "failure_class": "permanent" if invalid else "unknown",
        }
    except OSError:
        return {**result, "error": "PLANNER_IO_FAILED", "failure_class": "transient"}


def prepare_resolution(
    core: CoreExecutor, store: ObjectStore, snapshot: ResolutionSnapshot
) -> PreparedResolution:
    """No ORM/session is accepted here; object and Core work cannot span a DB lock."""
    validator = catalog_validator_version(core)
    inspected = _read_verified(
        store, snapshot.inspect_object_key, snapshot.inspect_sha256, 64 * 1024**2
    )
    evidence = inspection_evidence(
        inspected,
        dump_sha256=snapshot.dump_sha256,
        dump_size=snapshot.dump_size,
        inspector_version=snapshot.inspector_version,
        inspector_provenance=snapshot.inspector_provenance,
        object_key=snapshot.inspect_object_key,
    )
    captured = tuple(
        {"module_index": m.module_index, "identity": m.identity} for m in snapshot.modules
    )
    if evidence.modules != captured:
        raise CoreExecutionError(
            "PLANNER_INSPECT_MISMATCH", "Stored inspect differs from snapshot identities"
        )
    core.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
    prefix = f"workspaces/{snapshot.workspace_id}/analysis-planning/{new_ulid()}"
    checked: dict[str, dict[str, Any]] = {}
    validations = 0
    modules = []
    with tempfile.TemporaryDirectory(
        prefix="resolution-plan-", dir=core.settings.task_tmp_root
    ) as temporary:
        for module in snapshot.modules:
            active: set[str] = set()
            unavailable: set[str] = set()
            observations = []
            incomplete = not module.enumeration_complete
            reason = module.enumeration_reason
            unavailable_reasons = set()
            for pair_id in module.pair_ids:
                if pair_id not in checked:
                    pair = snapshot.pairs[pair_id]
                    needs_validation = (
                        pair.state == "active"
                        and not pair.error
                        and pair.pe
                        and pair.pdb
                        and pair.pe.locations
                        and pair.pdb.locations
                    )
                    if needs_validation and validations >= snapshot.limits.validations:
                        checked[pair_id] = {
                            "pair_id": pair_id,
                            "validation": "pending",
                            "error": "PLANNER_VALIDATION_BUDGET_EXHAUSTED",
                            "failure_class": "unknown",
                        }
                    else:
                        if needs_validation:
                            validations += 1
                        checked[pair_id] = _validate(core, store, pair, Path(temporary))
                observation = checked[pair_id]
                observations.append(observation)
                if observation["validation"] == "pending":
                    incomplete = True
                    reason = reason or "validation_incomplete"
                elif observation["validation"] == "verified":
                    if observation["availability"] == "active":
                        active.add(pair_id)
                    else:
                        unavailable.add(pair_id)
                        unavailable_reasons.add(observation["availability"])
            state = (
                "indeterminate"
                if incomplete
                else "conflict"
                if len(active) > 1
                else "unique"
                if active
                else "unavailable"
                if unavailable
                else "none"
            )
            if not incomplete:
                reason = {
                    "conflict": "identity_conflict",
                    "unique": "unique",
                    "none": "missing",
                    "unavailable": "location_unavailable"
                    if "location_unavailable" in unavailable_reasons
                    else "withdrawn",
                }[state]
            receipt_key = f"{prefix}/module-{module.module_index}.json"
            _, receipt_sha = _retain(
                store,
                receipt_key,
                {
                    "schema_version": "resolution-candidate-evidence-v1",
                    "module_index": module.module_index,
                    "identity": module.identity,
                    "catalog_revision": snapshot.catalog_revision,
                    "enumeration_complete": module.enumeration_complete,
                    "enumeration_reason": module.enumeration_reason,
                    "validator_version": validator,
                    "inspector_provenance": snapshot.inspector_provenance,
                    "limits": asdict(snapshot.limits),
                    "candidates": observations,
                },
            )
            selection = {
                "module_index": module.module_index,
                "identity": module.identity,
                "state": state,
                "candidates_complete": not incomplete,
                "candidate_pair_ids": sorted(active),
                "unavailable_pair_ids": sorted(unavailable),
                "selected_pair_id": next(iter(active)) if state == "unique" else None,
                "reason": reason,
                "candidate_evidence": {"object_key": receipt_key, "sha256": receipt_sha},
                "review_refs": sorted(
                    {r["id"] for p in module.pair_ids for r in snapshot.pairs[p].reviews}
                ),
            }
            verify_selection(selection)
            modules.append(selection)
    if catalog_validator_version(core) != validator:
        raise CoreExecutionError("PLANNER_VALIDATOR_CHANGED", "Validator changed during planning")
    manifest = {
        "schema_version": "resolution-manifest-v1",
        "dump_sha256": snapshot.dump_sha256,
        "inspector_version": snapshot.inspector_version,
        "inspect_sha256": snapshot.inspect_sha256,
        "selection_version": "pair-selection-v1",
        "catalog_revision": snapshot.catalog_revision,
        "modules": modules,
    }
    key = prefix + "/resolution-manifest.json"
    data, sha = _retain(store, key, manifest)
    return PreparedResolution(
        snapshot.demand_id,
        snapshot.change_sequence,
        snapshot.inspection_id,
        manifest,
        data,
        key,
        sha,
        resolution_fingerprint(manifest),
        validator,
    )
