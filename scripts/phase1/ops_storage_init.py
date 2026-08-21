#!/usr/bin/env python3
"""Bootstrap the Phase 1 private RustFS bucket through standard S3 APIs.

The command never calls a RustFS management API. It creates/repairs a private
bucket and installs SSE-S3 (AES256) default encryption. Retention is
workspace-aware and therefore remains an application/operation concern; this
script deliberately does not install a global lifecycle rule that could delete
an object before a workspace-specific retention policy permits it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")


def plain_http_endpoint(value: str) -> bool:
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme == "http"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def parse_cors_allowed_origins(value: str) -> list[str]:
    origins = [item.strip() for item in value.split(",") if item.strip()]
    if not origins:
        raise ValueError("S3_CORS_ALLOWED_ORIGINS must list at least one HTTP frontend origin")
    normalized: list[str] = []
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ValueError(
                "S3_CORS_ALLOWED_ORIGINS entries must be exact HTTP origins "
                "without wildcard/userinfo/path/query/fragment"
            )
        normalized_origin = f"http://{parsed.netloc}"
        if normalized_origin not in normalized:
            normalized.append(normalized_origin)
    return normalized


def read_secret(file_var: str, value_var: str) -> str:
    path_value = os.environ.get(file_var)
    if path_value:
        path = Path(path_value)
        try:
            value = path.read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError) as exc:
            raise SystemExit(f"cannot read external secret file for {file_var}") from exc
        if value:
            return value
        raise SystemExit(f"external secret file for {file_var} is empty")
    value = os.environ.get(value_var, "")
    if value:
        return value
    raise SystemExit(f"set {file_var} (preferred) or {value_var} outside the repository")


def make_client() -> Any:
    try:
        import boto3
        from botocore.client import Config
    except ImportError as exc:  # pragma: no cover - depends on operator environment
        raise SystemExit(
            "ops_storage_init.py --apply requires boto3 (install the S3 adapter requirements)"
        ) from exc
    endpoint = os.environ.get("S3_ENDPOINT", "")
    if not plain_http_endpoint(endpoint):
        raise SystemExit("S3_ENDPOINT must use http:// with a host and no userinfo/query/fragment")
    bucket = os.environ.get("S3_BUCKET", "crashcap-private")
    if not BUCKET_RE.fullmatch(bucket):
        raise SystemExit("S3_BUCKET is not a valid S3 bucket name")
    access_key = read_secret("S3_ACCESS_KEY_FILE", "AWS_ACCESS_KEY_ID")
    secret_key = read_secret("S3_SECRET_KEY_FILE", "AWS_SECRET_ACCESS_KEY")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def apply_bucket_policy(client: Any, bucket: str, cors_origins: list[str]) -> None:
    """Apply the idempotent private/encrypted/browser-upload bucket policy."""

    client.put_bucket_acl(Bucket=bucket, ACL="private")
    client.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256",
                    }
                }
            ]
        },
    )
    client.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": cors_origins,
                    "AllowedMethods": ["GET", "HEAD", "PUT"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 300,
                }
            ]
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the idempotent S3 bootstrap")
    args = parser.parse_args()

    bucket = os.environ.get("S3_BUCKET", "crashcap-private")
    if not BUCKET_RE.fullmatch(bucket):
        print("ERROR: S3_BUCKET is not a valid S3 bucket name", file=sys.stderr)
        return 2
    if not args.apply:
        print("Storage bootstrap plan: PASS")
        print(
            "Would ensure a private bucket, default SSE-S3 (AES256), and exact HTTP CORS origins."
        )
        print("No network call made; workspace-specific retention remains application-owned.")
        return 0

    try:
        from botocore.exceptions import ClientError
    except ImportError as exc:  # pragma: no cover - guarded by make_client
        raise SystemExit("ops_storage_init.py --apply requires botocore") from exc
    try:
        cors_origins = parse_cors_allowed_origins(os.environ.get("S3_CORS_ALLOWED_ORIGINS", ""))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    client = make_client()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            raise SystemExit("cannot inspect the configured private bucket") from exc
        client.create_bucket(Bucket=bucket, ACL="private")
    # Repair every property even when an operator is re-running this command
    # after a manual S3-compatible migration or a RustFS restore.
    apply_bucket_policy(client, bucket, cors_origins)
    # Do not print endpoint, access key, secret, request IDs or presigned URLs.
    print(
        "Storage bootstrap: PASS "
        f"(private bucket, SSE-S3/AES256, {len(cors_origins)} HTTP CORS origin(s): {bucket})"
    )
    print("Retention was not changed; use the workspace-aware retention worker/runbook.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
