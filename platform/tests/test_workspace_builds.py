from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.frozen_inputs import canonical_bytes, digest
from crashcap_api.models import Artifact, Build, BuildModule, CatalogPair, Workspace
from crashcap_api.services.analysis_demands import DemandError
from crashcap_api.services.symbol_catalog import admit_pair
from crashcap_api.services.workspace_builds import (
    WorkspaceBuildLimits,
    prepare_build_policy,
    snapshot_workspace_builds,
)

from .test_symbol_catalog import origin, pair_evidence
from .test_symbol_catalog_postgres import pg

__all__ = ["pg"]

ROOT = Path(__file__).resolve().parents[2] / "contracts"
IDENTITY = {"code_id": "123456789", "debug_id": "2" * 32 + "1", "architecture": "x86_64"}


@pytest.fixture
def database(tmp_path, request):
    url = None
    if os.getenv("QAI_CATALOG_DATABASE_URL"):
        engine, _, _ = request.getfixturevalue("pg")
        url = engine.url.render_as_string(hide_password=False)
    db = Database(Settings.for_test(tmp_path, url) if url else Settings.for_test(tmp_path))
    yield db
    db.dispose()


def seed_build(session, workspace="wsp_a", build_id="bld_a", *, role="entrypoint", catalog=True):
    if session.get(Workspace, workspace) is None:
        session.add(Workspace(id=workspace, name=workspace))
        session.flush()
    session.add(
        Build(
            id=build_id,
            workspace_id=workspace,
            version="same-label-is-not-identity",
            manifest_object_key=f"builds/{build_id}/manifest.json",
            manifest_schema_version="1.0",
        )
    )
    session.flush()
    module_id = f"mod_{build_id}"
    session.add(
        BuildModule(
            id=module_id,
            build_id=build_id,
            code_file="renamed.exe",
            debug_file="renamed.pdb",
            role=role,
            # Producer hints and stale mutable module IDs must not select a pair.
            code_id="987654321",
            debug_id="3" * 32 + "1",
        )
    )
    session.flush()
    pe, pdb, locations = pair_evidence()
    if catalog:
        admit_pair(session, pe, pdb, locations, origin(build_id))
    for evidence in (pe, pdb):
        session.add(
            Artifact(
                id=f"art_{build_id}_{evidence.kind}",
                build_id=build_id,
                module_id=module_id,
                kind=evidence.kind,
                logical_name=f"different.{evidence.kind}",
                sha256=evidence.raw_sha256,
                size=evidence.raw_size,
                object_key=f"builds/{build_id}/{evidence.kind}",
                code_id=evidence.code_id,
                debug_id=evidence.debug_id,
                verification_status="verified",
            )
        )
    session.flush()
    return {
        "schema_version": "1.0",
        "product": "fixture",
        "version": "same-label-is-not-identity",
        "architecture": "x86_64",
        "modules": [{"code_file": "renamed.exe", "debug_file": "renamed.pdb", "role": role}],
    }


def test_only_consumer_artifact_content_binds_build_and_withdrawal_keeps_history(database):
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        seed_build(session, "wsp_b", "bld_b", role="dependency")
        before = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        pair_id = digest(["pair-v1", "a" * 64, "b" * 64])
        session.get(CatalogPair, pair_id).state = "withdrawn"
    with database.sessions() as session:
        snapshot = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        assert snapshot.metadata == before.metadata
        policy = prepare_build_policy(
            snapshot, {"bld_a": canonical_bytes(manifest)}, schema_root=ROOT
        )
        assert [row["build_id"] for row in policy["builds"]] == ["bld_a"]
        module = policy["builds"][0]["verified_modules"][0]
        assert module["identity"] == IDENTITY
        assert module["role"] == "entrypoint"
        assert module["verified_pair_ids"] == [pair_id]
        assert module["artifact_ids"] == ["art_bld_a_pdb", "art_bld_a_pe"]
        assert policy["builds"][0]["manifest_sha256"] == digest(manifest)
        assert snapshot_workspace_builds(session, "wsp_empty", [IDENTITY]).metadata == b"[]"
        with pytest.raises(DemandError, match="OUTSIDE_SCOPE"):
            snapshot_workspace_builds(session, "wsp_a", [IDENTITY], reported_build_id="bld_b")


def test_same_identity_local_builds_are_all_preserved_and_unrelated_input_is_stable(database):
    with database.sessions.begin() as session:
        seed_build(session)
        seed_build(session, build_id="bld_second")
        snapshot = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        assert len(json.loads(snapshot.metadata)) == 2
        session.add(Build(id="bld_unrelated", workspace_id="wsp_a", version="newer"))
        session.flush()
        assert snapshot_workspace_builds(session, "wsp_a", [IDENTITY]).metadata == snapshot.metadata
        # One known identifier is not enough to claim a local Build association.
        assert (
            snapshot_workspace_builds(session, "wsp_a", [{**IDENTITY, "code_id": None}]).metadata
            == b"[]"
        )


