from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import zstandard
from crashcap_api.models import ArtifactBlob
from crashcap_api.services.artifact_payloads import (
    PAYLOAD_FORMAT_VERSION,
    ArtifactBlobCodec,
    ArtifactPayloadError,
    BlobMaterializer,
)
from crashcap_api.storage import LocalObjectStore
from prometheus_client import REGISTRY


def _blob(key: str, raw: bytes, payload: bytes, encoding: str) -> ArtifactBlob:
    return ArtifactBlob(
        id="abl_test",
        workspace_id="wsp_test",
        sha256=hashlib.sha256(raw).hexdigest(),
        kind="pdb",
        size=len(raw),
        object_key=key,
        payload_encoding=encoding,
        payload_size=len(payload),
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_object_key=key,
        payload_format_version=PAYLOAD_FORMAT_VERSION,
        verification_status="verified",
    )


@pytest.mark.parametrize("encoding", ["identity", "zstd-v1"])
def test_codec_round_trip_and_atomic_output(tmp_path: Path, encoding: str) -> None:
    raw = b"Microsoft C/C++ MSF 7.00\r\n" + (b"symbols-and-lines\0" * 200_000)
    source = tmp_path / "source.pdb"
    encoded = tmp_path / "payload"
    decoded = tmp_path / "decoded.pdb"
    source.write_bytes(raw)

    result = ArtifactBlobCodec().encode_file(
        source,
        encoded,
        kind="pdb",
        encoding=encoding,  # type: ignore[arg-type]
        expected_raw_size=len(raw),
        expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
    )
    ArtifactBlobCodec().decode_file(
        encoded,
        decoded,
        kind="pdb",
        encoding=encoding,  # type: ignore[arg-type]
        expected_raw_size=len(raw),
        expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
    )

    assert decoded.read_bytes() == raw
    assert result.payload_size == encoded.stat().st_size
    if encoding == "zstd-v1":
        assert result.payload_size < result.raw_size // 10
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("mutation", ["truncated", "trailing", "checksum"])
def test_zstd_rejects_corrupt_payload_without_output(tmp_path: Path, mutation: str) -> None:
    raw = b"a" * 2_000_000
    source = tmp_path / "source.pdb"
    encoded = tmp_path / "payload"
    decoded = tmp_path / "decoded.pdb"
    source.write_bytes(raw)
    ArtifactBlobCodec().encode_file(source, encoded, kind="pdb", encoding="zstd-v1")
    payload = bytearray(encoded.read_bytes())
    if mutation == "truncated":
        del payload[-4:]
    elif mutation == "trailing":
        payload.extend(b"not-a-frame")
    else:
        payload[-1] ^= 0x01
    encoded.write_bytes(payload)

    with pytest.raises(ArtifactPayloadError):
        ArtifactBlobCodec().decode_file(
            encoded,
            decoded,
            kind="pdb",
            encoding="zstd-v1",
            expected_raw_size=len(raw),
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        )
    assert not decoded.exists()


def test_zstd_rejects_additional_frame_via_logical_size(tmp_path: Path) -> None:
    raw = b"logical-payload" * 50
    encoded = tmp_path / "payload"
    encoded.write_bytes(
        zstandard.ZstdCompressor(write_checksum=True, write_content_size=True).compress(raw)
        + zstandard.ZstdCompressor(write_checksum=True, write_content_size=True).compress(b"extra")
    )

    with pytest.raises(ArtifactPayloadError, match="size"):
        ArtifactBlobCodec().decode_file(
            encoded,
            tmp_path / "decoded.pdb",
            kind="pdb",
            encoding="zstd-v1",
            expected_raw_size=len(raw),
            expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        )


def test_materializer_verifies_stored_and_raw_hashes(tmp_path: Path) -> None:
    raw = b"PDB" + b"x" * 100_000
    source = tmp_path / "source.pdb"
    source.write_bytes(raw)
    encoded = tmp_path / "encoded"
    digest = ArtifactBlobCodec().encode_file(source, encoded, kind="pdb", encoding="zstd-v1")
    store = LocalObjectStore(tmp_path / "objects")
    store.put_file("artifact-blobs-v2/wsp_test/aa/hash/zstd-v1", encoded, "application/zstd")
    blob = _blob(
        "artifact-blobs-v2/wsp_test/aa/hash/zstd-v1",
        raw,
        encoded.read_bytes(),
        "zstd-v1",
    )
    destination = tmp_path / "materialized.pdb"

    result = BlobMaterializer(store, tmp_path / "tasks").materialize(blob, destination)

    assert destination.read_bytes() == raw
    assert result.payload_sha256 == digest.payload_sha256
    temp_count = REGISTRY.get_sample_value(
        "crashcap_artifact_payload_temp_bytes_count",
        {"operation": "materialize", "kind": "pdb", "encoding": "zstd-v1"},
    )
    assert temp_count is not None and temp_count >= 1

    store.put_bytes(blob.payload_object_key, encoded.read_bytes() + b"x", "application/zstd")
    failure_labels = {
        "operation": "materialize",
        "encoding": "zstd-v1",
        "reason": "payload_size_mismatch",
    }
    before = REGISTRY.get_sample_value(
        "crashcap_artifact_payload_failures_total", failure_labels
    ) or 0.0
    with pytest.raises(ArtifactPayloadError, match="size"):
        BlobMaterializer(store, tmp_path / "tasks").materialize(blob, destination)
    after = REGISTRY.get_sample_value(
        "crashcap_artifact_payload_failures_total", failure_labels
    )
    assert after == before + 1


def test_codec_rejects_insufficient_temp_capacity_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdb"
    destination = tmp_path / "encoded.pdb.zst"
    source.write_bytes(b"PDB" * 1024)
    monkeypatch.setattr(
        "crashcap_api.services.artifact_payloads.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )

    with pytest.raises(ArtifactPayloadError) as captured:
        ArtifactBlobCodec().encode_file(
            source,
            destination,
            kind="pdb",
            encoding="zstd-v1",
        )

    assert captured.value.code == "temp_capacity_insufficient"
    assert not destination.exists()
    assert not list(tmp_path.glob("*.partial"))
