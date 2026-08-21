"""A deliberately small, replaceable adapter over the standard S3 contract.

No service-management or vendor extension calls belong here.  The qualification
runner depends on this surface so that the same tests can be run against another
S3-compatible endpoint by changing only the endpoint and credentials.
"""

from __future__ import annotations

import hashlib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class HttpResult:
    """Bounded result for an unauthenticated or pre-signed HTTP request."""

    status: int
    headers: Mapping[str, str]
    body: bytes


class S3Adapter:
    """Standard S3 operations used by the Phase 0 qualification suite."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        ca_bundle: str | None = None,
    ) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            verify=ca_bundle or True,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @property
    def client(self) -> Any:
        """Expose the standards-based SDK client to contract-level tests only."""

        return self._client

    def create_bucket(self, bucket: str) -> Mapping[str, Any]:
        return self._client.create_bucket(Bucket=bucket)

    def delete_bucket(self, bucket: str) -> Mapping[str, Any]:
        return self._client.delete_bucket(Bucket=bucket)

    def put_object(
        self,
        *,
        bucket: str,
        key: str,
        body: bytes | bytearray | Iterable[bytes],
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        return self._client.put_object(Bucket=bucket, Key=key, Body=body, **kwargs)

    def head_object(self, *, bucket: str, key: str) -> Mapping[str, Any]:
        return self._client.head_object(Bucket=bucket, Key=key)

    def get_object(self, *, bucket: str, key: str, **kwargs: Any) -> Mapping[str, Any]:
        return self._client.get_object(Bucket=bucket, Key=key, **kwargs)

    def delete_object(self, *, bucket: str, key: str) -> Mapping[str, Any]:
        return self._client.delete_object(Bucket=bucket, Key=key)

    def list_objects(self, *, bucket: str, prefix: str = "") -> Mapping[str, Any]:
        return self._client.list_objects_v2(Bucket=bucket, Prefix=prefix)

    def get_bucket_acl(self, *, bucket: str) -> Mapping[str, Any]:
        return self._client.get_bucket_acl(Bucket=bucket)

    def put_bucket_lifecycle(self, *, bucket: str, rules: list[Mapping[str, Any]]) -> Mapping[str, Any]:
        return self._client.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration={"Rules": rules},
        )

    def get_bucket_lifecycle(self, *, bucket: str) -> Mapping[str, Any]:
        return self._client.get_bucket_lifecycle_configuration(Bucket=bucket)

    def put_bucket_encryption(
        self,
        *,
        bucket: str,
        algorithm: str = "AES256",
    ) -> Mapping[str, Any]:
        return self._client.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": algorithm,
                        }
                    }
                ]
            },
        )

    def get_bucket_encryption(self, *, bucket: str) -> Mapping[str, Any]:
        return self._client.get_bucket_encryption(Bucket=bucket)

    def create_multipart(self, *, bucket: str, key: str) -> Mapping[str, Any]:
        return self._client.create_multipart_upload(Bucket=bucket, Key=key)

    def upload_part(
        self,
        *,
        bucket: str,
        key: str,
        upload_id: str,
        part_number: int,
        body: bytes,
    ) -> Mapping[str, Any]:
        return self._client.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
        )

    def complete_multipart(
        self,
        *,
        bucket: str,
        key: str,
        upload_id: str,
        parts: list[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        return self._client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def abort_multipart(self, *, bucket: str, key: str, upload_id: str) -> Mapping[str, Any]:
        return self._client.abort_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
        )

    def list_multipart(self, *, bucket: str, prefix: str = "") -> Mapping[str, Any]:
        return self._client.list_multipart_uploads(Bucket=bucket, Prefix=prefix)

    def generate_presigned_url(
        self,
        operation: str,
        *,
        bucket: str,
        key: str,
        expires_in: int,
        method: str | None = None,
    ) -> str:
        params = {"Bucket": bucket, "Key": key}
        return self._client.generate_presigned_url(
            operation,
            Params=params,
            ExpiresIn=expires_in,
            HttpMethod=method,
        )


def stream_sha256(body: Any, *, chunk_size: int = 64 * 1024) -> tuple[str, int, int]:
    """Hash a streaming S3 response without calling ``read()``.

    Returns ``(hex_digest, byte_count, max_chunk_size)``.  The helper accepts
    botocore ``StreamingBody`` and a tiny iterable test double, making the
    no-whole-object-read contract directly testable.
    """

    digest = hashlib.sha256()
    byte_count = 0
    max_chunk_size = 0
    chunks = body.iter_chunks(chunk_size=chunk_size)
    for chunk in chunks:
        if not chunk:
            continue
        digest.update(chunk)
        byte_count += len(chunk)
        max_chunk_size = max(max_chunk_size, len(chunk))
    return digest.hexdigest(), byte_count, max_chunk_size


def http_request(
    url: str,
    *,
    method: str,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = 15.0,
    ca_bundle: str | None = None,
) -> HttpResult:
    """Issue a bounded request without following redirects or leaking its URL."""

    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers or {}),
        method=method,
    )
    context = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else None
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return HttpResult(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(4096),
            )
    except urllib.error.HTTPError as exc:
        return HttpResult(
            status=exc.code,
            headers=dict(exc.headers.items()),
            body=exc.read(4096),
        )
    except urllib.error.URLError as exc:
        reason = str(exc.reason).encode("utf-8", errors="replace")[:512]
        return HttpResult(status=0, headers={}, body=reason)
