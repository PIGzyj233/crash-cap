from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import zstandard
from crashcap_api.services.artifact_payloads import (
    ArtifactBlobCodec,
    ArtifactPayloadError,
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
