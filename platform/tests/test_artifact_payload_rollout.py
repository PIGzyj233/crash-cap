from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import zstandard
from crashcap_api.models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPayloadLegacyCopy,
)
from crashcap_api.object_keys import artifact_blob_payload_key
from crashcap_api.services.artifact_blob_export import (
    ArtifactBlobExportError,
    materialize_artifact_blob_export,
)
from crashcap_api.services.artifact_payload_backfill import (
    backfill_artifact_blob_payloads,
    cleanup_artifact_blob_raw_payloads,
)
from crashcap_api.services.artifact_payloads import ArtifactPayloadError, BlobMaterializer
from crashcap_api.storage import ObjectNotFoundError
from prometheus_client import REGISTRY
from sqlalchemy import select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes
from .test_artifact_blob_dedup import _deliver_upload, _publication, _register


class CapturingSymbols:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, bytes, str]] = []

    def publish_pair(
        self, workspace_id: str, pe_path: Path, pdb_path: Path, debug_id: str
    ) -> None:
        self.calls.append((workspace_id, pe_path.read_bytes(), pdb_path.read_bytes(), debug_id))


def _publish_one_pair(
    harness: Phase1Harness,
    *,
    workspace_name: str,
    compression_mode: Literal["off", "shadow", "active"],
) -> tuple[dict[str, object], bytes, bytes]:
    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "active"
    harness.settings.artifact_blob_compression_mode = compression_mode
    workspace = harness.create_workspace(workspace_name)
    debug_id = "ABCDEFABCDEFABCDEFABCDEFABCDEFAB1"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="1.0.0",
        client_id=f"local:{workspace_name}",
        modules=[("app.exe", "app.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    for expected, payload in zip(body["artifacts"], (pe, pdb), strict=True):
        _deliver_upload(harness, registered["build_id"], expected, payload)
    return registered, pe, pdb


def test_active_writer_binds_verified_zstd_and_retains_raw_rollback(
    harness: Phase1Harness, tmp_path: Path
) -> None:
    registered, pe, pdb = _publish_one_pair(
        harness, workspace_name="payload-active", compression_mode="active"
    )
    with harness.app.state.database.sessions() as session:
        artifacts = session.scalars(
            select(Artifact)
            .where(Artifact.build_id == registered["build_id"])
            .order_by(Artifact.kind)
        ).all()
        blobs = [session.get(ArtifactBlob, artifact.artifact_blob_id) for artifact in artifacts]
        assert all(blob is not None for blob in blobs)
        for artifact, blob in zip(artifacts, blobs, strict=True):
            assert blob is not None
            assert blob.payload_encoding == "zstd-v1"
            assert blob.payload_object_key.startswith("artifact-blobs-v2/")
            assert blob.payload_size < blob.size
            assert artifact.object_key == blob.payload_object_key
            legacy = session.get(ArtifactBlobPayloadLegacyCopy, blob.id)
            assert legacy is not None and legacy.object_key == blob.object_key
            assert harness.app.state.store.head(legacy.object_key).size == blob.size
            destination = tmp_path / f"{blob.id}.{blob.kind}"
            BlobMaterializer(harness.app.state.store, tmp_path / "tasks").materialize(
                blob, destination
            )
            assert destination.read_bytes() == (pe if blob.kind == "pe" else pdb)
    status = harness.client.get(
        f"/api/v1/builds/{registered['build_id']}/publication-status"
    ).json()
    assert status["ready"] is True
    build_view = harness.client.get(f"/api/v1/builds/{registered['build_id']}").json()
    assert all(item["payload_encoding"] == "zstd-v1" for item in build_view["artifacts"])
    assert all(item["storage_status"] == "verified" for item in build_view["artifacts"])
    assert all(item["logical_size"] > item["stored_size"] for item in build_view["artifacts"])
    assert all(item["savings_bytes"] > 0 for item in build_view["artifacts"])
    assert all(0 < item["savings_ratio"] < 1 for item in build_view["artifacts"])

    harness.settings.raw_download_enabled = True
    raw_download = harness.client.get(
        f"/api/v1/artifacts/{build_view['artifacts'][0]['id']}/download"
    )
    assert raw_download.status_code == 409
    assert raw_download.json()["error"]["code"] == "RAW_DOWNLOAD_REQUIRES_MATERIALIZATION"


def test_verified_retry_and_reindex_publish_raw_bytes_from_zstd_payload(
    harness: Phase1Harness,
) -> None:
    registered, pe, pdb = _publish_one_pair(
        harness, workspace_name="payload-reader-audit", compression_mode="active"
    )
    symbols = CapturingSymbols()
    harness.app.state.processor.symbols = symbols
    with harness.app.state.database.sessions() as session:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.build_id == registered["build_id"], Artifact.kind == "pe"
            )
        )
        assert artifact is not None
        artifact_id = artifact.id

    harness.app.state.processor._publish_verified_pair(artifact_id)
    assert len(symbols.calls) == 1
    assert symbols.calls[0][1:3] == (pe, pdb)

    symbols.calls.clear()
    response = harness.client.post(
        f"/api/v1/workspaces/{registered['publication']['workspace_id']}/symbols/reindex",
        json={"build_id": registered["build_id"]},
    )
    assert response.status_code == 202, response.text
    harness.drain()
    assert len(symbols.calls) == 1
    assert symbols.calls[0][1:3] == (pe, pdb)


