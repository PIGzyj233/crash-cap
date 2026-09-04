from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest
from crashcap_api.config import Settings
from crashcap_api.frozen_inputs import FrozenInputError, canonical_bytes, digest
from crashcap_api.models import Artifact, Build, BuildModule, Workspace, WorkspaceModuleRole
from crashcap_api.services.analysis_demands import DemandError
from crashcap_api.services.workspace_builds import prepare_build_policy, snapshot_workspace_builds
from crashcap_api.services.workspace_policies import (
    declare_workspace_module_role,
    prepare_workspace_policies,
    snapshot_workspace_policies,
)

from .test_workspace_builds import IDENTITY, ROOT, database, pg, seed_build

__all__ = ["database", "pg"]
SCHEMAS = ROOT / "drafts/qa-symbol-import"
DESCRIPTOR = {"schema_version": "1.0", "archive": "source.zip", "source_root": "C:\\producer"}


def inspect_report(code_file="target.exe", identity=None):
    return {
        "process": {"architecture": "x86_64"},
        "modules": [{**(identity or IDENTITY), "code_file": code_file}],
    }


def prepare(session, manifests, *, inspect=None, sources=None):
    report = inspect or inspect_report()
    builds = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
    snapshot = snapshot_workspace_policies(session, builds)
    policy = prepare_build_policy(
        builds, {key: canonical_bytes(value) for key, value in manifests.items()}, schema_root=ROOT
    )
    return snapshot, prepare_workspace_policies(
        snapshot, policy, report, public_sources=sources or [], schema_root=SCHEMAS
    )


@pytest.mark.parametrize(
    ("file", "rules", "role", "in_app"),
    [
        ("renamed.exe", {}, "entrypoint", True),
        ("renamed.exe", {"exclude_modules": ["RENAMED.EXE"]}, "dependency", False),
        ("renamed.exe", {"include_modules": ["renamed.exe"]}, "entrypoint", True),
        (
            "C:\\Windows\\System32\\renamed.exe",
            {"include_modules": ["renamed.exe"]},
            "system",
            False,
        ),
        ("NTDLL.DLL", {"include_modules": ["ntdll.dll"]}, "system", False),
        (
            "renamed.exe",
            {"include_modules": ["renamed.exe"], "exclude_modules": ["renamed.exe"]},
            "dependency",
            False,
        ),
    ],
)
def test_existing_workspace_rules_and_system_precedence(database, file, rules, role, in_app):
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        session.get(Workspace, "wsp_a").in_app_rules = rules
        session.flush()
        _, (policy, locations) = prepare(session, {"bld_a": manifest}, inspect=inspect_report(file))
        assert policy["role_policy"]["modules"][0] == {
            "module_index": 0,
            "identity": IDENTITY,
            "role": role,
            "in_app": in_app,
        }
        assert locations == []


def test_role_requires_full_local_identity_not_global_provider_or_name(database):
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        seed_build(session, "wsp_b", "bld_b", role="dependency")
        for identity in ({**IDENTITY, "code_id": None}, {**IDENTITY, "debug_id": "4" * 32 + "1"}):
            _, (policy, _) = prepare(
                session, {"bld_a": manifest}, inspect=inspect_report("renamed.exe", identity)
            )
            assert policy["role_policy"]["modules"][0]["role"] == "unknown"
        _, (policy, _) = prepare(session, {"bld_a": manifest})
        assert policy["role_policy"]["modules"][0]["role"] == "entrypoint"


def test_exact_workspace_declaration_is_append_only_idempotent_and_overrides_build(database):
    now = datetime(2026, 9, 4, tzinfo=UTC)
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        first = declare_workspace_module_role(session, "wsp_a", IDENTITY, "dependency", now=now)
        same = declare_workspace_module_role(session, "wsp_a", IDENTITY, "dependency", now=now)
        changed = declare_workspace_module_role(session, "wsp_a", IDENTITY, "owned", now=now)
        assert (first.version, first.changed) == (1, True)
        assert (same.version, same.changed) == (1, False)
        assert (changed.version, changed.changed) == (2, True)
        assert session.query(WorkspaceModuleRole).count() == 2
        snapshot, (policy, _) = prepare(session, {"bld_a": manifest})
        assert snapshot.module_role_version == 2
        assert policy["role_policy"]["modules"][0]["role"] == "owned"
        assert policy["role_policy"]["modules"][0]["in_app"] is True


def test_exact_workspace_declaration_is_scoped_and_requires_complete_identity(database):
    now = datetime(2026, 9, 4, tzinfo=UTC)
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        seed_build(session, "wsp_b", "bld_b")
        declare_workspace_module_role(session, "wsp_b", IDENTITY, "dependency", now=now)
        _, (policy, _) = prepare(session, {"bld_a": manifest})
        assert policy["role_policy"]["modules"][0]["role"] == "entrypoint"
        for identity in (
            {**IDENTITY, "code_id": None},
            {**IDENTITY, "debug_id": None},
            {**IDENTITY, "architecture": "unknown"},
        ):
            with pytest.raises(DemandError, match="EXACT_IDENTITY_REQUIRED"):
                declare_workspace_module_role(session, "wsp_a", identity, "owned", now=now)


