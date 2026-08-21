#!/usr/bin/env python3
"""Delete exactly one RustFS object from the local operator workstation.

This is intentionally not an API endpoint and has no prefix/delete-recursive
mode. A dry-run is the default; applying a deletion needs both ``--apply`` and
an exact ``--confirm 'DELETE <object-key>'`` phrase plus a reason. The operator
must reconcile the local audit record with the platform operation log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

KEY_RE = re.compile(
    r"^(?:raw-builds|sym-unified|dump-blobs|analysis|uploads)/"
    r"wsp_[A-Za-z0-9_-]{1,96}/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$"
)


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


def secret(file_var: str, value_var: str) -> str:
    path_value = os.environ.get(file_var)
    if path_value:
        try:
            value = Path(path_value).read_text(encoding="utf-8").splitlines()[0].strip()
        except (OSError, IndexError) as exc:
            raise SystemExit(f"cannot read external secret file for {file_var}") from exc
        if value:
            return value
    value = os.environ.get(value_var, "")
    if value:
        return value
    raise SystemExit(f"set {file_var} or {value_var} outside the repository")


def s3_client() -> Any:
    try:
        import boto3
        from botocore.client import Config
    except ImportError as exc:  # pragma: no cover - depends on operator environment
        raise SystemExit(
            "ops_emergency_delete.py --apply requires boto3 (install the S3 adapter requirements)"
        ) from exc
    endpoint = os.environ.get("S3_ENDPOINT", "")
    if not plain_http_endpoint(endpoint):
        raise SystemExit("S3_ENDPOINT must use http:// with a host and no userinfo/query/fragment")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        aws_access_key_id=secret("S3_ACCESS_KEY_FILE", "AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret("S3_SECRET_KEY_FILE", "AWS_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def safe_audit_path(path: Path) -> Path:
    resolved = path.resolve()
    repo = Path(__file__).resolve().parents[2]
    if resolved == repo or repo in resolved.parents:
        raise SystemExit("audit log must be outside the repository")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET", "crashcap-private"))
    parser.add_argument("--object-key", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--audit-log", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", help="must equal DELETE <object-key> when --apply is used")
    args = parser.parse_args()

    key = args.object_key
    if not KEY_RE.fullmatch(key) or ".." in key or key.endswith("/"):
        print(
            "ERROR: object key must be one exact workspace-scoped Phase 1 object",
            file=sys.stderr,
        )
        return 2
    if not args.reason.strip() or len(args.reason) > 500:
        print(
            "ERROR: provide a concise deletion reason (1..500 characters)",
            file=sys.stderr,
        )
        return 2
    if not args.apply:
        print(f"Emergency deletion plan: PASS (one object only: {key})")
        print(
            "No S3 request made. Re-run with --apply and the exact confirmation phrase to delete."
        )
        return 0
    expected = f"DELETE {key}"
    if args.confirm != expected:
        print("ERROR: exact confirmation phrase did not match object key", file=sys.stderr)
        return 2
    if args.audit_log is None:
        print(
            "ERROR: --audit-log outside the repository is required for --apply",
            file=sys.stderr,
        )
        return 2
    try:
        from botocore.exceptions import ClientError
    except ImportError as exc:  # pragma: no cover - guarded by s3_client
        raise SystemExit("ops_emergency_delete.py --apply requires botocore") from exc
    audit_path = safe_audit_path(args.audit_log)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    bucket = args.bucket
    client = s3_client()
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            print("ERROR: target object was not found; nothing deleted", file=sys.stderr)
            return 1
        raise SystemExit("cannot verify target object") from exc
    client.delete_object(Bucket=bucket, Key=key)
    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"404", "NoSuchKey", "NotFound"}:
            raise SystemExit("delete was issued but post-delete verification failed") from exc
    else:
        raise SystemExit("delete was issued but the object is still visible")
    event = {
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "actor": "local-operator",
        "action": "emergency_delete",
        "target": key,
        "bucket": bucket,
        "reason": args.reason,
        "result": "deleted",
    }
    with audit_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    print("Emergency deletion: PASS (target verified absent; audit event written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
