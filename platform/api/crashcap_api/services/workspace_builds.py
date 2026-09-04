"""Consumer-owned Build evidence for frozen planning, without object I/O.

Catalog origins never establish Build ownership. The only bridge to a global pair
is the raw content of verified PE/PDB Artifacts belonging to the same local module.
This is preparation only; the caller must fence/recheck before adopting a Run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..contracts import load_validator
from ..frozen_inputs import canonical_bytes, digest, normalize_identity
from ..models import Artifact, Build, BuildModule, CatalogPair
from .analysis_demands import require


@dataclass(frozen=True)
class WorkspaceBuildLimits:
    artifacts: int = 20000
    modules: int = 10000
    pair_checks: int = 2000
    manifest_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        require(
            all(0 < value <= 100000 for value in (self.artifacts, self.modules, self.pair_checks))
            and 0 < self.manifest_bytes <= 16 * 1024 * 1024,
            "WORKSPACE_BUILD_LIMIT_INVALID",
        )


@dataclass(frozen=True)
class WorkspaceBuildSnapshot:
    workspace_id: str
    reported_build_id: str | None
    # Canonical bytes detach the snapshot from mutable ORM/JSON objects.
    metadata: bytes
    limits: WorkspaceBuildLimits


def _identity(row: Artifact) -> dict[str, Any]:
    return normalize_identity(
        {"code_id": row.code_id, "debug_id": row.debug_id, "architecture": "x86_64"}
    )


def snapshot_workspace_builds(
    session: Session,
    workspace_id: str,
    captured: list[dict[str, Any]],
    *,
    reported_build_id: str | None = None,
    limits: WorkspaceBuildLimits | None = None,
) -> WorkspaceBuildSnapshot:
    """Read bounded local evidence. Exhaustion cannot become an empty/unique set.

    The stored Artifact IDs have already been extracted by verification. Filenames,
    Build versions, producer hints and global pair origins are not matching inputs.
    Unrelated local Builds are excluded from the resulting semantic snapshot.
    """
    limits = limits or WorkspaceBuildLimits()
    identities = [normalize_identity(item) for item in captured]
    artifacts = list(
        session.scalars(
            select(Artifact)
            .join(Build, Artifact.build_id == Build.id)
            .where(Build.workspace_id == workspace_id, Artifact.verification_status == "verified")
            .order_by(Artifact.id)
            .limit(limits.artifacts + 1)
            .execution_options(populate_existing=True)
        )
    )
    require(len(artifacts) <= limits.artifacts, "WORKSPACE_ARTIFACT_ENUMERATION_INCOMPLETE")
    build_ids = {
        row.build_id
        for row in artifacts
        if row.kind == "pe"
        and row.code_id is not None
        and row.debug_id is not None
        and _identity(row) in identities
    }
    if reported_build_id is not None:
        reported = session.scalar(
            select(Build.id).where(
                Build.id == reported_build_id, Build.workspace_id == workspace_id
            )
        )
        require(reported is not None, "WORKSPACE_REPORTED_BUILD_OUTSIDE_SCOPE")
        build_ids.add(reported_build_id)
    builds = list(
        session.scalars(
            select(Build)
            .where(Build.id.in_(build_ids), Build.workspace_id == workspace_id)
            .order_by(Build.id)
            .execution_options(populate_existing=True)
        )
    )
    modules = list(
        session.scalars(
            select(BuildModule)
            .where(BuildModule.build_id.in_(build_ids))
            .order_by(BuildModule.id)
            .limit(limits.modules + 1)
            .execution_options(populate_existing=True)
        )
    )
    require(len(modules) <= limits.modules, "WORKSPACE_MODULE_ENUMERATION_INCOMPLETE")
    module_ids = {(row.build_id, row.id) for row in modules}
    for artifact in artifacts:
        if artifact.build_id in build_ids and artifact.kind in {"pe", "pdb"}:
            require(
                (artifact.build_id, artifact.module_id) in module_ids,
                "WORKSPACE_ARTIFACT_MODULE_MISMATCH",
            )
    checks = 0
    result = []
    for build in builds:
        require(build.manifest_object_key is not None, "WORKSPACE_BUILD_MANIFEST_MISSING")
        verified = []
        for module in (row for row in modules if row.build_id == build.id):
            local = [
                row for row in artifacts if row.build_id == build.id and row.module_id == module.id
            ]
            pes = [row for row in local if row.kind == "pe"]
            pdbs = [row for row in local if row.kind == "pdb"]
            pairs: dict[str, dict[str, Any]] = {}
            used_artifacts: set[str] = set()
            compatible_identities: set[bytes] = set()
            for pe in pes:
                for pdb in pdbs:
                    checks += 1
                    require(checks <= limits.pair_checks, "WORKSPACE_PAIR_ENUMERATION_INCOMPLETE")
                    pe_identity = _identity(pe)
                    pdb_identity = _identity(pdb)
                    if (
                        pe_identity["debug_id"] is None
                        or pe_identity["debug_id"] != pdb_identity["debug_id"]
                    ):
                        continue
                    compatible_identities.add(canonical_bytes(pe_identity))
                    pair_id = digest(["pair-v1", pe.sha256.lower(), pdb.sha256.lower()])
                    pair = session.get(CatalogPair, pair_id, populate_existing=True)
                    if pair is None:
                        continue
                    require(
                        pair.pe_file_id == digest(["catalog-file-v1", "pe", pe.sha256.lower()])
                        and pair.pdb_file_id
                        == digest(["catalog-file-v1", "pdb", pdb.sha256.lower()]),
                        "WORKSPACE_PAIR_CONTENT_MISMATCH",
                    )
                    actual = normalize_identity(
                        {
                            "code_id": pair.code_id,
                            "debug_id": pair.debug_id,
                            "architecture": pair.architecture,
                        }
                    )
                    require(actual == pe_identity, "WORKSPACE_PAIR_IDENTITY_MISMATCH")
                    # Logical withdrawal affects symbol selection, not the local Build's history.
                    pairs[pair.id] = actual
                    used_artifacts.update((pe.id, pdb.id))
            actual_identities = {canonical_bytes(value) for value in pairs.values()}
            require(
                compatible_identities <= actual_identities,
                "WORKSPACE_PAIR_BACKFILL_REQUIRED",
            )
            require(len(actual_identities) <= 1, "WORKSPACE_MODULE_IDENTITY_AMBIGUOUS")
            identity = (
                json.loads(next(iter(actual_identities)))
                if actual_identities
                else {"code_id": None, "debug_id": None, "architecture": build.architecture}
            )
            verified.append(
                {
                    "module_id": module.id,
                    "code_file": module.code_file,
                    "debug_file": module.debug_file,
                    "role": module.role,
                    "identity": identity,
                    "verified_pair_ids": sorted(pairs),
                    "artifact_ids": sorted(used_artifacts),
                }
            )
        result.append(
            {
                "build_id": build.id,
                "workspace_id": workspace_id,
                "manifest_object_key": build.manifest_object_key,
                "manifest_schema_version": build.manifest_schema_version,
                "architecture": build.architecture,
                "version": build.version,
                "source_bundle_config": build.source_bundle_config,
                "verified_modules": verified,
            }
        )
    return WorkspaceBuildSnapshot(workspace_id, reported_build_id, canonical_bytes(result), limits)


def prepare_build_policy(
    snapshot: WorkspaceBuildSnapshot,
    manifests: dict[str, bytes],
    *,
    schema_root: Path,
) -> dict[str, Any]:
    """Bind complete fetched manifests to local declarations outside DB transactions.

    The returned manifest is embedded and content-addressed, never lazily reread by
    Core. Object acquisition/retention and atomic adoption belong to the caller.
    """
    result = []
    for build in json.loads(snapshot.metadata):
        data = manifests.get(build["build_id"])
        require(data is not None, "WORKSPACE_BUILD_MANIFEST_MISSING")
        assert data is not None
        require(len(data) <= snapshot.limits.manifest_bytes, "WORKSPACE_MANIFEST_SIZE_LIMIT")

        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                require(key not in value, "WORKSPACE_MANIFEST_DUPLICATE_KEY")
                value[key] = item
            return value

        manifest = json.loads(data, object_pairs_hook=unique)
        version = build["manifest_schema_version"]
        require(version in {"0.1", "1.0", "2.0"}, "WORKSPACE_MANIFEST_VERSION_UNSUPPORTED")
        name = {"0.1": "v0", "1.0": "v1", "2.0": "v2"}[version]
        validator = load_validator(
            str((schema_root / f"build-manifest-{name}.schema.json").resolve())
        )
        require(validator.is_valid(manifest), "WORKSPACE_MANIFEST_SCHEMA_INVALID")
        require(
            manifest["architecture"] == build["architecture"]
            and manifest["version"] == build["version"]
            and manifest.get("source_bundle") == build["source_bundle_config"],
            "WORKSPACE_MANIFEST_METADATA_MISMATCH",
        )
        declarations = manifest["modules"]
        bindings = {
            (row["code_file"], row["debug_file"], row["role"]): index
            for index, row in enumerate(declarations)
        }
        require(len(bindings) == len(declarations), "WORKSPACE_MANIFEST_BINDING_AMBIGUOUS")
        local = build["verified_modules"]
        require(
            set(bindings) == {(row["code_file"], row["debug_file"], row["role"]) for row in local}
            and len(local) == len(declarations),
            "WORKSPACE_MANIFEST_MODULE_MISMATCH",
        )
        verified = []
        for row in local:
            verified.append(
                {
                    "module_id": row["module_id"],
                    "manifest_module_index": bindings[
                        (row["code_file"], row["debug_file"], row["role"])
                    ],
                    "role": row["role"],
                    "identity": row["identity"],
                    "verified_pair_ids": row["verified_pair_ids"],
                    "artifact_ids": row["artifact_ids"],
                }
            )
        result.append(
            {
                "build_id": build["build_id"],
                "workspace_id": snapshot.workspace_id,
                "manifest_sha256": digest(manifest),
                "manifest": manifest,
                "verified_modules": verified,
            }
        )
    return {"schema_version": "frozen-builds-v1", "builds": result}
