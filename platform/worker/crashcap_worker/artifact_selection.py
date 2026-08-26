from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from crashcap_api.canonical_semantics import canonical_json_bytes

ARTIFACT_SELECTION_VERSION = "artifact-selection-v1"


class ArtifactSelectionError(RuntimeError):
    """A deterministic selection checkpoint could not be validated."""


def plan_artifact_selection(
    run_spec: dict[str, Any],
    inspect: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    """Select a conservative artifact superset without claiming Build Resolution."""

    artifacts = [dict(item) for item in run_spec.get("artifacts", [])]
    builds = [dict(item) for item in run_spec.get("builds", [])]
    dump_modules = [
        module for module in inspect.get("modules", []) if isinstance(module, dict)
    ]

    matched_module_ids: set[str] = set()
    reported_build_id = str(run_spec.get("reported_build_id") or "")
    candidate_build_ids: set[str] = {reported_build_id} if reported_build_id else set()
    module_reasons: dict[str, set[str]] = {}
    for build in builds:
        build_id = str(build.get("build_id") or "")
        for module in build.get("modules", []):
            if not isinstance(module, dict):
                continue
            reasons = _matching_reasons(module, dump_modules)
            module_id = str(module.get("module_id") or "")
            if not reasons or not module_id:
                continue
            matched_module_ids.add(module_id)
            module_reasons.setdefault(module_id, set()).update(reasons)
            if build_id:
                candidate_build_ids.add(build_id)

    # Legacy Artifacts may not have a BuildModule binding. Keep exact identity
    # matches useful without falling back to filenames or Version labels.
    directly_matched_artifact_ids: set[str] = set()
    direct_reasons: dict[str, set[str]] = {}
    for artifact in artifacts:
        if artifact.get("kind") not in {"pe", "pdb"}:
            continue
        artifact_id = str(artifact.get("artifact_id") or "")
        reasons = _matching_reasons(artifact, dump_modules)
        if not reasons or not artifact_id:
            continue
        directly_matched_artifact_ids.add(artifact_id)
        direct_reasons.setdefault(artifact_id, set()).update(reasons)
        build_id = str(artifact.get("build_id") or "")
        if build_id:
            candidate_build_ids.add(build_id)

    selected: list[dict[str, Any]] = []
    for artifact in artifacts:
        artifact_id = str(artifact.get("artifact_id") or "")
        module_id = str(artifact.get("module_id") or "")
        build_id = str(artifact.get("build_id") or "")
        kind = str(artifact.get("kind") or "")
        selection_reasons: set[str] = set()
        if kind in {"pe", "pdb"}:
            if reported_build_id and build_id == reported_build_id:
                selection_reasons.add("reported_build")
            if module_id in matched_module_ids:
                selection_reasons.update(module_reasons.get(module_id, ()))
                if not _matching_reasons(artifact, dump_modules):
                    selection_reasons.add("paired_artifact")
            if artifact_id in directly_matched_artifact_ids:
                selection_reasons.update(direct_reasons.get(artifact_id, ()))
        elif kind == "source_bundle" and build_id in candidate_build_ids:
            selection_reasons.add("candidate_source_bundle")
        if not selection_reasons:
            continue
        selected.append(_selection_artifact(artifact, selection_reasons))

    selected.sort(key=lambda item: (item["artifact_id"], item["kind"]))
    inventory_summary = _summary(artifacts)
    selection_summary = _summary(selected)
    inspect_sha256 = hashlib.sha256(canonical_json_bytes(inspect)).hexdigest()
    return {
        "schema_version": ARTIFACT_SELECTION_VERSION,
        "policy_version": ARTIFACT_SELECTION_VERSION,
        "mode": mode,
        "workspace_id": str(run_spec["workspace_id"]),
        "run_id": str(run_spec["run_id"]),
        "inspect_sha256": inspect_sha256,
        "reported_build_id": run_spec.get("reported_build_id"),
        "candidate_build_ids": sorted(candidate_build_ids),
        "matched_module_ids": sorted(matched_module_ids),
        "selected_artifacts": selected,
        "inventory_summary": inventory_summary,
        "selection_summary": selection_summary,
        "materialization_summary": selection_summary,
    }


def selected_artifacts(
    run_spec: dict[str, Any], selection: dict[str, Any], *, mode: str
) -> list[dict[str, Any]]:
    artifacts = [dict(item) for item in run_spec.get("artifacts", [])]
    if mode in {"legacy", "shadow"}:
        return artifacts
    selected_ids = {
        str(item["artifact_id"])
        for item in selection.get("selected_artifacts", [])
        if item.get("artifact_id")
    }
    return [item for item in artifacts if str(item.get("artifact_id") or "") in selected_ids]


def materialization_summary(artifacts: Iterable[dict[str, Any]]) -> dict[str, int]:
    return _summary(list(artifacts))


def _matching_reasons(
    candidate: dict[str, Any], dump_modules: list[dict[str, Any]]
) -> set[str]:
    code_id = _identity(candidate.get("code_id"))
    debug_id = _identity(candidate.get("debug_id"))
    reasons: set[str] = set()
    for module in dump_modules:
        if code_id and code_id == _identity(module.get("code_id")):
            reasons.add("code_id")
        if debug_id and debug_id == _identity(module.get("debug_id")):
            reasons.add("debug_id")
    return reasons


def _identity(value: object) -> str | None:
    return value.casefold() if isinstance(value, str) and value else None


def _selection_artifact(artifact: dict[str, Any], reasons: set[str]) -> dict[str, Any]:
    return {
        "artifact_id": str(artifact["artifact_id"]),
        "build_id": str(artifact["build_id"]),
        "module_id": artifact.get("module_id"),
        "kind": str(artifact["kind"]),
        "sha256": str(artifact["sha256"]).lower(),
        "size": int(artifact["size"]),
        "object_key": str(artifact["object_key"]),
        "selection_reasons": sorted(reasons),
    }


def _summary(artifacts: list[dict[str, Any]]) -> dict[str, int]:
    unique: dict[str, int] = {}
    total_bytes = 0
    for artifact in artifacts:
        size = int(artifact.get("size") or 0)
        total_bytes += size
        blob_identity = str(
            artifact.get("sha256")
            or artifact.get("object_key")
            or artifact.get("artifact_id")
            or ""
        ).lower()
        if blob_identity:
            unique.setdefault(blob_identity, size)
    return {
        "artifact_count": len(artifacts),
        "artifact_bytes": total_bytes,
        "unique_blob_count": len(unique),
        "unique_blob_bytes": sum(unique.values()),
    }
