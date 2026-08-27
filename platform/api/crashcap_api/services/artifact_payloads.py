from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Literal, cast

import zstandard

from ..metrics import (
    ARTIFACT_MATERIALIZATION_SECONDS,
    ARTIFACT_MATERIALIZATIONS,
    ARTIFACT_PAYLOAD_BYTES,
    ARTIFACT_PAYLOAD_CODEC_SECONDS,
    ARTIFACT_PAYLOAD_FAILURES,
    ARTIFACT_PAYLOAD_RATIO,
    ARTIFACT_PAYLOAD_TEMP_BYTES,
)
from ..models import ArtifactBlob
from ..storage import ObjectHead, ObjectNotFoundError, ObjectStore

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
            ARTIFACT_PAYLOAD_FAILURES.labels(
                "encode", encoding, _failure_reason(error)
            ).inc()
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
            ARTIFACT_PAYLOAD_FAILURES.labels(
                "decode", encoding, _failure_reason(error)
            ).inc()
            raise


class BlobMaterializer:
    """The only supported ArtifactBlob payload-to-file reader."""

    def __init__(
        self, store: ObjectStore, temp_root: Path, codec: ArtifactBlobCodec | None = None
    ) -> None:
        self.store = store
        self.temp_root = temp_root
        self.codec = codec or ArtifactBlobCodec()

    def payload_head(self, blob: ArtifactBlob) -> ObjectHead:
        head = self.store.head(_payload_key(blob))
        if head.size != _payload_size(blob):
            raise ArtifactPayloadError(
                "payload_size_mismatch", "stored Artifact payload size differs from PostgreSQL"
            )
        return head

    def payload_exists(self, blob: ArtifactBlob) -> bool:
        try:
            self.payload_head(blob)
            return True
        except (ObjectNotFoundError, ArtifactPayloadError):
            return False

    def materialize(self, blob: ArtifactBlob, destination: Path) -> PayloadDigest:
        started = time.monotonic()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        encoding = _payload_encoding(blob)
        payload_size = _payload_size(blob)
        payload_sha256 = _payload_sha256(blob)
        if payload_size <= 0 or payload_size > _payload_hard_limit(blob.kind, encoding):
            raise ArtifactPayloadError(
                "payload_size_limit_exceeded", "stored payload size is invalid"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        _require_free_space(self.temp_root, payload_size + blob.size)
        _require_free_space(destination.parent, blob.size)
        try:
            with tempfile.TemporaryDirectory(
                prefix=f"materialize-{blob.id}-", dir=self.temp_root
            ) as raw:
                root = Path(raw)
                stored_path = root / "payload"
                digest = hashlib.sha256()
                observed_size = 0
                with stored_path.open("wb") as stored:
                    for chunk in self.store.stream(_payload_key(blob), STREAM_CHUNK_SIZE):
                        observed_size += len(chunk)
                        if observed_size > payload_size:
                            raise ArtifactPayloadError(
                                "payload_size_mismatch",
                                "stored payload exceeds its declared size",
                            )
                        digest.update(chunk)
                        stored.write(chunk)
                if observed_size != payload_size:
                    raise ArtifactPayloadError(
                        "payload_size_mismatch", "stored payload is shorter than its declared size"
                    )
                observed_sha256 = digest.hexdigest()
                if observed_sha256 != payload_sha256:
                    raise ArtifactPayloadError(
                        "payload_sha256_mismatch", "stored payload hash differs from PostgreSQL"
                    )
                self.codec.decode_file(
                    stored_path,
                    destination,
                    kind=blob.kind,
                    encoding=encoding,
                    expected_raw_size=blob.size,
                    expected_raw_sha256=blob.sha256,
                )
            result = PayloadDigest(
                encoding=encoding,
                raw_size=blob.size,
                raw_sha256=blob.sha256,
                payload_size=payload_size,
                payload_sha256=payload_sha256,
            )
            ARTIFACT_MATERIALIZATIONS.labels(encoding, "success").inc()
            ARTIFACT_MATERIALIZATION_SECONDS.labels(encoding, blob.kind, "success").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_TEMP_BYTES.labels("materialize", blob.kind, encoding).observe(
                payload_size + blob.size
            )
            return result
        except Exception as error:
            ARTIFACT_MATERIALIZATIONS.labels(encoding, "failed").inc()
            ARTIFACT_MATERIALIZATION_SECONDS.labels(encoding, blob.kind, "failed").observe(
                time.monotonic() - started
            )
            ARTIFACT_PAYLOAD_FAILURES.labels(
                "materialize", encoding, _failure_reason(error)
            ).inc()
            raise


def configure_identity_payload(blob: ArtifactBlob) -> None:
    blob.payload_encoding = IDENTITY_ENCODING
    blob.payload_size = blob.size
    blob.payload_sha256 = blob.sha256.lower()
    blob.payload_object_key = blob.object_key
    blob.payload_verified_at = blob.verified_at
    blob.payload_format_version = PAYLOAD_FORMAT_VERSION


def configure_zstd_payload(
    blob: ArtifactBlob, *, object_key: str, payload: PayloadDigest, verified_at: Any
) -> None:
    if payload.encoding != ZSTD_ENCODING:
        raise ArtifactPayloadError("unsupported_encoding", "compressed payload must use zstd-v1")
    if payload.raw_size != blob.size or payload.raw_sha256 != blob.sha256.lower():
        raise ArtifactPayloadError(
            "raw_identity_mismatch", "compressed payload does not match the Artifact Blob identity"
        )
    blob.payload_encoding = ZSTD_ENCODING
    blob.payload_size = payload.payload_size
    blob.payload_sha256 = payload.payload_sha256
    blob.payload_object_key = object_key
    blob.payload_verified_at = verified_at
    blob.payload_format_version = PAYLOAD_FORMAT_VERSION


def payload_head_valid(store: ObjectStore, blob: ArtifactBlob) -> bool:
    try:
        expected_size = _payload_size(blob)
        if store.head(_payload_key(blob)).size != expected_size:
            return False
        digest = hashlib.sha256()
        observed_size = 0
        for chunk in store.stream(_payload_key(blob), STREAM_CHUNK_SIZE):
            observed_size += len(chunk)
            if observed_size > expected_size:
                return False
            digest.update(chunk)
        return observed_size == expected_size and digest.hexdigest() == _payload_sha256(blob)
    except (ObjectNotFoundError, ArtifactPayloadError):
        return False


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


def artifact_blob_snapshot(blob: ArtifactBlob) -> dict[str, Any]:
    return {
        "id": blob.id,
        "workspace_id": blob.workspace_id,
        "sha256": blob.sha256,
        "kind": blob.kind,
        "size": blob.size,
        "object_key": blob.object_key,
        "payload_encoding": _payload_encoding(blob),
        "payload_size": _payload_size(blob),
        "payload_sha256": _payload_sha256(blob),
        "payload_object_key": _payload_key(blob),
        "payload_format_version": blob.payload_format_version or PAYLOAD_FORMAT_VERSION,
    }


def artifact_blob_from_snapshot(value: dict[str, Any]) -> ArtifactBlob:
    return ArtifactBlob(
        id=str(value["id"]),
        workspace_id=str(value["workspace_id"]),
        sha256=str(value["sha256"]),
        kind=str(value["kind"]),
        size=int(value["size"]),
        object_key=str(value["object_key"]),
        payload_encoding=str(value["payload_encoding"]),
        payload_size=int(value["payload_size"]),
        payload_sha256=str(value["payload_sha256"]),
        payload_object_key=str(value["payload_object_key"]),
        payload_format_version=str(value["payload_format_version"]),
        verification_status="verified",
    )


def payload_object_key(blob: ArtifactBlob) -> str:
    return _payload_key(blob)


def _payload_encoding(blob: ArtifactBlob) -> PayloadEncoding:
    value = blob.payload_encoding or IDENTITY_ENCODING
    if value not in {IDENTITY_ENCODING, ZSTD_ENCODING}:
        raise ArtifactPayloadError("unsupported_encoding", "unknown Artifact payload encoding")
    return value


def _payload_key(blob: ArtifactBlob) -> str:
    return blob.payload_object_key or blob.object_key


def _payload_size(blob: ArtifactBlob) -> int:
    return int(blob.payload_size or blob.size)


def _payload_sha256(blob: ArtifactBlob) -> str:
    return str(blob.payload_sha256 or blob.sha256).lower()


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