def test_missing_catalog_backfill_does_not_silently_remove_verified_local_build(database):
    with database.sessions.begin() as session:
        seed_build(session, catalog=False)
        with pytest.raises(DemandError, match="BACKFILL_REQUIRED"):
            snapshot_workspace_builds(session, "wsp_a", [IDENTITY])


@pytest.mark.parametrize("kind", ["pe", "pdb"])
def test_pending_file_cannot_establish_verified_pair(database, kind):
    with database.sessions.begin() as session:
        seed_build(session)
        session.get(Artifact, f"art_bld_a_{kind}").verification_status = "pending"
        session.flush()
        snapshot = snapshot_workspace_builds(
            session, "wsp_a", [IDENTITY], reported_build_id="bld_a"
        )
        module = json.loads(snapshot.metadata)[0]["verified_modules"][0]
        assert module["verified_pair_ids"] == []


@pytest.mark.parametrize("field", ["artifacts", "modules", "pair_checks"])
def test_enumeration_limit_cannot_report_a_unique_build(database, field):
    with database.sessions.begin() as session:
        seed_build(session)
        seed_build(session, build_id="bld_second")
        with pytest.raises(DemandError, match="ENUMERATION_INCOMPLETE"):
            snapshot_workspace_builds(
                session, "wsp_a", [IDENTITY], limits=replace(WorkspaceBuildLimits(), **{field: 1})
            )


@pytest.mark.parametrize(
    "change", ["role", "filename", "architecture", "source", "duplicate", "version"]
)
def test_manifest_must_match_local_declarations_and_descriptor(database, change):
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        snapshot = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
    if change == "role":
        manifest["modules"][0]["role"] = "dependency"
    elif change == "filename":
        manifest["modules"][0]["debug_file"] = "other.pdb"
    elif change == "architecture":
        manifest["architecture"] = "arm64"
    elif change == "source":
        manifest["schema_version"] = "2.0"
        manifest["source_bundle"] = {
            "schema_version": "1.0",
            "archive": "source.zip",
            "source_root": "src",
        }
    elif change == "duplicate":
        manifest["modules"] *= 2
    else:
        manifest["schema_version"] = "2.0"
    with pytest.raises(DemandError, match="WORKSPACE_MANIFEST_"):
        prepare_build_policy(snapshot, {"bld_a": canonical_bytes(manifest)}, schema_root=ROOT)


def test_snapshot_detached_and_manifest_objects_are_required_and_bounded(database):
    with database.sessions.begin() as session:
        manifest = seed_build(session)
        snapshot = snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
        session.get(BuildModule, "mod_bld_a").role = "dependency"
        assert json.loads(snapshot.metadata)[0]["verified_modules"][0]["role"] == "entrypoint"
    with pytest.raises(DemandError, match="MANIFEST_MISSING"):
        prepare_build_policy(snapshot, {}, schema_root=ROOT)
    with pytest.raises(DemandError, match="SIZE_LIMIT"):
        prepare_build_policy(
            replace(snapshot, limits=replace(snapshot.limits, manifest_bytes=1)),
            {"bld_a": canonical_bytes(manifest)},
            schema_root=ROOT,
        )
    data = canonical_bytes(manifest).replace(
        b'"product":"fixture"', b'"product":"first","product":"fixture"'
    )
    with pytest.raises(DemandError, match="DUPLICATE_KEY"):
        prepare_build_policy(snapshot, {"bld_a": data}, schema_root=ROOT)
    manifest["version"] = "tampered-display-label"
    with pytest.raises(DemandError, match="METADATA_MISMATCH"):
        prepare_build_policy(snapshot, {"bld_a": canonical_bytes(manifest)}, schema_root=ROOT)


@pytest.mark.parametrize("cataloged", [True, False])
def test_multiple_actual_identities_in_one_local_module_cannot_pick_latest(database, cataloged):
    with database.sessions.begin() as session:
        seed_build(session)
        pe, pdb, locations = pair_evidence(pe_sha="c" * 64, code="987654321")
        if cataloged:
            admit_pair(session, pe, pdb, locations, origin("second-content"))
        session.add(
            Artifact(
                id="art_alternative_pe",
                build_id="bld_a",
                module_id="mod_bld_a",
                kind="pe",
                logical_name="renamed.exe",
                sha256=pe.raw_sha256,
                size=pe.raw_size,
                object_key="other/pe",
                code_id=pe.code_id,
                debug_id=pe.debug_id,
                verification_status="verified",
            )
        )
        session.flush()
        with pytest.raises(DemandError, match="AMBIGUOUS" if cataloged else "BACKFILL_REQUIRED"):
            snapshot_workspace_builds(session, "wsp_a", [IDENTITY])


def test_artifact_cannot_borrow_another_builds_module(database):
    with database.sessions.begin() as session:
        seed_build(session)
        seed_build(session, "wsp_b", "bld_b")
        session.get(Artifact, "art_bld_a_pdb").module_id = "mod_bld_b"
        session.flush()
        with pytest.raises(DemandError, match="ARTIFACT_MODULE_MISMATCH"):
            snapshot_workspace_builds(session, "wsp_a", [IDENTITY])
