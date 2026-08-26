from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import Any, cast

from .models import AnalysisRun, DumpBlob, Occurrence

ANALYSIS_CONTEXT_VERSION = "analysis-context-v1"
SOURCE_BUNDLE_POLICY_VERSION = "source-bundle-v1.0"


class CanonicalSemanticError(ValueError):
    """The schema-valid Canonical result contradicts immutable Run facts."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def freeze_analysis_context(
    run: AnalysisRun,
    occurrence: Occurrence,
    blob: DumpBlob,
    inspect: dict[str, Any],
    inspect_object_key: str,
    artifact_selection: dict[str, Any] | None = None,
    artifact_selection_object_key: str | None = None,
    materialized_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Freeze every platform-owned fact consumed while assembling Canonical v1."""

    artifacts = [
        {
            key: artifact.get(key)
            for key in (
                "artifact_id",
                "build_id",
                "kind",
                "logical_name",
                "sha256",
                "size",
                "object_key",
                "ingest_metadata",
                "source_bundle_config",
            )
        }
        for artifact in run.run_spec.get("artifacts", [])
    ]
    effective_artifacts = (
        materialized_artifacts if materialized_artifacts is not None else artifacts
    )
    source_bundles = [
        artifact for artifact in effective_artifacts if artifact.get("kind") == "source_bundle"
    ]
    build_ids = sorted(
        str(build["build_id"]) for build in run.run_spec.get("builds", []) if build.get("build_id")
    )
    return {
        "schema_version": ANALYSIS_CONTEXT_VERSION,
        "identity": {
            "workspace_id": occurrence.workspace_id,
            "occurrence_id": occurrence.id,
            "analysis_id": run.id,
        },
        "dump": {
            "blob_id": blob.id,
            "sha256": blob.sha256.lower(),
            "kind": blob.dump_kind,
            "size": blob.size,
            "dump_timestamp": _iso(occurrence.dump_timestamp),
            "reported_at": _iso(occurrence.reported_at),
            "uploaded_at": _iso(occurrence.uploaded_at),
            "occurred_at": _iso(occurrence.occurred_at),
            "time_source": occurrence.time_source,
        },
        "engine": {
            "core_image_digest": run.core_image_digest,
            "symbolicator_version": run.symbolicator_version,
            "grouping_version": run.grouping_version,
            "normalization_version": run.normalization_version,
        },
        "policy": {
            "symbol_inventory_version": run.symbol_inventory_version,
            "in_app_rule_version": run.run_spec.get("in_app_rule_version", 0),
            "source_bundle_policy_version": SOURCE_BUNDLE_POLICY_VERSION,
            "artifact_selection_version": run.run_spec.get(
                "artifact_selection_version", "artifact-selection-legacy"
            ),
        },
        "inspect": {
            "object_key": inspect_object_key,
            "sha256": hashlib.sha256(canonical_json_bytes(inspect)).hexdigest(),
        },
        "inputs": {
            "artifact_ids": [
                str(artifact["artifact_id"])
                for artifact in effective_artifacts
                if artifact.get("artifact_id")
            ],
            "inventory_artifact_ids": [
                str(artifact["artifact_id"])
                for artifact in artifacts
                if artifact.get("artifact_id")
            ],
            "build_ids": build_ids,
            "source_bundles": source_bundles,
            "artifact_selection": {
                "object_key": artifact_selection_object_key,
                "sha256": hashlib.sha256(canonical_json_bytes(artifact_selection)).hexdigest()
                if artifact_selection is not None
                else None,
                "mode": artifact_selection.get("mode")
                if artifact_selection is not None
                else None,
                "policy_version": artifact_selection.get("policy_version")
                if artifact_selection is not None
                else None,
                "candidate_build_ids": artifact_selection.get("candidate_build_ids")
                if artifact_selection is not None
                else None,
                "inventory_summary": artifact_selection.get("inventory_summary")
                if artifact_selection is not None
                else None,
                "selection_summary": artifact_selection.get("selection_summary")
                if artifact_selection is not None
                else None,
                "materialization_summary": artifact_selection.get("materialization_summary")
                if artifact_selection is not None
                else None,
            },
        },
    }


