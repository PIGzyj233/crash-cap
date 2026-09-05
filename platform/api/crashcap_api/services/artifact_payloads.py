from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, cast

import zstandard

from ..metrics import (
    ARTIFACT_PAYLOAD_BYTES,
    ARTIFACT_PAYLOAD_CODEC_SECONDS,
    ARTIFACT_PAYLOAD_FAILURES,
    ARTIFACT_PAYLOAD_RATIO,
    ARTIFACT_PAYLOAD_TEMP_BYTES,
)
from ..storage import ObjectNotFoundError

PayloadEncoding = Literal["identity", "zstd-v1"]

PAYLOAD_FORMAT_VERSION = "artifact-blob-payload-v1"
IDENTITY_ENCODING: PayloadEncoding = "identity"
ZSTD_ENCODING: PayloadEncoding = "zstd-v1"
ZSTD_LEVEL = 6
ZSTD_THREADS = 0
ZSTD_MAX_WINDOW_BYTES = 64 * 1024 * 1024
STREAM_CHUNK_SIZE = 1024 * 1024
TEMP_DISK_RESERVE_BYTES = 64 * 1024 * 1024
MAX_RAW_BYTES = {"pe": 512 * 1024 * 1024, "pdb": 2 * 1024 * 1024 * 1024}


class ArtifactPayloadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PayloadDigest:
    encoding: PayloadEncoding
    raw_size: int
    raw_sha256: str
    payload_size: int
    payload_sha256: str


class _BoundedHashWriter:
    def __init__(self, handle: BinaryIO, limit: int) -> None:
        self.handle = handle
        self.limit = limit
        self.size = 0
        self.digest = hashlib.sha256()

    def write(self, data: bytes) -> int:
        next_size = self.size + len(data)
        if next_size > self.limit:
            raise ArtifactPayloadError(
                "raw_size_limit_exceeded", "decoded Artifact raw size exceeds its hard limit"
            )
        written = self.handle.write(data)
        if written != len(data):
            raise ArtifactPayloadError(
                "short_write", "Artifact payload materialization was partial"
            )
        self.size = next_size
        self.digest.update(data)
        return written

    def flush(self) -> None:
        self.handle.flush()


