"""Freeze consumer Workspace role/source metadata without reading remote objects.

Role declarations from the QA report and atomic policy adoption are separate
integration steps. This module consumes existing verified local Build evidence
and existing Workspace in-app overrides; it never imports provider roles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..contracts import load_validator
from ..frozen_inputs import canonical_bytes, normalize_identity, verify_public_sources
from ..in_app import is_system_module, module_basename
from ..models import Artifact, Build, Workspace, WorkspaceModuleRole
from .analysis_demands import require
from .workspace_builds import WorkspaceBuildSnapshot


@dataclass(frozen=True)
class WorkspacePolicySnapshot:
    workspace_id: str
    in_app_rule_version: int
    module_role_version: int
    rules: bytes
    declarations: bytes
    bundles: bytes


@dataclass(frozen=True)
class ModuleRoleDeclaration:
    version: int
    identity: dict[str, Any]
    role: str
    changed: bool


def declare_workspace_module_role(
    session: Session,
    workspace_id: str,
    identity: dict[str, Any],
    role: str,
    *,
    now: datetime,
) -> ModuleRoleDeclaration:
    """Append one serialized exact-identity declaration; identical retries are no-ops."""
    normalized = normalize_identity(identity)
    require(
        normalized["code_id"] is not None
        and normalized["debug_id"] is not None
        and normalized["architecture"] == "x86_64",
        "WORKSPACE_ROLE_EXACT_IDENTITY_REQUIRED",
    )
    require(role in {"owned", "dependency"}, "WORKSPACE_ROLE_INVALID")
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    )
    require(workspace is not None, "WORKSPACE_NOT_FOUND")
    assert workspace is not None
    current = session.scalar(
        select(WorkspaceModuleRole)
        .where(
            WorkspaceModuleRole.workspace_id == workspace_id,
            WorkspaceModuleRole.code_id == normalized["code_id"],
            WorkspaceModuleRole.debug_id == normalized["debug_id"],
            WorkspaceModuleRole.architecture == normalized["architecture"],
        )
        .order_by(WorkspaceModuleRole.version.desc())
        .limit(1)
    )
    if current is not None and current.role == role:
        return ModuleRoleDeclaration(current.version, normalized, role, False)
    workspace.module_role_version += 1
    session.add(
        WorkspaceModuleRole(
            workspace_id=workspace_id,
            version=workspace.module_role_version,
            code_id=normalized["code_id"],
            debug_id=normalized["debug_id"],
            architecture=normalized["architecture"],
            role=role,
            created_at=now,
        )
    )
    session.flush()
    return ModuleRoleDeclaration(workspace.module_role_version, normalized, role, True)


def snapshot_workspace_policies(
    session: Session, builds: WorkspaceBuildSnapshot, *, bundle_limit: int = 200
) -> WorkspacePolicySnapshot:
    """Detached metadata from local verified source artifacts; no global origins."""
    require(0 < bundle_limit <= 2000, "WORKSPACE_SOURCE_BUNDLE_LIMIT_INVALID")
    # Keep the version counter and effective append-only rows in one coherent
    # snapshot while a concurrent declaration takes the exclusive row lock.
    workspace = session.scalar(
        select(Workspace)
        .where(Workspace.id == builds.workspace_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    require(workspace is not None, "WORKSPACE_NOT_FOUND")
    assert workspace is not None
    local = {row["build_id"]: row for row in json.loads(builds.metadata)}
    artifacts = list(
        session.scalars(
            select(Artifact)
            .join(Build, Artifact.build_id == Build.id)
            .where(
                Build.workspace_id == builds.workspace_id,
                Build.id.in_(local),
                Artifact.kind == "source_bundle",
                Artifact.verification_status == "verified",
            )
            .order_by(Artifact.id)
            .limit(bundle_limit + 1)
            .execution_options(populate_existing=True)
        )
    )
    require(len(artifacts) <= bundle_limit, "WORKSPACE_SOURCE_ENUMERATION_INCOMPLETE")
    latest = (
        select(
            WorkspaceModuleRole.code_id,
            WorkspaceModuleRole.debug_id,
            WorkspaceModuleRole.architecture,
            func.max(WorkspaceModuleRole.version).label("version"),
        )
        .where(WorkspaceModuleRole.workspace_id == builds.workspace_id)
        .group_by(
            WorkspaceModuleRole.code_id,
            WorkspaceModuleRole.debug_id,
            WorkspaceModuleRole.architecture,
        )
        .subquery()
    )
    declarations = list(
        session.scalars(
            select(WorkspaceModuleRole)
            .join(
                latest,
                and_(
                    WorkspaceModuleRole.code_id == latest.c.code_id,
                    WorkspaceModuleRole.debug_id == latest.c.debug_id,
                    WorkspaceModuleRole.architecture == latest.c.architecture,
                    WorkspaceModuleRole.version == latest.c.version,
                ),
            )
            .where(WorkspaceModuleRole.workspace_id == builds.workspace_id)
            .order_by(
                WorkspaceModuleRole.code_id,
                WorkspaceModuleRole.debug_id,
                WorkspaceModuleRole.architecture,
            )
            .limit(2001)
        )
    )
    require(len(declarations) <= 2000, "WORKSPACE_ROLE_ENUMERATION_INCOMPLETE")
    bundles = []
    contents: dict[str, tuple[str, int]] = {}
    for artifact in artifacts:
        descriptor = local[artifact.build_id]["source_bundle_config"]
        require(
            isinstance(descriptor, dict)
            and isinstance(descriptor.get("archive"), str)
            and descriptor["archive"].casefold() == artifact.logical_name.casefold()
            and artifact.module_id is None
            and artifact.size > 0,
            "WORKSPACE_SOURCE_DESCRIPTOR_MISMATCH",
        )
        content = (artifact.sha256.lower(), artifact.size)
        require(
            artifact.build_id not in contents or contents[artifact.build_id] == content,
            "WORKSPACE_SOURCE_BUNDLE_CONFLICT",
        )
        contents[artifact.build_id] = content
        bundles.append(
            {
                "build_id": artifact.build_id,
                "artifact_id": artifact.id,
                "sha256": artifact.sha256.lower(),
                "size": artifact.size,
                "descriptor": descriptor,
                "object_key": artifact.object_key,
            }
        )
    return WorkspacePolicySnapshot(
        builds.workspace_id,
        workspace.in_app_rule_version,
        workspace.module_role_version,
        canonical_bytes(workspace.in_app_rules),
        canonical_bytes(
            [
                {
                    "identity": {
                        "code_id": row.code_id,
                        "debug_id": row.debug_id,
                        "architecture": row.architecture,
                    },
                    "role": row.role,
                }
                for row in declarations
            ]
        ),
        canonical_bytes(bundles),
    )


def prepare_workspace_policies(
    snapshot: WorkspacePolicySnapshot,
    build_policy: dict[str, Any],
    inspect: dict[str, Any],
    *,
    public_sources: list[dict[str, Any]],
    schema_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Produce policies and physical source locations as separate values.

    `public_sources` must come from deployment configuration, never a request body.
    Known local role conflicts fail explicitly instead of choosing the newest Build.
    Physical source locations and rule counters do not enter semantic policy hashes.
    """
    builds = build_policy["builds"]
    require(
        all(row["workspace_id"] == snapshot.workspace_id for row in builds),
        "WORKSPACE_POLICY_BUILD_OUTSIDE_SCOPE",
    )
    rules = json.loads(snapshot.rules)
    require(
        isinstance(rules, dict)
        and set(rules) <= {"include_modules", "exclude_modules"}
        and all(
            isinstance(rules.get(key, []), list)
            and all(isinstance(item, str) for item in rules.get(key, []))
            for key in ("include_modules", "exclude_modules")
        ),
        "WORKSPACE_IN_APP_RULES_INVALID",
    )
    included = {value.casefold() for value in rules.get("include_modules", [])}
    excluded = {value.casefold() for value in rules.get("exclude_modules", [])}
    declared = {
        canonical_bytes(normalize_identity(row["identity"])): row["role"]
        for row in json.loads(snapshot.declarations)
    }
    known: dict[bytes, set[str]] = {}
    for build in builds:
        for module in build["verified_modules"]:
            if module["verified_pair_ids"]:
                key = canonical_bytes(normalize_identity(module["identity"]))
                known.setdefault(key, set()).add(module["role"])
    roles = []
    for index, module in enumerate(inspect["modules"]):
        identity = normalize_identity(
            {**module, "architecture": inspect["process"]["architecture"]}
        )
        code_file = module.get("code_file") or ""
        name = module_basename(code_file)
        candidates = known.get(canonical_bytes(identity), set())
        if is_system_module(code_file):
            role = "system"
        elif canonical_bytes(identity) in declared:
            role = declared[canonical_bytes(identity)]
        elif name in excluded:
            role = "dependency"
        elif name in included:
            role = "entrypoint" if candidates == {"entrypoint"} else "owned"
        else:
            require(len(candidates) <= 1, "WORKSPACE_ROLE_AMBIGUOUS")
            role = next(iter(candidates), "unknown")
        roles.append(
            {
                "module_index": index,
                "identity": identity,
                "role": role,
                "in_app": role in {"entrypoint", "owned"},
            }
        )
    bundles = json.loads(snapshot.bundles)
    build_by_id = {row["build_id"]: row for row in builds}
    for bundle in bundles:
        require(
            bundle["build_id"] in build_by_id
            and build_by_id[bundle["build_id"]]["manifest"].get("source_bundle")
            == bundle["descriptor"],
            "WORKSPACE_SOURCE_POLICY_BUILD_MISMATCH",
        )
    policy = {
        "build_snapshot": build_policy,
        "role_policy": {"schema_version": "workspace-role-policy-v1", "modules": roles},
        "source_policy": {
            "schema_version": "frozen-source-policy-v1",
            "pair_source_protocol": "pair-http-v2",
            "public_sources": public_sources,
            "bundles": [
                {key: value for key, value in item.items() if key != "object_key"}
                for item in bundles
            ],
        },
    }
    # Validate the complete policy shape against the same package the Core consumes.
    validator = load_validator(str((schema_root / "analysis-run-v2.schema.json").resolve()))
    schema = validator.schema
    assert isinstance(schema, dict)
    require(
        not list(validator.descend(policy, schema["properties"]["policy_snapshots"])),
        "WORKSPACE_POLICY_SCHEMA_INVALID",
    )
    verify_public_sources(public_sources)
    locations = [
        {
            "artifact_id": row["artifact_id"],
            "content": {"object_key": row["object_key"], "sha256": row["sha256"]},
        }
        for row in bundles
    ]
    return policy, locations