def test_conflicting_local_roles_do_not_pick_latest_build(database):
    with database.sessions.begin() as session:
        first = seed_build(session)
        second = seed_build(session, build_id="bld_second", role="owned")
        declaration = {
            "code_file": "launcher.exe",
            "debug_file": "launcher.pdb",
            "role": "entrypoint",
        }
        second["modules"].append(declaration)
        session.add(BuildModule(id="mod_launcher", build_id="bld_second", **declaration))
        session.flush()
        builds = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        snapshot = snapshot_workspace_policies(session, builds)
        policy = prepare_build_policy(
            builds,
            {"bld_a": canonical_bytes(first), "bld_second": canonical_bytes(second)},
            schema_root=ROOT,
        )
        with pytest.raises(DemandError, match="ROLE_AMBIGUOUS"):
            prepare_workspace_policies(
                snapshot, policy, inspect_report(), public_sources=[], schema_root=SCHEMAS
            )


def source(
    session,
    *,
    artifact_id="art_source",
    sha="c" * 64,
    workspace="wsp_a",
    build_id="bld_a",
    status="verified",
):
    session.add(
        Artifact(
            id=artifact_id,
            build_id=build_id,
            module_id=None,
            kind="source_bundle",
            logical_name="source.zip",
            sha256=sha,
            size=21,
            object_key=f"{workspace}/{artifact_id}.zip",
            verification_status=status,
        )
    )
    session.flush()


def source_manifest(session, **kwargs):
    manifest = seed_build(session, **kwargs)
    build_id = kwargs.get("build_id", "bld_a")
    manifest.update(schema_version="2.0", source_bundle=DESCRIPTOR)
    build = session.get(Build, build_id)
    build.manifest_schema_version = "2.0"
    build.source_bundle_config = DESCRIPTOR
    session.flush()
    return manifest


def test_source_scope_binding_and_locations_do_not_enter_semantic_policy(database):
    with database.sessions.begin() as session:
        manifest = source_manifest(session)
        source(session)
        source_manifest(session, workspace="wsp_b", build_id="bld_b")
        source(
            session, workspace="wsp_b", build_id="bld_b", artifact_id="art_private", sha="d" * 64
        )
        snapshot, (policy, locations) = prepare(session, {"bld_a": manifest})
        assert policy["source_policy"]["bundles"] == [
            {
                "build_id": "bld_a",
                "artifact_id": "art_source",
                "sha256": "c" * 64,
                "size": 21,
                "descriptor": DESCRIPTOR,
            }
        ]
        assert locations[0]["content"]["object_key"] == "wsp_a/art_source.zip"
        session.get(Artifact, "art_source").object_key = "new/replica.zip"
        session.get(Workspace, "wsp_a").in_app_rule_version += 1
        session.flush()
        changed, (new_policy, new_locations) = prepare(session, {"bld_a": manifest})
        assert digest(new_policy) == digest(policy)
        assert changed.in_app_rule_version == snapshot.in_app_rule_version + 1
        assert new_locations != locations
        assert json.loads(snapshot.bundles)[0]["object_key"] == "wsp_a/art_source.zip"


@pytest.mark.parametrize("problem", ["archive", "module", "descriptor", "content", "budget"])
def test_source_inconsistent_or_incomplete_evidence_cannot_select_arbitrary_bundle(
    database, problem
):
    with database.sessions.begin() as session:
        source_manifest(session)
        source(session)
        if problem == "archive":
            session.get(Artifact, "art_source").logical_name = "other.zip"
        elif problem == "module":
            session.get(Artifact, "art_source").module_id = "mod_bld_a"
        elif problem == "descriptor":
            session.get(Build, "bld_a").source_bundle_config = None
        else:
            source(
                session,
                artifact_id="art_second",
                sha="d" * 64 if problem == "content" else "c" * 64,
            )
        session.flush()
        builds = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        with pytest.raises(DemandError, match="WORKSPACE_SOURCE_"):
            snapshot_workspace_policies(
                session, builds, bundle_limit=1 if problem == "budget" else 200
            )


def test_pending_source_is_not_available_and_replicas_keep_all_evidence(database):
    with database.sessions.begin() as session:
        manifest = source_manifest(session)
        source(session, status="pending")
        _, (policy, _) = prepare(session, {"bld_a": manifest})
        assert policy["source_policy"]["bundles"] == []
        session.get(Artifact, "art_source").verification_status = "verified"
        source(session, artifact_id="art_same_content")
        session.flush()
        _, (policy, _) = prepare(session, {"bld_a": manifest})
        assert [row["artifact_id"] for row in policy["source_policy"]["bundles"]] == [
            "art_same_content",
            "art_source",
        ]


@pytest.mark.parametrize(
    "problem", ["credentials", "reserved", "duplicate", "filter_order", "private"]
)
def test_public_source_policy_uses_core_semantic_validation(database, tmp_path, problem):
    sources = copy.deepcopy(Settings.for_test(tmp_path).frozen_public_sources)
    if problem == "credentials":
        sources[0]["url"] = "https://user:password@example.invalid/symbols/"
    elif problem == "reserved":
        sources[0]["id"] = "crash-cap:pair:forged"
    elif problem == "duplicate":
        sources *= 2
    elif problem == "filter_order":
        sources[0]["filters"]["filetypes"] = ["pe", "pdb"]
    else:
        sources[0]["is_public"] = False
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        with pytest.raises((DemandError, FrozenInputError)):
            prepare(session, {"bld_a": manifest}, sources=sources)