class ArtifactBlobCodec:
    """Versioned, bounded streaming codec for canonical PE/PDB payloads."""

    def encode_file(
        self,
        source: Path,
        destination: Path,
        *,
        kind: str,
        encoding: PayloadEncoding,
        expected_raw_size: int | None = None,
        expected_raw_sha256: str | None = None,
    ) -> PayloadDigest:
        started = time.monotonic()
        limit = _kind_limit(kind)
        declared_size = source.stat().st_size
        if declared_size <= 0 or declared_size > limit:
            raise ArtifactPayloadError("raw_size_limit_exceeded", "raw Artifact size is invalid")
        if expected_raw_size is not None and declared_size != expected_raw_size:
            raise ArtifactPayloadError(
                "raw_size_mismatch", "raw Artifact size changed before encoding"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_free_space(
            destination.parent,
            declared_size + (STREAM_CHUNK_SIZE if encoding == ZSTD_ENCODING else 0),
        )
        raw_digest = hashlib.sha256()
        payload_digest = hashlib.sha256()
        raw_size = payload_size = 0
        partial = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
        partial.unlink(missing_ok=True)
        try:
            with source.open("rb") as raw, partial.open("wb") as stored:
                if encoding == IDENTITY_ENCODING:
                    while chunk := raw.read(STREAM_CHUNK_SIZE):
                        raw_size += len(chunk)
                        if raw_size > limit:
                            raise ArtifactPayloadError(
                                "raw_size_limit_exceeded", "raw Artifact exceeds its hard limit"
                            )
                        raw_digest.update(chunk)
                        payload_digest.update(chunk)
                        payload_size += stored.write(chunk)
                elif encoding == ZSTD_ENCODING:
                    compressor = zstandard.ZstdCompressor(
                        level=ZSTD_LEVEL,
                        write_checksum=True,
                        write_content_size=True,
                        threads=ZSTD_THREADS,
                    )
                    with compressor.stream_writer(
                        stored, size=declared_size, closefd=False
                    ) as encoded:
                        while chunk := raw.read(STREAM_CHUNK_SIZE):
                            raw_size += len(chunk)
                            if raw_size > limit:
                                raise ArtifactPayloadError(
                                    "raw_size_limit_exceeded", "raw Artifact exceeds its hard limit"
                                )
                            raw_digest.update(chunk)
                            encoded.write(chunk)
                    stored.flush()
                    with partial.open("rb") as verify_stored:
                        while chunk := verify_stored.read(STREAM_CHUNK_SIZE):
                            payload_digest.update(chunk)
                            payload_size += len(chunk)
                else:
                    raise ArtifactPayloadError(
                        "unsupported_encoding", "unknown Artifact payload encoding"
                    )
            raw_sha256 = raw_digest.hexdigest()
            if raw_size != declared_size:
                raise ArtifactPayloadError(
                    "raw_size_mismatch", "raw Artifact changed during encoding"
                )
            if expected_raw_sha256 is not None and raw_sha256 != expected_raw_sha256.lower():
                raise ArtifactPayloadError(
                    "raw_sha256_mismatch", "raw Artifact hash changed before encoding"
                )
            os.replace(partial, destination)
            result = PayloadDigest(
                encoding=encoding,
                raw_size=raw_size,
                raw_sha256=raw_sha256,
                payload_size=payload_size,
                payload_sha256=payload_digest.hexdigest(),
            )
            ARTIFACT_PAYLOAD_CODEC_SECONDS.labels("encode", encoding, "success").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_BYTES.labels(encoding, kind, "logical").inc(raw_size)
            ARTIFACT_PAYLOAD_BYTES.labels(encoding, kind, "stored").inc(payload_size)
            ARTIFACT_PAYLOAD_RATIO.labels(kind, encoding).observe(payload_size / raw_size)
            ARTIFACT_PAYLOAD_TEMP_BYTES.labels("encode", kind, encoding).observe(payload_size)
            return result
        except Exception as error:
            partial.unlink(missing_ok=True)
            ARTIFACT_PAYLOAD_CODEC_SECONDS.labels("encode", encoding, "failed").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_FAILURES.labels("encode", encoding, _failure_reason(error)).inc()
            raise

    def decode_file(
        self,
        source: Path,
        destination: Path,
        *,
        kind: str,
        encoding: PayloadEncoding,
        expected_raw_size: int,
        expected_raw_sha256: str,
    ) -> tuple[int, str]:
        started = time.monotonic()
        limit = _kind_limit(kind)
        if expected_raw_size <= 0 or expected_raw_size > limit:
            raise ArtifactPayloadError("raw_size_limit_exceeded", "declared raw size is invalid")
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_free_space(destination.parent, expected_raw_size)
        partial = destination.with_name(f".{destination.name}.{os.getpid()}.partial")
        partial.unlink(missing_ok=True)
        try:
            with source.open("rb") as stored, partial.open("wb") as raw:
                writer = _BoundedHashWriter(raw, min(limit, expected_raw_size))
                if encoding == IDENTITY_ENCODING:
                    while chunk := stored.read(STREAM_CHUNK_SIZE):
                        writer.write(chunk)
                elif encoding == ZSTD_ENCODING:
                    prefix = stored.read(18)
                    stored.seek(0)
                    try:
                        parameters = zstandard.get_frame_parameters(prefix)
                    except zstandard.ZstdError as error:
                        raise ArtifactPayloadError(
                            "zstd_frame_invalid", "stored payload is not a valid zstd-v1 frame"
                        ) from error
                    if parameters.content_size != expected_raw_size:
                        raise ArtifactPayloadError(
                            "zstd_content_size_mismatch",
                            "zstd-v1 frame content size differs from the logical Artifact size",
                        )
                    try:
                        decompressor = zstandard.ZstdDecompressor(
                            max_window_size=ZSTD_MAX_WINDOW_BYTES
                        )
                        with decompressor.stream_writer(
                            cast(BinaryIO, writer), closefd=False
                        ) as decoded:
                            while chunk := stored.read(STREAM_CHUNK_SIZE):
                                decoded.write(chunk)
                    except ArtifactPayloadError:
                        raise
                    except zstandard.ZstdError as error:
                        raise ArtifactPayloadError(
                            "zstd_decode_failed", "zstd-v1 payload is truncated or corrupt"
                        ) from error
                else:
                    raise ArtifactPayloadError(
                        "unsupported_encoding", "unknown Artifact payload encoding"
                    )
                writer.flush()
            raw_sha256 = writer.digest.hexdigest()
            if writer.size != expected_raw_size:
                raise ArtifactPayloadError(
                    "raw_size_mismatch", "decoded Artifact size differs from its logical size"
                )
            if raw_sha256 != expected_raw_sha256.lower():
                raise ArtifactPayloadError(
                    "raw_sha256_mismatch", "decoded Artifact hash differs from its logical hash"
                )
            os.replace(partial, destination)
            ARTIFACT_PAYLOAD_CODEC_SECONDS.labels("decode", encoding, "success").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_TEMP_BYTES.labels("decode", kind, encoding).observe(writer.size)
            return writer.size, raw_sha256
        except Exception as error:
            partial.unlink(missing_ok=True)
            ARTIFACT_PAYLOAD_CODEC_SECONDS.labels("decode", encoding, "failed").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_FAILURES.labels("decode", encoding, _failure_reason(error)).inc()
            raise


def _failure_reason(error: Exception) -> str:
    if isinstance(error, ArtifactPayloadError):
        return error.code
    if isinstance(error, ObjectNotFoundError):
        return "object_missing"
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, zstandard.ZstdError):
        return "zstd_error"
    return "unexpected_error"


def _require_free_space(path: Path, required_bytes: int) -> None:
    try:
        free_bytes = int(shutil.disk_usage(path).free)
    except OSError as error:
        raise ArtifactPayloadError(
            "temp_capacity_unknown", "temporary filesystem capacity could not be inspected"
        ) from error
    if free_bytes < required_bytes + TEMP_DISK_RESERVE_BYTES:
        raise ArtifactPayloadError(
            "temp_capacity_insufficient",
            "temporary filesystem lacks capacity for the bounded Artifact operation",
        )


def _kind_limit(kind: str) -> int:
    try:
        return MAX_RAW_BYTES[kind]
    except KeyError as error:
        raise ArtifactPayloadError(
            "unsupported_kind", "only PE/PDB payloads are supported"
        ) from error


def _payload_hard_limit(kind: str, encoding: PayloadEncoding) -> int:
    raw_limit = _kind_limit(kind)
    return raw_limit if encoding == IDENTITY_ENCODING else raw_limit + STREAM_CHUNK_SIZE