def test_operator_export_materializes_verified_zstd_without_exposing_object_key(
    harness: Phase1Harness, tmp_path: Path
) -> None:
    registered, _pe, pdb = _publish_one_pair(
        harness, workspace_name="payload-operator-export", compression_mode="active"
    )
    destination = tmp_path / "restored.pdb"
    with harness.app.state.database.sessions() as session:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.build_id == registered["build_id"], Artifact.kind == "pdb"
            )
        )
        assert artifact is not None and artifact.artifact_blob_id is not None
        report = materialize_artifact_blob_export(
            session,
            harness.app.state.store,
            tmp_path / "tasks",
            artifact_blob_id=artifact.artifact_blob_id,
            destination=destination,
        )
        session.commit()

    assert destination.read_bytes() == pdb
    assert report["payload_encoding"] == "zstd-v1"
    assert report["logical_sha256"] == hashlib.sha256(pdb).hexdigest()
    assert "object_key" not in report
    assert "destination" not in report

    with harness.app.state.database.sessions() as session:
        try:
            materialize_artifact_blob_export(
                session,
                harness.app.state.store,
                tmp_path / "tasks",
                artifact_blob_id=str(report["artifact_blob_id"]),
                destination=destination,
            )
        except ArtifactBlobExportError as error:
            assert error.code == "destination_exists"
        else:
            raise AssertionError("operator export overwrote an existing destination")

    with harness.app.state.database.sessions() as session:
        blob = session.get(ArtifactBlob, str(report["artifact_blob_id"]))
        assert blob is not None
        payload_key = blob.payload_object_key
        assert payload_key is not None
    payload = bytearray(b"".join(harness.app.state.store.stream(payload_key)))
    payload[len(payload) // 2] ^= 1
    harness.app.state.store.put_bytes(payload_key, bytes(payload), "application/zstd")
    corrupt_destination = tmp_path / "corrupt-output.pdb"
    with harness.app.state.database.sessions() as session:
        try:
            materialize_artifact_blob_export(
                session,
                harness.app.state.store,
                tmp_path / "tasks",
                artifact_blob_id=str(report["artifact_blob_id"]),
                destination=corrupt_destination,
            )
        except ArtifactPayloadError:
            pass
        else:
            raise AssertionError("corrupt payload was exported")
    assert not corrupt_destination.exists()

def test_shadow_writer_verifies_zstd_without_changing_identity_binding(
    harness: Phase1Harness,
) -> None:
    registered, _pe, _pdb = _publish_one_pair(
        harness, workspace_name="payload-shadow", compression_mode="shadow"
    )
    with harness.app.state.database.sessions() as session:
        artifacts = session.scalars(
            select(Artifact).where(Artifact.build_id == registered["build_id"])
        ).all()
        for artifact in artifacts:
            blob = session.get(ArtifactBlob, artifact.artifact_blob_id)
            assert blob is not None
            assert blob.payload_encoding == "identity"
            assert artifact.object_key == blob.object_key
            shadow_key = artifact_blob_payload_key(blob.workspace_id, blob.sha256, "zstd-v1")
            assert harness.app.state.store.head(shadow_key).size > 0
            assert session.get(ArtifactBlobPayloadLegacyCopy, blob.id) is None


def test_same_size_corrupt_payload_is_never_reused(harness: Phase1Harness) -> None:
    registered, pe, pdb = _publish_one_pair(
        harness, workspace_name="payload-corrupt-reuse", compression_mode="active"
    )
    with harness.app.state.database.sessions() as session:
        artifact = session.scalar(
            select(Artifact).where(
                Artifact.build_id == registered["build_id"], Artifact.kind == "pe"
            )
        )
        assert artifact is not None
        blob = session.get(ArtifactBlob, artifact.artifact_blob_id)
        assert blob is not None
        payload_key = blob.payload_object_key
    payload = bytearray(b"".join(harness.app.state.store.stream(payload_key)))
    payload[len(payload) // 2] ^= 1
    harness.app.state.store.put_bytes(payload_key, bytes(payload), "application/zstd")

    body = _publication(
        version="1.0.1",
        client_id="local:payload-corrupt-reuse-second",
        modules=[("app.exe", "app.pdb", "entrypoint", pe, pdb)],
    )
    second = _register(harness, registered["publication"]["workspace_id"], body)
    expected = next(item for item in body["artifacts"] if item["kind"] == "pe")
    response = harness.client.post(
        f"/api/v1/builds/{second['build_id']}/artifacts/deliveries:init",
        json={
            "file_kind": "pe",
            "filename": expected["logical_name"],
            "size": expected["size"],
            "sha256": expected["sha256"],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["disposition"] == "upload"
    with harness.app.state.database.sessions() as session:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == registered["publication"]["workspace_id"],
                ArtifactBlob.sha256 == expected["sha256"],
            )
        )
        assert blob is not None
        assert blob.verification_status == "missing"


def test_blob_payload_backfill_and_grace_gated_raw_cleanup(
    harness: Phase1Harness, tmp_path: Path
) -> None:
    registered, pe, pdb = _publish_one_pair(
        harness, workspace_name="payload-backfill", compression_mode="off"
    )
    dry_run = backfill_artifact_blob_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
    )
    assert dry_run["compressed_or_would_compress"] == 2
    assert dry_run["gaps"] == 0
    applied = backfill_artifact_blob_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        apply=True,
    )
    assert applied["compressed_or_would_compress"] == 2
    assert applied["gaps"] == 0

    before_grace = cleanup_artifact_blob_raw_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=datetime.now(UTC),
    )
    assert before_grace["scanned"] == 0
    after_grace = datetime.now(UTC) + timedelta(days=15)
    cleanup = cleanup_artifact_blob_raw_payloads(
        harness.app.state.database.sessions,
        harness.app.state.store,
        harness.settings,
        now=after_grace,
        apply=True,
    )
    assert cleanup["deleted_or_would_delete"] == 2
    assert cleanup["skipped"] == 0

    with harness.app.state.database.sessions() as session:
        artifacts = session.scalars(
            select(Artifact)
            .where(Artifact.build_id == registered["build_id"])
            .order_by(Artifact.kind)
        ).all()
        for artifact in artifacts:
            blob = session.get(ArtifactBlob, artifact.artifact_blob_id)
            assert blob is not None
            legacy = session.get(ArtifactBlobPayloadLegacyCopy, blob.id)
            assert legacy is not None and legacy.deleted_at is not None
            try:
                harness.app.state.store.head(legacy.object_key)
            except ObjectNotFoundError:
                pass
            else:
                raise AssertionError("raw rollback object still exists after exact cleanup")
            destination = tmp_path / f"restored-{blob.kind}"
            BlobMaterializer(harness.app.state.store, tmp_path / "tasks").materialize(
                blob, destination
            )
            assert destination.read_bytes() == (pe if blob.kind == "pe" else pdb)


