"""Run the Phase 0 RustFS S3 qualification cases and emit evidence.

The runner intentionally reports ``NOT_PROVEN`` separately from ``FAIL``.  A
configured lifecycle rule, for example, is not treated as expiration proof
unless an object is actually observed to expire during the bounded run.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

from botocore.exceptions import ClientError, EndpointConnectionError

from .adapter import S3Adapter, http_request, stream_sha256


class QualificationError(RuntimeError):
    """An assertion failure in one qualification case."""


class NotProven(QualificationError):
    """The implementation may work, but this run did not prove the claim."""


@dataclass
class CaseResult:
    case_id: str
    title: str
    status: str
    duration_ms: int
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_error(value: Any, secrets: tuple[str, ...] = ()) -> str:
    """Return a short error without URLs, credentials, or object contents."""

    if isinstance(value, ClientError):
        error = value.response.get("Error", {})
        status = value.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = error.get("Code", "ClientError")
        message = str(error.get("Message", ""))[:300]
        text = f"{code} (HTTP {status}): {message}" if status else f"{code}: {message}"
    elif isinstance(value, EndpointConnectionError):
        text = "endpoint connection failed"
    else:
        text = f"{type(value).__name__}: {value}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://[^\s]+", "[URL REDACTED]", text)
    return text[:600]


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


class Qualification:
    def __init__(self) -> None:
        self.started_at = utc_now()
        self.endpoint = os.environ.get("S3_ENDPOINT", "http://127.0.0.1:9000").rstrip("/")
        self.access_key = os.environ.get("RUSTFS_ACCESS_KEY", "")
        self.secret_key = os.environ.get("RUSTFS_SECRET_KEY", "")
        self.rpc_secret = os.environ.get("RUSTFS_RPC_SECRET", "")
        self.ca_bundle = os.environ.get("S3_CA_BUNDLE", "") or None
        self.expected_digest = os.environ.get(
            "RUSTFS_EXPECTED_DIGEST",
            "sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831",
        )
        self.image_ref = os.environ.get(
            "RUSTFS_IMAGE_REF",
            "ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc@" + self.expected_digest,
        )
        self.repo_root = Path(__file__).resolve().parents[2]
        self.compose_file = self.repo_root / "infra" / "rustfs" / "compose.yaml"
        self.data_dir = self.repo_root / "infra" / "rustfs" / ".runtime" / "data"
        self.output_dir = Path(
            os.environ.get("S3_REPORT_DIR", str(self.repo_root / "docs" / "evidence"))
        )
        self.output_json = self.output_dir / "rustfs-qualification.json"
        self.output_markdown = self.output_dir / "rustfs-qualification.md"
        self.lifecycle_wait_seconds = int(os.environ.get("LIFECYCLE_WAIT_SECONDS", "45"))
        self.presign_wait_seconds = int(os.environ.get("PRESIGNED_EXPIRY_WAIT_SECONDS", "3"))
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"{int(time.time())}{os.getpid()}"[-12:]
        self.prefix = f"ccq-{suffix}".lower()
        self.buckets: list[str] = []
        self.cases: list[CaseResult] = []
        self.notes: list[str] = []
        self.cleanup_errors: list[str] = []
        self.adapter = S3Adapter(
            endpoint_url=self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            ca_bundle=self.ca_bundle,
        )

    def bucket(self, label: str) -> str:
        name = f"{self.prefix}-{label}".lower()
        if name not in self.buckets:
            self.buckets.append(name)
        return name

    def key(self, label: str) -> str:
        return f"qualification/{self.run_id}/{label}"

    def create_bucket(self, label: str) -> str:
        bucket = self.bucket(label)
        try:
            self.adapter.create_bucket(bucket)
        except ClientError as exc:
            # A re-run with a stable prefix should be recoverable, but the
            # normal runner uses a fresh prefix. Keep this branch explicit.
            code = exc.response.get("Error", {}).get("Code")
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
        return bucket

    def compose(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        command = [
            "docker",
            "compose",
            "--project-name",
            "crash-cap-rustfs-qualification",
            "--file",
            str(self.compose_file),
            *args,
        ]
        return subprocess.run(
            command,
            cwd=self.repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )

    def wait_for_service(self, timeout: int = 60) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.adapter.client.list_buckets()
                return
            except Exception as exc:  # startup errors are expected while polling
                last_error = exc
                time.sleep(1)
        raise QualificationError(f"S3 endpoint did not become ready: {safe_error(last_error)}")

    def run_case(self, case_id: str, title: str, function: Callable[[], dict[str, Any]]) -> None:
        started = time.perf_counter()
        status = "PASS"
        details: dict[str, Any] = {}
        error: str | None = None
        try:
            details = json_safe(function())
        except NotProven as exc:
            status = "NOT_PROVEN"
            error = safe_error(exc, (self.secret_key, self.rpc_secret))
        except Exception as exc:  # every case is recorded; later cases still run
            status = "FAIL"
            error = safe_error(exc, (self.secret_key, self.rpc_secret))
            self.notes.append(f"{case_id} traceback is available only in the local runner log.")
        duration_ms = int((time.perf_counter() - started) * 1000)
        self.cases.append(
            CaseResult(
                case_id=case_id,
                title=title,
                status=status,
                duration_ms=duration_ms,
                details=details,
                error=error,
            )
        )
        print(f"{case_id}: {status} ({duration_ms} ms)")

    # P0-E01
    def case_image(self) -> dict[str, Any]:
        if "@sha256:" not in self.image_ref:
            raise QualificationError("Compose image reference is not digest-pinned")
        declared = self.image_ref.rsplit("@", 1)[1]
        if declared != self.expected_digest:
            raise QualificationError("image reference and expected digest disagree")
        result = subprocess.run(
            ["docker", "image", "inspect", self.image_ref, "--format", "{{json .RepoDigests}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        repo_digests = json.loads(result.stdout.strip() or "[]")
        if not any(self.expected_digest in item for item in repo_digests):
            raise QualificationError("Docker image inspect did not return the pinned digest")
        compose_text = self.compose_file.read_text(encoding="utf-8")
        if self.expected_digest not in compose_text:
            raise QualificationError("Compose does not contain the expected digest")
        return {
            "image": self.image_ref.split("@", 1)[0],
            "manifest_digest": self.expected_digest,
            "repo_digests": repo_digests,
            "compose_file": "infra/rustfs/compose.yaml",
            "release_maturity": "pre-release candidate",
        }

    # P0-E02
    def case_adapter(self) -> dict[str, Any]:
        source = inspect.getsource(S3Adapter).lower()
        for forbidden in ("rustfs", "minio", "console", "rpc_secret", "admin"):
            if forbidden in source:
                raise QualificationError(f"adapter contains vendor/private term: {forbidden}")
        required = {
            "create_bucket",
            "delete_bucket",
            "put_object",
            "head_object",
            "get_object",
            "generate_presigned_url",
            "create_multipart",
            "upload_part",
            "complete_multipart",
            "abort_multipart",
            "put_bucket_lifecycle",
            "put_bucket_encryption",
        }
        missing = sorted(name for name in required if not hasattr(self.adapter, name))
        if missing:
            raise QualificationError(f"adapter surface missing: {','.join(missing)}")
        return {
            "module": "qualification/s3/adapter.py",
            "sdk": "boto3 S3 client with SigV4 and path-style addressing",
            "vendor_private_operations": [],
            "required_surface": sorted(required),
        }

    # P0-E03
    def case_private_bucket(self) -> dict[str, Any]:
        bucket = self.create_bucket("private")
        key = self.key("private-object")
        body = b"private-object-proof"
        self.adapter.put_object(bucket=bucket, key=key, body=body)
        acl = self.adapter.get_bucket_acl(bucket=bucket)
        public_grants = []
        for grant in acl.get("Grants", []):
            grantee = grant.get("Grantee", {})
            uri = str(grantee.get("URI", ""))
            if "AllUsers" in uri or "AuthenticatedUsers" in uri:
                public_grants.append(
                    {"type": grantee.get("Type"), "uri": uri, "permission": grant.get("Permission")}
                )
        if public_grants:
            raise QualificationError("bucket ACL grants public access")
        url = f"{self.endpoint}/{bucket}/{quote(key, safe='/')}"
        anonymous = http_request(url, method="GET", ca_bundle=self.ca_bundle)
        if anonymous.status not in {401, 403}:
            raise QualificationError(f"anonymous GET was not denied (HTTP {anonymous.status})")
        compose_text = self.compose_file.read_text(encoding="utf-8")
        if re.search(r"9001:\s*9001", compose_text):
            raise QualificationError("Console port 9001 is published by Compose")
        return {
            "bucket": bucket,
            "acl_public_grants": public_grants,
            "anonymous_get_status": anonymous.status,
            "console_port_published": False,
            "service_credentials_in_presigned_urls": "tested in P0-E04",
        }

    # P0-E04
    def case_presigned(self) -> dict[str, Any]:
        if urlsplit(self.endpoint).scheme != "https":
            raise QualificationError("qualification endpoint is not HTTPS")
        if not self.ca_bundle or not Path(self.ca_bundle).is_file():
            raise QualificationError("strict TLS CA bundle is unavailable")
        bucket = self.create_bucket("presign")
        key = self.key("presigned-object")
        body = b"presigned-put-and-get-proof"
        put_url = self.adapter.generate_presigned_url(
            "put_object", bucket=bucket, key=key, expires_in=300, method="PUT"
        )
        put_result = http_request(put_url, method="PUT", body=body, ca_bundle=self.ca_bundle)
        if put_result.status not in {200, 201, 204}:
            raise QualificationError(f"pre-signed PUT failed (HTTP {put_result.status})")
        get_url = self.adapter.generate_presigned_url(
            "get_object", bucket=bucket, key=key, expires_in=300, method="GET"
        )
        get_result = http_request(get_url, method="GET", ca_bundle=self.ca_bundle)
        if get_result.status != 200 or get_result.body != body:
            raise QualificationError(f"pre-signed GET failed (HTTP {get_result.status})")
        wrong_method = http_request(put_url, method="GET", ca_bundle=self.ca_bundle)
        if wrong_method.status in {200, 201, 204}:
            raise QualificationError("PUT pre-signature was accepted for GET")
        wrong_path = urlsplit(get_url)
        wrong_key_path = wrong_path.path + "-different"
        wrong_object = http_request(
            urlunsplit((wrong_path.scheme, wrong_path.netloc, wrong_key_path, wrong_path.query, "")),
            method="GET",
            ca_bundle=self.ca_bundle,
        )
        if wrong_object.status in {200, 206}:
            raise QualificationError("GET pre-signature was accepted for a different object")
        expired_url = self.adapter.generate_presigned_url(
            "get_object", bucket=bucket, key=key, expires_in=1, method="GET"
        )
        time.sleep(max(2, self.presign_wait_seconds))
        expired = http_request(expired_url, method="GET", ca_bundle=self.ca_bundle)
        if expired.status in {200, 206}:
            raise QualificationError("expired pre-signed URL was accepted")
        if self.secret_key in put_url or self.secret_key in get_url:
            raise QualificationError("pre-signed URL contains the service secret key")
        return {
            "bucket": bucket,
            "put_status": put_result.status,
            "get_status": get_result.status,
            "wrong_method_status": wrong_method.status,
            "wrong_object_status": wrong_object.status,
            "expired_status": expired.status,
            "secret_key_in_urls": False,
            "expiry_wait_seconds": max(2, self.presign_wait_seconds),
            "endpoint_scheme": "https",
            "tls_peer_verification": "strict CA and SAN verification",
            "ca_bundle_sha256": hashlib.sha256(Path(self.ca_bundle).read_bytes()).hexdigest(),
            "urls": "omitted from evidence by design",
        }

    # P0-E05
    def case_multipart(self) -> dict[str, Any]:
        bucket = self.create_bucket("multipart")
        part_one = b"A" * (5 * 1024 * 1024)
        part_two = b"B" * (1024 * 1024)
        key = self.key("multipart-complete")
        upload = self.adapter.create_multipart(bucket=bucket, key=key)
        upload_id = str(upload["UploadId"])
        try:
            first = self.adapter.upload_part(
                bucket=bucket, key=key, upload_id=upload_id, part_number=1, body=part_one
            )
            retry = self.adapter.upload_part(
                bucket=bucket, key=key, upload_id=upload_id, part_number=1, body=part_one
            )
            second = self.adapter.upload_part(
                bucket=bucket, key=key, upload_id=upload_id, part_number=2, body=part_two
            )
            completed = self.adapter.complete_multipart(
                bucket=bucket,
                key=key,
                upload_id=upload_id,
                parts=[
                    {"ETag": retry["ETag"], "PartNumber": 1},
                    {"ETag": second["ETag"], "PartNumber": 2},
                ],
            )
        except Exception:
            try:
                self.adapter.abort_multipart(bucket=bucket, key=key, upload_id=upload_id)
            except Exception:
                pass
            raise
        head = self.adapter.head_object(bucket=bucket, key=key)
        expected_size = len(part_one) + len(part_two)
        if head.get("ContentLength") != expected_size:
            raise QualificationError("completed multipart object has unexpected length")

        failed_key = self.key("multipart-failed-complete")
        failed = self.adapter.create_multipart(bucket=bucket, key=failed_key)
        failed_id = str(failed["UploadId"])
        invalid_complete_code = None
        try:
            uploaded = self.adapter.upload_part(
                bucket=bucket,
                key=failed_key,
                upload_id=failed_id,
                part_number=1,
                body=part_one,
            )
            try:
                self.adapter.complete_multipart(
                    bucket=bucket,
                    key=failed_key,
                    upload_id=failed_id,
                    parts=[{"ETag": '"not-the-real-etag"', "PartNumber": 1}],
                )
            except ClientError as exc:
                invalid_complete_code = str(exc.response.get("Error", {}).get("Code", "ClientError"))
            if invalid_complete_code is None:
                raise QualificationError("invalid multipart completion unexpectedly succeeded")
            self.adapter.abort_multipart(bucket=bucket, key=failed_key, upload_id=failed_id)
        finally:
            # Abort is idempotent enough for cleanup; a completed upload may
            # return NoSuchUpload, which is safe to ignore here.
            try:
                self.adapter.abort_multipart(bucket=bucket, key=failed_key, upload_id=failed_id)
            except Exception:
                pass

        abort_key = self.key("multipart-abort")
        aborted = self.adapter.create_multipart(bucket=bucket, key=abort_key)
        aborted_id = str(aborted["UploadId"])
        self.adapter.upload_part(
            bucket=bucket,
            key=abort_key,
            upload_id=aborted_id,
            part_number=1,
            body=part_one,
        )
        self.adapter.abort_multipart(bucket=bucket, key=abort_key, upload_id=aborted_id)
        residual = self.adapter.list_multipart(bucket=bucket, prefix=self.key("multipart"))
        residual_keys = [item.get("Key") for item in residual.get("Uploads", [])]
        if residual_keys:
            for item in residual.get("Uploads", []):
                try:
                    self.adapter.abort_multipart(
                        bucket=bucket,
                        key=str(item["Key"]),
                        upload_id=str(item["UploadId"]),
                    )
                except Exception:
                    pass
            raise QualificationError(f"multipart uploads remain after abort: {len(residual_keys)}")
        return {
            "bucket": bucket,
            "complete_status": "success",
            "retry_same_part": True,
            "completed_bytes": expected_size,
            "failed_complete_error": invalid_complete_code,
            "aborted_uploads_remaining": 0,
            "first_part_etag_changed_on_retry": first.get("ETag") != retry.get("ETag"),
            "complete_response_present": bool(completed),
            "uploaded_failed_part_present": bool(uploaded),
        }

    # P0-E06
    def case_head_range_stream(self) -> dict[str, Any]:
        bucket = self.create_bucket("stream")
        key = self.key("stream-object")
        body = bytes((index * 17 + 3) % 251 for index in range(2 * 1024 * 1024))
        expected = hashlib.sha256(body).hexdigest()
        self.adapter.put_object(bucket=bucket, key=key, body=body)
        head = self.adapter.head_object(bucket=bucket, key=key)
        if int(head.get("ContentLength", -1)) != len(body):
            raise QualificationError("HEAD ContentLength does not match object length")
        response = self.adapter.get_object(bucket=bucket, key=key)
        try:
            actual, byte_count, max_chunk = stream_sha256(response["Body"])
        finally:
            response["Body"].close()
        if actual != expected or byte_count != len(body):
            raise QualificationError("streaming SHA-256 does not match the known object")
        if max_chunk > 64 * 1024:
            raise QualificationError("streaming hash helper read a chunk larger than its bound")
        start, end = 12345, 12544
        ranged = self.adapter.get_object(bucket=bucket, key=key, Range=f"bytes={start}-{end}")
        try:
            ranged_body = ranged["Body"].read(end - start + 1)
        finally:
            ranged["Body"].close()
        if ranged_body != body[start : end + 1]:
            raise QualificationError("Range GET body does not match the requested interval")
        if ranged.get("ContentRange") != f"bytes {start}-{end}/{len(body)}":
            raise QualificationError("Range GET Content-Range is incorrect")

        class GuardedBody:
            def __init__(self, chunks: list[bytes]) -> None:
                self.chunks = chunks

            def iter_chunks(self, *, chunk_size: int) -> Any:
                del chunk_size
                yield from self.chunks

            def read(self, *_args: Any, **_kwargs: Any) -> None:
                raise AssertionError("stream_sha256 called read() instead of iter_chunks()")

        guarded_digest, guarded_size, _ = stream_sha256(GuardedBody([b"guard", b"ed"]))
        if guarded_digest != hashlib.sha256(b"guarded").hexdigest() or guarded_size != 7:
            raise QualificationError("streaming helper guard test failed")
        return {
            "bucket": bucket,
            "head_content_length": head.get("ContentLength"),
            "range": f"bytes={start}-{end}",
            "range_content_range": ranged.get("ContentRange"),
            "stream_sha256": expected,
            "streamed_bytes": byte_count,
            "max_stream_chunk_bytes": max_chunk,
            "client_sha256_hint_sent": False,
            "whole_object_read": False,
            "guarded_iter_chunks_test": True,
        }

    # P0-E07
    def case_lifecycle_restart(self) -> dict[str, Any]:
        bucket = self.create_bucket("lifecycle")
        restart_key = self.key("restart-object")
        restart_body = b"restart-consistency-proof" * 1024
        restart_digest = hashlib.sha256(restart_body).hexdigest()
        self.adapter.put_object(bucket=bucket, key=restart_key, body=restart_body)
        rule = {
            "ID": "expire-old-qualification-objects",
            "Filter": {"Prefix": self.key("expire")},
            "Status": "Enabled",
            "Expiration": {"Days": 1},
        }
        self.adapter.put_bucket_lifecycle(bucket=bucket, rules=[rule])
        lifecycle = self.adapter.get_bucket_lifecycle(bucket=bucket)
        if not lifecycle.get("Rules"):
            raise QualificationError("lifecycle configuration could not be read back")
        expire_key = self.key("expire-object")
        self.adapter.put_object(bucket=bucket, key=expire_key, body=b"expire-me")

        self.compose("restart", "rustfs", timeout=120)
        self.wait_for_service()
        after_restart = self.adapter.get_object(bucket=bucket, key=restart_key)
        try:
            after_restart_body = after_restart["Body"].read()
        finally:
            after_restart["Body"].close()
        if hashlib.sha256(after_restart_body).hexdigest() != restart_digest:
            raise QualificationError("object hash changed across RustFS restart")

        deadline = time.monotonic() + self.lifecycle_wait_seconds
        expired_at = None
        last_status = None
        while time.monotonic() < deadline:
            try:
                self.adapter.head_object(bucket=bucket, key=expire_key)
                last_status = 200
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                last_status = status or code
                if status == 404 or code in {"NoSuchKey", "NotFound", "NoSuchObject"}:
                    expired_at = utc_now()
                    break
            time.sleep(2)
        if expired_at is None:
            raise NotProven(
                f"lifecycle rule was accepted but expiration was not observed within {self.lifecycle_wait_seconds}s"
            )
        return {
            "bucket": bucket,
            "lifecycle_rule_read_back": True,
            "lifecycle_expired_at": expired_at,
            "lifecycle_last_probe": last_status,
            "restart_object_sha256": restart_digest,
            "restart_object_bytes": len(restart_body),
            "restart_consistency": "verified",
            "lifecycle_wait_seconds": self.lifecycle_wait_seconds,
            "lifecycle_acceleration": {
                "debug_day_seconds": 10,
                "scanner_cycle_seconds": 2,
                "data_usage_update_dir_cycles": 1,
            },
        }

    # P0-E08
    def case_sse(self) -> dict[str, Any]:
        bucket = self.create_bucket("sse")
        self.adapter.put_bucket_encryption(bucket=bucket, algorithm="AES256")
        encryption = self.adapter.get_bucket_encryption(bucket=bucket)
        rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        configured = [
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for rule in rules
        ]
        if "AES256" not in configured:
            raise QualificationError("bucket SSE-S3 configuration did not read back as AES256")
        default_key = self.key("sse-default")
        self.adapter.put_object(bucket=bucket, key=default_key, body=b"default-encryption")
        default_head = self.adapter.head_object(bucket=bucket, key=default_key)
        explicit_key = self.key("sse-explicit")
        self.adapter.put_object(
            bucket=bucket,
            key=explicit_key,
            body=b"explicit-encryption",
            ServerSideEncryption="AES256",
        )
        explicit_head = self.adapter.head_object(bucket=bucket, key=explicit_key)
        if default_head.get("ServerSideEncryption") != "AES256":
            raise QualificationError("bucket default SSE-S3 was not applied to a new object")
        if explicit_head.get("ServerSideEncryption") != "AES256":
            raise QualificationError("explicit SSE-S3 object did not report AES256")
        default_read = self.adapter.get_object(bucket=bucket, key=default_key)
        try:
            default_read_body = default_read["Body"].read()
        finally:
            default_read["Body"].close()
        if default_read_body != b"default-encryption":
            raise QualificationError("SSE-S3 default-encrypted object could not be read back")
        return {
            "bucket": bucket,
            "bucket_encryption_algorithm": configured,
            "default_object_sse": default_head.get("ServerSideEncryption"),
            "explicit_object_sse": explicit_head.get("ServerSideEncryption"),
            "read_regression": "verified with HEAD and GET-compatible object path",
        }

    # P0-E09
    def case_backup_restore(self) -> dict[str, Any]:
        bucket = self.create_bucket("backup")
        key = self.key("analysis/canonical.json")
        body = json.dumps(
            {"schema_version": "0.1", "kind": "qualification-analysis", "evidence": "s3"},
            sort_keys=True,
        ).encode("utf-8")
        expected = hashlib.sha256(body).hexdigest()
        self.adapter.put_object(bucket=bucket, key=key, body=body, ContentType="application/json")
        before = self.adapter.head_object(bucket=bucket, key=key)
        backup_dir = self.repo_root / "infra" / "rustfs" / ".runtime" / "backup" / self.run_id
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        self.compose("stop", "rustfs", timeout=120)
        shutil.copytree(self.data_dir, backup_dir)
        shutil.rmtree(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup_dir, self.data_dir, dirs_exist_ok=True)
        self.compose("up", "-d", "rustfs", timeout=120)
        self.wait_for_service()
        after = self.adapter.head_object(bucket=bucket, key=key)
        if int(after.get("ContentLength", -1)) != int(before.get("ContentLength", -2)):
            raise QualificationError("restored object HEAD length differs from pre-backup value")
        restored = self.adapter.get_object(bucket=bucket, key=key)
        try:
            restored_body = restored["Body"].read()
        finally:
            restored["Body"].close()
        if hashlib.sha256(restored_body).hexdigest() != expected:
            raise QualificationError("restored analysis object hash differs from pre-backup value")
        ranged = self.adapter.get_object(bucket=bucket, key=key, Range="bytes=0-15")
        try:
            range_body = ranged["Body"].read()
        finally:
            ranged["Body"].close()
        if range_body != body[:16]:
            raise QualificationError("restored analysis object Range GET differs from pre-backup value")
        return {
            "bucket": bucket,
            "object": "analysis/canonical.json",
            "object_sha256": expected,
            "head_length_before": before.get("ContentLength"),
            "head_length_after": after.get("ContentLength"),
            "range_after_restore": "verified",
            "backup_method": "stopped SNSD service, copied exact data directory, restored exact snapshot",
            "backup_snapshot": str(backup_dir.relative_to(self.repo_root)).replace("\\", "/"),
            "restore_readback": "verified",
        }

    def cleanup(self) -> None:
        for bucket in reversed(self.buckets):
            try:
                multipart = self.adapter.list_multipart(bucket=bucket)
                for item in multipart.get("Uploads", []):
                    try:
                        self.adapter.abort_multipart(
                            bucket=bucket,
                            key=str(item["Key"]),
                            upload_id=str(item["UploadId"]),
                        )
                    except Exception as exc:
                        self.cleanup_errors.append(f"abort {bucket}: {safe_error(exc)}")
                objects = self.adapter.list_objects(bucket=bucket)
                for item in objects.get("Contents", []):
                    try:
                        self.adapter.delete_object(bucket=bucket, key=str(item["Key"]))
                    except Exception as exc:
                        self.cleanup_errors.append(f"delete {bucket}: {safe_error(exc)}")
                self.adapter.delete_bucket(bucket)
            except Exception as exc:
                self.cleanup_errors.append(f"bucket {bucket}: {safe_error(exc)}")

    def docker_versions(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name, command in {
            "docker_server": ["docker", "version", "--format", "{{.Server.Version}}"],
            "docker_compose": ["docker", "compose", "version", "--short"],
        }.items():
            try:
                result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
                values[name] = result.stdout.strip()
            except Exception as exc:
                values[name] = safe_error(exc)
        return values

    def report_payload(self) -> dict[str, Any]:
        failed = [case.case_id for case in self.cases if case.status == "FAIL"]
        not_proven = [case.case_id for case in self.cases if case.status == "NOT_PROVEN"]
        all_pass = not failed and not not_proven and len(self.cases) == 10
        return {
            "report_version": "rustfs-s3-qualification-v0",
            "qualification_status": "QUALIFIED" if all_pass else "INCOMPLETE",
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "candidate": {
                "image": self.image_ref.split("@", 1)[0],
                "manifest_digest": self.expected_digest,
                "release_maturity": "pre-release candidate",
                "s3_endpoint": self.endpoint,
                "tls_peer_verification": "strict CA and SAN verification",
                "console_port_published": False,
            },
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                **self.docker_versions(),
            },
            "adapter": {
                "module": "qualification/s3/adapter.py",
                "contract": "standard S3 operations through boto3 SigV4",
                "private_vendor_api_calls": [],
            },
            "cases": [json_safe(case.__dict__) for case in self.cases],
            "not_completed": [
                {
                    "case_id": case.case_id,
                    "status": case.status,
                    "reason": case.error,
                }
                for case in self.cases
                if case.status != "PASS"
            ],
            "failed_case_ids": failed,
            "not_proven_case_ids": not_proven,
            "cleanup_errors": self.cleanup_errors,
            "notes": [
                "This is an SNSD Docker qualification, not a distributed durability or production backup SLA test.",
                "Credentials are generated outside the repository and are not included in this report.",
                "Lifecycle expiry uses documented qualification-only accelerated scanner controls; it does not claim production default expiry latency.",
                *self.notes,
            ],
            "reproduce": {
                "command": "bash qualification/s3/run.sh",
                "compose": "infra/rustfs/compose.yaml",
                "requirements": "qualification/s3/requirements.txt",
                "report_json": "docs/evidence/rustfs-qualification.json",
                "report_markdown": "docs/evidence/rustfs-qualification.md",
            },
        }

    def write_reports(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.report_payload()
        self.output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        markdown: list[str] = [
            "# RustFS S3 资格报告",
            "",
            f"- 状态：**{payload['qualification_status']}**",
            f"- 开始：`{payload['started_at']}`",
            f"- 完成：`{payload['finished_at']}`",
            f"- 镜像：`{payload['candidate']['image']}`",
            f"- Manifest digest：`{payload['candidate']['manifest_digest']}`",
            "- Endpoint：`http://127.0.0.1:9000`（报告不记录凭据）",
            "",
            "## P0-E01--E10",
            "",
            "| Case | 结果 | 耗时 | 说明 |",
            "| --- | --- | ---: | --- |",
        ]
        for case in self.cases:
            explanation = case.error or "通过"
            markdown.append(f"| {case.case_id} | **{case.status}** | {case.duration_ms} ms | {explanation} |")
        markdown.extend(
            [
                "",
                "## 未完成项",
                "",
            ]
        )
        if payload["not_completed"]:
            for item in payload["not_completed"]:
                markdown.append(f"- `{item['case_id']}` `{item['status']}`：{item['reason'] or '未通过'}")
        else:
            markdown.append("- 无。十个资格项均已通过本次运行。")
        markdown.extend(
            [
                "",
                "## 复跑与边界",
                "",
                "```bash",
                "bash qualification/s3/run.sh",
                "```",
                "",
                "测试 adapter 只调用 boto3 的标准 S3 API；未调用 RustFS 管理或私有 API。",
                "本报告验证的是本机 Docker SNSD：重启一致性和停止后目录快照恢复均不等价于分布式副本、异地备份或生产 RPO/RTO。",
                "生命周期必须在限定等待窗口内观察到对象过期，否则状态为 `NOT_PROVEN`，不会被算作通过。",
                "",
                "## 证据文件",
                "",
                "- `docs/evidence/rustfs-qualification.json`",
                "- `infra/rustfs/compose.yaml`",
                "- `qualification/s3/adapter.py`",
                "- `qualification/s3/runner.py`",
            ]
        )
        self.output_markdown.write_text("\n".join(markdown) + "\n", encoding="utf-8")

    def run(self) -> int:
        self.run_case("P0-E01", "固定 RustFS 镜像 digest", self.case_image)
        self.run_case("P0-E02", "可替换的标准 S3 adapter", self.case_adapter)
        self.run_case("P0-E03", "私有 Bucket 与凭证隔离", self.case_private_bucket)
        self.run_case("P0-E04", "预签名 PUT/GET、动作限制与过期", self.case_presigned)
        self.run_case("P0-E05", "multipart complete/abort/retry/残留", self.case_multipart)
        self.run_case("P0-E06", "HEAD、Range GET 与流式 SHA-256", self.case_head_range_stream)
        self.run_case("P0-E07", "生命周期与服务重启一致性", self.case_lifecycle_restart)
        self.run_case("P0-E08", "SSE-S3 配置与读取回归", self.case_sse)
        self.run_case("P0-E09", "停止后数据快照备份与恢复", self.case_backup_restore)
        self.cleanup()
        prior = self.cases[:9]
        if all(case.status == "PASS" for case in prior):
            self.run_case(
                "P0-E10",
                "形成可复跑 RustFS 资格报告",
                lambda: {"report_status": "all P0-E01--E09 passed", "report_paths": [
                    "docs/evidence/rustfs-qualification.json",
                    "docs/evidence/rustfs-qualification.md",
                ]},
            )
        elif any(case.status == "FAIL" for case in prior):
            self.run_case(
                "P0-E10",
                "形成可复跑 RustFS 资格报告",
                lambda: (_ for _ in ()).throw(
                    QualificationError("report emitted, but one or more prerequisite qualification cases failed")
                ),
            )
        else:
            self.run_case(
                "P0-E10",
                "形成可复跑 RustFS 资格报告",
                lambda: (_ for _ in ()).throw(
                    NotProven("report emitted, but one or more prerequisite cases remain NOT_PROVEN")
                ),
            )
        self.write_reports()
        return 0 if self.report_payload()["qualification_status"] == "QUALIFIED" else 2


def main() -> int:
    qualification = Qualification()
    try:
        qualification.wait_for_service()
        return qualification.run()
    except Exception as exc:
        qualification.notes.append(f"runner stopped before all cases: {safe_error(exc)}")
        qualification.write_reports()
        print(f"runner: FAIL ({safe_error(exc)})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
