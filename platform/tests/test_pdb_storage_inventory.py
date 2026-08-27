from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crashcap_api.models import ArtifactBlob, ArtifactBlobPayloadLegacyCopy, Upload
from crashcap_api.services import pdb_storage_inventory as inventory_module
from crashcap_api.services.pdb_storage_inventory import (
    collect_pdb_storage_inventory,
    render_pdb_storage_inventory_markdown,
)
from sqlalchemy.dialects import postgresql

from .conftest import Phase1Harness, dump_bytes


def test_inventory_aggregates_without_object_keys_or_filenames(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("pdb-storage-inventory")
    harness.initialize_dump(workspace["id"], dump_bytes(71))
    with harness.app.state.database.sessions() as session:
        report = collect_pdb_storage_inventory(session, harness.app.state.store)

    assert report["schema_version"] == "pdb-storage-inventory-v1"
    uploads = report["database"]["uploads"]
    assert uploads[0]["workspace_id"] == workspace["id"]
    assert uploads[0]["payload_bytes"] == len(dump_bytes(71))
    stored = next(row for row in report["object_store"] if row["prefix"] == "uploads")
    assert stored["workspace_id"] == workspace["id"]
    assert stored["object_count"] == 1
    assert report["privacy"]["object_keys_included"] is False
    _assert_no_sensitive_fields(report)
    markdown = render_pdb_storage_inventory_markdown(report)
    assert "PDB storage inventory" in markdown
    assert "uploads/" not in markdown
    assert "oldest_age_seconds" in markdown


def test_inventory_reconciles_orphan_missing_deleted_and_size_mismatch_payloads(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("pdb-storage-reconciliation")
    initialized = [
        harness.initialize_dump(workspace["id"], dump_bytes(seed)) for seed in (72, 73, 74)
    ]
    with harness.app.state.database.sessions() as session:
        uploads = [session.get(Upload, item["upload_id"]) for item in initialized]
        assert all(upload is not None for upload in uploads)
        deleted, missing, mismatched = uploads
        assert deleted is not None and missing is not None and mismatched is not None
        deleted.payload_deleted_at = datetime.now(UTC)
        session.commit()
        missing_key = missing.object_key
        mismatched_key = mismatched.object_key
    harness.app.state.store.delete(missing_key)
    harness.app.state.store.put_bytes(mismatched_key, b"wrong-size", "application/octet-stream")
    harness.app.state.store.put_bytes(
        f"uploads/{workspace['id']}/orphan/test.bin", b"orphan", "application/octet-stream"
    )

    with harness.app.state.database.sessions() as session:
        report = collect_pdb_storage_inventory(session, harness.app.state.store)
    row = report["reconciliation"]["upload_payloads"][0]
    assert row == {
        "workspace_id": workspace["id"],
        "orphan_objects": 1,
        "orphan_bytes": 6,
        "missing_retained_objects": 1,
        "missing_retained_bytes": len(dump_bytes(73)),
        "deleted_marker_but_present_objects": 1,
        "deleted_marker_but_present_bytes": len(dump_bytes(72)),
        "size_mismatch_objects": 1,
        "size_mismatch_bytes": len(dump_bytes(74)) - len(b"wrong-size"),
    }
    _assert_no_sensitive_fields(report)


def test_inventory_reports_raw_payload_rollback_bytes(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("pdb-storage-rollback-inventory")
    now = datetime.now(UTC)
    with harness.app.state.database.sessions() as session:
        blob = ArtifactBlob(
            id="abl_inventory_rollback",
            workspace_id=workspace["id"],
            sha256="a" * 64,
            kind="pdb",
            size=341,
            object_key="artifact-blobs/raw.pdb",
            verification_status="verified",
            verified_at=now,
            payload_encoding="zstd-v1",
            payload_size=34,
            payload_sha256="b" * 64,
            payload_object_key="artifact-blobs-v2/compressed.pdb.zst",
            payload_verified_at=now,
        )
        session.add(blob)
        session.add(
            ArtifactBlobPayloadLegacyCopy(
                artifact_blob_id=blob.id,
                object_key="artifact-blobs/raw.pdb",
                size=341,
                sha256=blob.sha256,
                retained_until=now + timedelta(days=14),
            )
        )
        session.commit()
        report = collect_pdb_storage_inventory(session, harness.app.state.store)

    assert report["database"]["payload_rollback_copies"] == [
        {
            "workspace_id": workspace["id"],
            "kind": "pdb",
            "state": "retained",
            "count": 1,
            "stored_bytes": 341,
        }
    ]
    _assert_no_sensitive_fields(report)


def test_inventory_maps_physical_symbolicator_directories_to_policy_groups(
    harness: Phase1Harness, tmp_path: Path
) -> None:
    cache_root = tmp_path / "symbolicator-cache"
    objects = cache_root / "objects"
    symcaches = cache_root / "symcaches"
    cache_root.mkdir()
    objects.mkdir()
    symcaches.mkdir()
    downloaded_file = objects / "downloaded"
    derived_file = symcaches / "derived"
    downloaded_file.write_bytes(b"1234")
    derived_file.write_bytes(b"123456")
    os.utime(downloaded_file, (100.0, 100.0))
    os.utime(derived_file, (200.0, 200.0))

    with harness.app.state.database.sessions() as session:
        report = collect_pdb_storage_inventory(
            session,
            harness.app.state.store,
            symbolicator_cache_root=cache_root,
        )

    rows = {row["scope"]: row for row in report["volumes"]["symbolicator_cache"]}
    assert rows["downloaded"]["status"] == "available"
    assert rows["downloaded"]["file_count"] == 1
    assert rows["downloaded"]["bytes"] == 4
    assert rows["derived"]["status"] == "available"
    assert rows["derived"]["file_count"] == 1
    assert rows["derived"]["bytes"] == 6
    assert rows["downloaded"]["oldest_age_seconds"] > rows["derived"]["oldest_age_seconds"]


def test_postgresql_grouping_reuses_case_bind_parameters() -> None:
    class EmptyResult:
        @staticmethod
        def all() -> list[object]:
            return []

    class CaptureSession:
        statement: Any = None

        def execute(self, statement: Any) -> EmptyResult:
            self.statement = statement
            return EmptyResult()

    for aggregate in (
        inventory_module._upload_groups,
        inventory_module._legacy_groups,
        inventory_module._payload_legacy_groups,
    ):
        session = CaptureSession()
        assert aggregate(session) == []  # type: ignore[arg-type]
        compiled = session.statement.compile(dialect=postgresql.dialect())
        state_values = [
            value for value in compiled.params.values() if value in {"deleted", "retained"}
        ]
        assert state_values.count("deleted") == 1
        assert state_values.count("retained") == 1


def _assert_no_sensitive_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in {"object_key", "filename", "url", "credential"}
            _assert_no_sensitive_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_sensitive_fields(child)