def test_zstd_materialization_preserves_crash_analysis_semantics(
    harness: Phase1Harness,
) -> None:
    def analyze(workspace_name: str, compression_mode: Literal["off", "active"]):
        registered, _pe, _pdb = _publish_one_pair(
            harness,
            workspace_name=workspace_name,
            compression_mode=compression_mode,
        )
        completed = harness.upload_dump(
            registered["publication"]["workspace_id"],
            dump_bytes(20260827),
            reported_build_id=registered["build_id"],
        )
        occurrence_id = completed["occurrence_id"]
        detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
        canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()
        return detail, canonical

    identity_detail, identity = analyze("payload-analysis-identity", "off")
    zstd_detail, zstd = analyze("payload-analysis-zstd", "active")

    assert identity_detail["current_analysis"]["status"] == "COMPLETE"
    assert zstd_detail["current_analysis"]["status"] == "COMPLETE"
    assert zstd["crash"] == identity["crash"]
    assert zstd["threads"] == identity["threads"]
    assert [
        {key: value for key, value in module.items() if key != "artifact_ids"}
        for module in zstd["modules"]
    ] == [
        {key: value for key, value in module.items() if key != "artifact_ids"}
        for module in identity["modules"]
    ]
    assert zstd["quality"] == identity["quality"]
    assert zstd["fingerprints"] == identity["fingerprints"]


