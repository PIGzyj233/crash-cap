from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_s3.type_defs import CompletedPartTypeDef

from .config import Settings


class ObjectNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class ObjectHead:
    size: int
    etag: str | None
    metadata: dict[str, str]


@dataclass(frozen=True)
class PresignedUpload:
    method: str
    url: str
    headers: dict[str, str]
    expires_in: int
    multipart_upload_id: str | None = None
    parts: tuple[dict[str, object], ...] = ()


class ObjectStore(Protocol):
    def presign_put(self, key: str, size: int, content_type: str) -> PresignedUpload: ...

    def complete_multipart(
        self, key: str, multipart_upload_id: str, parts: Sequence[dict[str, object]]
    ) -> None: ...

    def presign_get(self, key: str) -> str: ...

    def head(self, key: str) -> ObjectHead: ...

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]: ...

    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None: ...

    def put_file(self, key: str, path: Path, content_type: str) -> None: ...

    def copy(self, source_key: str, destination_key: str) -> None: ...

    def download_file(self, key: str, destination: Path) -> None: ...

    def delete(self, key: str) -> None: ...


def _safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts or "\\" in key or "\x00" in key:
        raise ValueError("unsafe object key")
    return key


class LocalObjectStore:
    """Explicit test double; production configuration cannot select it accidentally."""

    def __init__(self, root: Path, put_ttl: int = 3600, get_ttl: int = 300) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.put_ttl = put_ttl
        self.get_ttl = get_ttl

    def path_for(self, key: str) -> Path:
        candidate = (self.root / _safe_key(key)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("object key escaped local store root")
        return candidate

    def presign_put(self, key: str, size: int, content_type: str) -> PresignedUpload:
        del size
        return PresignedUpload(
            method="PUT",
            url=f"local-object-store://put/{quote(_safe_key(key), safe='/')}",
            headers={"Content-Type": content_type},
            expires_in=self.put_ttl,
        )

    def complete_multipart(
        self, key: str, multipart_upload_id: str, parts: Sequence[dict[str, object]]
    ) -> None:
        del key, multipart_upload_id, parts
        raise ValueError("local object-store test double does not use multipart uploads")

    def presign_get(self, key: str) -> str:
        return f"local-object-store://get/{quote(_safe_key(key), safe='/')}?ttl={self.get_ttl}"

    def head(self, key: str) -> ObjectHead:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        size = path.stat().st_size
        digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()  # noqa: S324
        return ObjectHead(size=size, etag=digest, metadata={})

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        path = self.path_for(key)
        if not path.is_file():
            raise ObjectNotFoundError(key)
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                yield chunk

    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None:
        del content_type
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        del content_type
        destination = self.path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)

    def copy(self, source_key: str, destination_key: str) -> None:
        source = self.path_for(source_key)
        if not source.is_file():
            raise ObjectNotFoundError(source_key)
        destination = self.path_for(destination_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def download_file(self, key: str, destination: Path) -> None:
        source = self.path_for(key)
        if not source.is_file():
            raise ObjectNotFoundError(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def delete(self, key: str) -> None:
        path = self.path_for(key)
        path.unlink(missing_ok=True)


class S3ObjectStore:
    MULTIPART_THRESHOLD = 64 * 1024 * 1024
    PART_SIZE = 64 * 1024 * 1024

    def __init__(self, settings: Settings) -> None:
        config = Config(signature_version="s3v4", s3={"addressing_style": "path"})
        access_key = settings.s3_access_key.get_secret_value()
        secret_key = settings.s3_secret_key.get_secret_value()
        self.client: S3Client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=settings.s3_region,
            config=config,
        )
        public_endpoint = settings.s3_public_endpoint_url or settings.s3_endpoint_url
        self.presign_client: S3Client = boto3.client(
            "s3",
            endpoint_url=public_endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=settings.s3_region,
            config=config,
        )
        self.bucket = settings.s3_bucket
        self.sse = settings.s3_sse
        self.put_ttl = settings.presign_put_ttl_seconds
        self.get_ttl = settings.presign_get_ttl_seconds

    def presign_put(self, key: str, size: int, content_type: str) -> PresignedUpload:
        key = _safe_key(key)
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentType": content_type,
            "ServerSideEncryption": self.sse,
        }
        headers = {
            "Content-Type": content_type,
            "x-amz-server-side-encryption": self.sse,
        }
        if size <= self.MULTIPART_THRESHOLD:
            url = self.presign_client.generate_presigned_url(
                "put_object", Params=params, ExpiresIn=self.put_ttl
            )
            return PresignedUpload("PUT", url, headers, self.put_ttl)

        response = self.client.create_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            ContentType=content_type,
            ServerSideEncryption=self.sse,
        )
        upload_id = str(response["UploadId"])
        part_count = (size + self.PART_SIZE - 1) // self.PART_SIZE
        parts: list[dict[str, object]] = []
        for part_number in range(1, part_count + 1):
            url = self.presign_client.generate_presigned_url(
                "upload_part",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": part_number,
                },
                ExpiresIn=self.put_ttl,
            )
            parts.append({"part_number": part_number, "url": url})
        return PresignedUpload(
            "PUT",
            "",
            headers,
            self.put_ttl,
            multipart_upload_id=upload_id,
            parts=tuple(parts),
        )

    def complete_multipart(
        self, key: str, multipart_upload_id: str, parts: Sequence[dict[str, object]]
    ) -> None:
        normalized: list[CompletedPartTypeDef] = []
        for part in parts:
            part_number = part["part_number"]
            if not isinstance(part_number, int):
                raise ValueError("multipart part_number must be an integer")
            normalized.append({"PartNumber": part_number, "ETag": str(part["etag"])})
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=_safe_key(key),
            UploadId=multipart_upload_id,
            MultipartUpload={"Parts": normalized},
        )

    def presign_get(self, key: str) -> str:
        return str(
            self.presign_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": _safe_key(key)},
                ExpiresIn=self.get_ttl,
            )
        )

    def head(self, key: str) -> ObjectHead:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise ObjectNotFoundError(key) from error
            raise
        return ObjectHead(
            size=int(response["ContentLength"]),
            etag=str(response.get("ETag", "")).strip('"') or None,
            metadata={str(key): str(value) for key, value in response.get("Metadata", {}).items()},
        )

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise ObjectNotFoundError(key) from error
            raise
        body = response["Body"]
        try:
            while chunk := body.read(chunk_size):
                yield bytes(chunk)
        finally:
            body.close()

    def put_bytes(self, key: str, payload: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=_safe_key(key),
            Body=payload,
            ContentType=content_type,
            ServerSideEncryption=self.sse,
        )

    def put_file(self, key: str, path: Path, content_type: str) -> None:
        with path.open("rb") as handle:
            self.client.upload_fileobj(
                handle,
                self.bucket,
                _safe_key(key),
                ExtraArgs={"ContentType": content_type, "ServerSideEncryption": self.sse},
            )

    def copy(self, source_key: str, destination_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            Key=_safe_key(destination_key),
            CopySource={"Bucket": self.bucket, "Key": _safe_key(source_key)},
            ServerSideEncryption=self.sse,
        )

    def download_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, _safe_key(key), str(destination))
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                raise ObjectNotFoundError(key) from error
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=_safe_key(key))


def create_object_store(settings: Settings) -> ObjectStore:
    if settings.object_store_backend == "local":
        if settings.environment != "test":
            raise ValueError("local object store is restricted to explicit test settings")
        return LocalObjectStore(
            settings.object_store_local_root,
            settings.presign_put_ttl_seconds,
            settings.presign_get_ttl_seconds,
        )
    return S3ObjectStore(settings)


def stream_sha256(store: ObjectStore, key: str) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    total = 0
    prefix = bytearray()
    for chunk in store.stream(key):
        digest.update(chunk)
        total += len(chunk)
        if len(prefix) < 4096:
            prefix.extend(chunk[: 4096 - len(prefix)])
    return digest.hexdigest(), total, bytes(prefix)


def put_json(store: ObjectStore, key: str, payload: object) -> None:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    store.put_bytes(key, data, "application/json")
