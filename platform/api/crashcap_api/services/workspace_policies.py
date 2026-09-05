"""Freeze consumer classification independently of uploads' version labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..contracts import load_validator
from ..frozen_inputs import canonical_bytes, normalize_identity, verify_public_sources
from ..in_app import is_system_module, module_basename
from ..models import ArtifactEntry, CatalogFile, Workspace, WorkspaceModuleRole
from .analysis_demands import require


@dataclass(frozen=True)
class WorkspacePolicySnapshot:
    workspace_id: str
    in_app_rule_version: int
    module_role_version: int
    rules: bytes
    declarations: bytes
    defaults: bytes


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
    session: Session,
    workspace_id: str,
    identities: list[dict[str, Any]],
) -> WorkspacePolicySnapshot:
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update(read=True)
    )
    require(workspace is not None, "WORKSPACE_NOT_FOUND")
    assert workspace is not None
    captured = {canonical_bytes(normalize_identity(i)): normalize_identity(i) for i in identities}
    declarations = {}
    for row in session.scalars(
        select(WorkspaceModuleRole)
        .where(WorkspaceModuleRole.workspace_id == workspace_id)
        .order_by(WorkspaceModuleRole.version)
    ):
        identity = {
            "code_id": row.code_id,
            "debug_id": row.debug_id,
            "architecture": row.architecture,
        }
        if canonical_bytes(identity) in captured:
            declarations[canonical_bytes(identity)] = {"identity": identity, "role": row.role}
    codes = {i["code_id"] for i in captured.values() if i["code_id"]}
    debugs = {i["debug_id"] for i in captured.values() if i["debug_id"]}
    rows = session.execute(
        select(CatalogFile, ArtifactEntry.workspace_id)
        .join(ArtifactEntry, ArtifactEntry.file_id == CatalogFile.id)
        .where(
            or_(ArtifactEntry.workspace_id == workspace_id, ArtifactEntry.workspace_id.is_(None)),
            or_(CatalogFile.code_id.in_(codes), CatalogFile.debug_id.in_(debugs)),
        )
        .distinct()
    ).all()
    defaults = []
    for _key, identity in sorted(captured.items()):
        roles = set()
        for file, scope in rows:
            match = file.debug_id and identity["debug_id"] == file.debug_id
            if file.kind == "pe":
                match = (
                    (identity["code_id"] is None or identity["code_id"] == file.code_id)
                    and (identity["debug_id"] is None or identity["debug_id"] == file.debug_id)
                    and (identity["code_id"] is not None or identity["debug_id"] is not None)
                )
            if match:
                roles.add("owned" if scope == workspace_id else "dependency")
        role = "owned" if "owned" in roles else "dependency" if roles else "unknown"
        defaults.append({"identity": identity, "role": role})
    return WorkspacePolicySnapshot(
        workspace_id,
        workspace.in_app_rule_version,
        workspace.module_role_version,
        canonical_bytes(workspace.in_app_rules),
        canonical_bytes([declarations[k] for k in sorted(declarations)]),
        canonical_bytes(defaults),
    )


def prepare_workspace_policies(
    snapshot: WorkspacePolicySnapshot,
    inspect: dict[str, Any],
    *,
    public_sources: list[dict[str, Any]],
    schema_root: Path,
) -> dict[str, Any]:
    rules = json.loads(snapshot.rules)
    included = {v.casefold() for v in rules.get("include_modules", [])}
    excluded = {v.casefold() for v in rules.get("exclude_modules", [])}
    declared = {
        canonical_bytes(v["identity"]): v["role"] for v in json.loads(snapshot.declarations)
    }
    defaults = {canonical_bytes(v["identity"]): v["role"] for v in json.loads(snapshot.defaults)}
    roles = []
    for index, module in enumerate(inspect["modules"]):
        identity = normalize_identity(
            {**module, "architecture": inspect["process"]["architecture"]}
        )
        key = canonical_bytes(identity)
        name = module_basename(module.get("code_file") or "")
        if is_system_module(module.get("code_file") or ""):
            role = "system"
            source = "system"
        elif key in declared:
            role = declared[key]
            source = "explicit"
        elif name in excluded:
            role = "dependency"
            source = "in_app_rule"
        elif name in included:
            role = "owned"
            source = "in_app_rule"
        else:
            role = defaults.get(key, "unknown")
            source = "catalog_default"
        roles.append(
            {
                "module_index": index,
                "identity": identity,
                "role": role,
                "in_app": role == "owned",
                "source": source,
            }
        )
    verify_public_sources(public_sources)
    policies = {
        "role_policy": {"schema_version": "workspace-role-policy-v1", "modules": roles},
        "source_policy": {
            "schema_version": "frozen-source-policy-v2",
            "pair_source_protocol": "pair-http-v3",
            "public_sources": public_sources,
        },
    }
    validator = load_validator(str((schema_root / "analysis-run-v3.schema.json").resolve()))
    schema = validator.schema
    assert isinstance(schema, dict)
    require(
        not list(validator.descend(policies, schema["properties"]["policy_snapshots"])),
        "WORKSPACE_POLICY_SCHEMA_INVALID",
    )
    return policies