def validate_canonical_semantics(
    canonical: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """Validate facts that JSON Schema cannot relate to the immutable Run."""

    if context.get("schema_version") != ANALYSIS_CONTEXT_VERSION:
        raise CanonicalSemanticError("unsupported analysis context version")
    identity = _mapping(context, "identity")
    dump = _mapping(context, "dump")
    engine = _mapping(context, "engine")
    expected = {
        "schema_version": "1.0",
        "workspace_id": identity.get("workspace_id"),
        "occurrence_id": identity.get("occurrence_id"),
        "analysis_id": identity.get("analysis_id"),
    }
    for field, value in expected.items():
        if canonical.get(field) != value:
            raise CanonicalSemanticError(
                f"Canonical {field} does not match immutable analysis context"
            )

    canonical_dump = _mapping(canonical, "dump")
    for field in (
        "blob_id",
        "sha256",
        "kind",
        "size",
        "dump_timestamp",
        "reported_at",
        "uploaded_at",
        "occurred_at",
        "time_source",
    ):
        actual = canonical_dump.get(field)
        expected_value = dump.get(field)
        if field == "sha256" and isinstance(actual, str):
            actual = actual.lower()
        if actual != expected_value:
            raise CanonicalSemanticError(
                f"Canonical dump.{field} does not match immutable analysis context"
            )

    canonical_engine = _mapping(canonical, "engine")
    for field in (
        "core_image_digest",
        "symbolicator_version",
        "grouping_version",
        "normalization_version",
    ):
        if canonical_engine.get(field) != engine.get(field):
            raise CanonicalSemanticError(
                f"Canonical engine.{field} does not match immutable analysis context"
            )

    build_resolution = _mapping(canonical, "build_resolution")
    resolved_build_id = build_resolution.get("resolved_build_id")
    build_ids = set(_mapping(context, "inputs").get("build_ids") or [])
    if resolved_build_id is not None and resolved_build_id not in build_ids:
        raise CanonicalSemanticError("Canonical resolved Build is outside the frozen Run inputs")
    fingerprints = _mapping(canonical, "fingerprints")
    if fingerprints.get("algorithm") != "exact-v1.0":
        raise CanonicalSemanticError(
            "Canonical fingerprint algorithm is not the frozen v1 algorithm"
        )


def bind_legacy_canonical(canonical: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Rollback adapter for old Core output; never used by the core-final path."""

    result = cast(dict[str, Any], json.loads(json.dumps(canonical)))
    identity = _mapping(context, "identity")
    dump = _mapping(context, "dump")
    engine = _mapping(context, "engine")
    result["schema_version"] = "1.0"
    result["workspace_id"] = identity["workspace_id"]
    result["occurrence_id"] = identity["occurrence_id"]
    result["analysis_id"] = identity["analysis_id"]
    result_dump = _mapping(result, "dump")
    result_dump.update(dump)
    result_engine = _mapping(result, "engine")
    result_engine.update(engine)
    return result


def canonical_parity_differences(legacy: dict[str, Any], core_final: dict[str, Any]) -> list[str]:
    """Return deterministic JSON-pointer-like paths for shadow parity failures."""

    differences: list[str] = []
    _compare("", legacy, core_final, differences)
    return differences


def _compare(path: str, left: Any, right: Any, differences: list[str]) -> None:
    if type(left) is not type(right):
        differences.append(path or "/")
        return
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in left or key not in right:
                differences.append(child)
            else:
                _compare(child, left[key], right[key], differences)
        return
    if isinstance(left, list):
        if len(left) != len(right):
            differences.append(path or "/")
            return
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            _compare(f"{path}/{index}", left_item, right_item, differences)
        return
    if left != right:
        differences.append(path or "/")


def _mapping(value: dict[str, Any], key: str) -> dict[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, dict):
        raise CanonicalSemanticError(f"Canonical semantic object {key} is missing")
    return nested


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return str(value.astimezone(UTC).isoformat())