def test_delivery_v2_verifies_wire_and_logical_identity_before_analysis(
    harness: Phase1Harness,
) -> None:
    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "active"
    harness.settings.artifact_blob_compression_mode = "active"
    workspace = harness.create_workspace("delivery-v2-analysis")
    debug_id = "D0D0D0D0D0D0D0D0D0D0D0D0D0D0D0D01"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="2.0.0",
        client_id="local:delivery-v2",
        modules=[("app.exe", "app.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)

    compressor = zstandard.ZstdCompressor(level=6, write_checksum=True, write_content_size=True)
    for expected, raw in zip(body["artifacts"], (pe, pdb), strict=True):
        wire = compressor.compress(raw)
        initialized = harness.client.post(
            f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries-v2:init",
            json={
                "file_kind": expected["kind"],
                "filename": expected["logical_name"],
                "logical": {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                "wire": {
                    "encoding": "zstd-v1",
                    "size": len(wire),
                    "sha256": hashlib.sha256(wire).hexdigest(),
                },
            },
        )
        assert initialized.status_code == 201, initialized.text
        upload = initialized.json()
        assert upload["wire_encoding"] == "zstd-v1"
        assert upload["wire_size"] == len(wire)
        harness._seed_upload(upload["upload_id"], wire)
        completed_upload = harness.client.post(
            f"/api/v1/uploads/{upload['upload_id']}/complete"
        )
        assert completed_upload.status_code == 200
        harness.drain()
        terminal = harness.client.get(f"/api/v1/uploads/{upload['upload_id']}").json()
        assert terminal["verification_status"] == "ACCEPTED"
        assert terminal["sha256"] == hashlib.sha256(raw).hexdigest()

    completed = harness.upload_dump(
        workspace["id"],
        dump_bytes(20260828),
        reported_build_id=registered["build_id"],
    )
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()
    assert detail["current_analysis"]["status"] == "COMPLETE"
    assert canonical["threads"][0]["frames"][0]["function"] == "crashcap::fake_crash"
    assert canonical["modules"][0]["status"] == "matched"
    assert canonical["fingerprints"]["exact"]


def test_delivery_v2_identity_pdb_records_bounded_fallback_metric(
    harness: Phase1Harness,
) -> None:
    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "active"
    harness.settings.artifact_blob_compression_mode = "active"
    workspace = harness.create_workspace("delivery-v2-identity-fallback")
    debug_id = "D1D1D1D1D1D1D1D1D1D1D1D1D1D1D1D11"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="2.0.1",
        client_id="local:delivery-v2-identity-fallback",
        modules=[("app.exe", "app.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    expected = next(item for item in body["artifacts"] if item["kind"] == "pdb")
    labels = {
        "contract": "delivery-v2",
        "kind": "pdb",
        "reason": "client_identity",
    }
    before = REGISTRY.get_sample_value(
        "crashcap_artifact_delivery_fallbacks_total", labels
    ) or 0.0

    response = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries-v2:init",
        json={
            "file_kind": "pdb",
            "filename": expected["logical_name"],
            "logical": {"size": len(pdb), "sha256": hashlib.sha256(pdb).hexdigest()},
            "wire": {
                "encoding": "identity",
                "size": len(pdb),
                "sha256": hashlib.sha256(pdb).hexdigest(),
            },
        },
    )

    assert response.status_code == 201, response.text
    assert (
        REGISTRY.get_sample_value("crashcap_artifact_delivery_fallbacks_total", labels)
        == before + 1
    )


def test_delivery_v2_rejects_corrupt_wire_and_forged_logical_identity(
    harness: Phase1Harness,
) -> None:
    harness.settings.build_publications_enabled = True
    harness.settings.artifact_blob_dedup_mode = "active"
    workspace = harness.create_workspace("delivery-v2-rejection")
    debug_id = "E0E0E0E0E0E0E0E0E0E0E0E0E0E0E0E01"
    pe, pdb = pe_bytes(debug_id), pdb_bytes(debug_id)
    body = _publication(
        version="2.0.0",
        client_id="local:delivery-v2-rejection",
        modules=[("app.exe", "app.pdb", "entrypoint", pe, pdb)],
    )
    registered = _register(harness, workspace["id"], body)
    expected = body["artifacts"][0]
    wire = zstandard.ZstdCompressor(
        level=6, write_checksum=True, write_content_size=True
    ).compress(pe)
    request = {
        "file_kind": expected["kind"],
        "filename": expected["logical_name"],
        "logical": {"size": len(pe), "sha256": hashlib.sha256(pe).hexdigest()},
        "wire": {
            "encoding": "zstd-v1",
            "size": len(wire),
            "sha256": hashlib.sha256(wire).hexdigest(),
        },
    }
    initialized = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries-v2:init", json=request
    ).json()
    corrupted = bytearray(wire)
    corrupted[-1] ^= 1
    harness._seed_upload(initialized["upload_id"], bytes(corrupted))
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete")
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{initialized['upload_id']}").json()
    assert terminal["verification_status"] == "REJECTED"
    assert terminal["rejection_reason"] == "wire_sha256_mismatch"

    forged = dict(request)
    forged["logical"] = {"size": len(pe), "sha256": "0" * 64}
    response = harness.client.post(
        f"/api/v1/builds/{registered['build_id']}/artifacts/deliveries-v2:init", json=forged
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ARTIFACT_CONTENT_MISMATCH"
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(ArtifactBlob).where(ArtifactBlob.sha256 == "0" * 64)) is None
