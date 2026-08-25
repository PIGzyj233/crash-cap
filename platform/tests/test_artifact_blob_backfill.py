from __future__ import annotations

from typing import Any

import pytest
from crashcap_api.models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobBackfillGap,
    ArtifactBlobLegacyCopy,
    ArtifactBlobPair,
    Build,
    BuildPublication,
)
from crashcap_api.services.artifact_blob_backfill import (
    backfill_artifact_blobs,
    cleanup_artifact_blob_legacy_copies,
)
from crashcap_api.storage import ObjectNotFoundError
from crashcap_worker.core_runner import CoreExecutor
from sqlalchemy import func, select


def _legacy_pair(harness: Any, workspace_id: str, *, version: str, debug_id: str) -> Build:
    from .conftest import pdb_bytes, pe_bytes

    created = harness.create_build(workspace_id, version=version)
    harness.put_manifest(created["id"], version=version)
    harness.upload_artifact(created["id"], "pe", "app.exe", pe_bytes(debug_id))
    harness.upload_artifact(created["id"], "pdb", "app.pdb", pdb_bytes(debug_id))
    with harness.app.state.database.sessions() as session:
        build = session.get(Build, created["id"])
        assert build is not None
        session.expunge(build)
        return build


def test_backfill_is_verified_dry_run_idempotent_and_preserves_legacy_copies(
    harness: Any,
) -> None:
    workspace = harness.create_workspace("artifact-blob-backfill")
    build = _legacy_pair(
        harness,
        workspace["id"],
        version="1.0.0",
        debug_id="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA1",
    )
    with harness.app.state.database.sessions() as session:
        artifacts = session.scalars(
            select(Artifact).where(Artifact.build_id == build.id).order_by(Artifact.id)
        ).all()
        original_keys = {row.id: row.object_key for row in artifacts}
        assert len(original_keys) == 2

    dry_run = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=False,
    )
    assert dry_run["mode"] == "dry-run"
    assert dry_run["scanned"] == 2
    assert {case["outcome"] for case in dry_run["cases"]} == {"would_link"}
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactBlob)) == 0

    applied = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert applied["gaps"] == 0
    assert applied["linked"] == 2
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactBlob)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactBlobLegacyCopy)) == 2
        pair = session.scalar(select(ArtifactBlobPair))
        assert pair is not None and pair.state == "published"
        current = session.scalars(
            select(Artifact).where(Artifact.build_id == build.id).order_by(Artifact.id)
        ).all()
        assert all(row.artifact_blob_id for row in current)
        assert all(row.materialization_source == "backfill" for row in current)
        canonical_prefix = f"artifact-blobs/{workspace['id']}/"
        assert all(row.object_key.startswith(canonical_prefix) for row in current)
        unchanged_build = session.get(Build, build.id)
        assert unchanged_build is not None and unchanged_build.sealed_at is None
        assert session.scalar(select(func.count()).select_from(BuildPublication)) == 0
    for key in original_keys.values():
        assert harness.app.state.store.head(key).size > 0

    replay = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert replay["already_linked"] == 2
    assert replay["gaps"] == 0
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ArtifactBlob)) == 2
        assert session.scalar(select(func.count()).select_from(ArtifactBlobPair)) == 1

    cleanup_dry_run = cleanup_artifact_blob_legacy_copies(
        harness.app.state.database.sessions,
        harness.app.state.store,
        apply=False,
    )
    assert cleanup_dry_run["deleted_or_would_delete"] == 2
    for key in original_keys.values():
        assert harness.app.state.store.head(key).size > 0

    cleanup = cleanup_artifact_blob_legacy_copies(
        harness.app.state.database.sessions,
        harness.app.state.store,
        apply=True,
    )
    assert cleanup["deleted_or_would_delete"] == 2
    for key in original_keys.values():
        with pytest.raises(ObjectNotFoundError):
            harness.app.state.store.head(key)


def test_backfill_records_missing_object_gap_without_inventing_identity(harness: Any) -> None:
    from .conftest import pe_bytes

    workspace = harness.create_workspace("artifact-blob-backfill-gap")
    build = harness.create_build(workspace["id"], version="2.0.0")
    harness.put_manifest(build["id"], version="2.0.0")
    uploaded = harness.upload_artifact(
        build["id"],
        "pe",
        "app.exe",
        pe_bytes("BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB1"),
    )
    with harness.app.state.database.sessions() as session:
        artifact = session.get(Artifact, uploaded["id"])
        assert artifact is not None
        object_key = artifact.object_key
        build_count = int(session.scalar(select(func.count()).select_from(Build)) or 0)
    harness.app.state.store.delete(object_key)

    report = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert report["gaps"] == 1
    assert report["cases"][0]["gap_reason"] == "object_missing"
    with harness.app.state.database.sessions() as session:
        gap = session.get(ArtifactBlobBackfillGap, uploaded["id"])
        assert gap is not None and gap.resolved_at is None
        assert session.get(Artifact, uploaded["id"]).artifact_blob_id is None
        assert int(session.scalar(select(func.count()).select_from(Build)) or 0) == build_count
        assert session.scalar(select(func.count()).select_from(BuildPublication)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactBlob)) == 0


def test_backfill_repairs_lost_canonical_from_retained_copy(harness: Any) -> None:
    workspace = harness.create_workspace("artifact-blob-backfill-repair")
    build = _legacy_pair(
        harness,
        workspace["id"],
        version="3.0.0",
        debug_id="CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC1",
    )
    first = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert first["gaps"] == 0
    with harness.app.state.database.sessions() as session:
        artifact = session.scalar(
            select(Artifact).where(Artifact.build_id == build.id, Artifact.kind == "pe")
        )
        assert artifact is not None
        canonical_key = artifact.object_key
        legacy = session.get(ArtifactBlobLegacyCopy, artifact.id)
        assert legacy is not None
        legacy_key = legacy.object_key
    harness.app.state.store.delete(canonical_key)
    assert harness.app.state.store.head(legacy_key).size > 0

    repaired = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert repaired["gaps"] == 0
    assert harness.app.state.store.head(canonical_key).size > 0

    # A present-but-corrupt canonical copy is repaired from the retained,
    # independently re-hashed per-Build copy as well.
    harness.app.state.store.put_bytes(canonical_key, b"corrupt", "application/octet-stream")
    repaired_corruption = backfill_artifact_blobs(
        harness.app.state.database.sessions,
        harness.app.state.store,
        CoreExecutor(harness.settings),
        apply=True,
    )
    assert repaired_corruption["gaps"] == 0
    assert harness.app.state.store.head(canonical_key).size > len(b"corrupt")
