"""Disposable loopback RustFS for browser QA; never reuse application storage."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

IMAGE = "ghcr.io/rustfs/rustfs@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831"


def docker(*args, env=None):
    return subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    ).stdout.strip()


@contextmanager
def owned_storage(output: Path, origin: str = "http://127.0.0.1:5189"):
    output.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    access, secret = "qa" + token, uuid4().hex + uuid4().hex
    env = dict(
        os.environ,
        RUSTFS_ACCESS_KEY=access,
        RUSTFS_SECRET_KEY=secret,
        RUSTFS_SSE_S3_MASTER_KEY=base64.b64encode(os.urandom(32)).decode(),
    )
    image_id = json.loads(docker("image", "inspect", IMAGE))[0]["Id"]
    container = docker(
        "run",
        "--pull=never",
        "-d",
        "--name",
        "qai-browser-storage-" + token,
        "--label",
        "crashcap.qai.browser-storage=" + token,
        "-p",
        "127.0.0.1::9000",
        "-e",
        "RUSTFS_ACCESS_KEY",
        "-e",
        "RUSTFS_SECRET_KEY",
        "-e",
        "RUSTFS_SSE_S3_MASTER_KEY",
        "-e",
        "RUSTFS_VOLUMES=/data",
        "-e",
        "RUSTFS_ADDRESS=0.0.0.0:9000",
        "-e",
        "RUSTFS_CONSOLE_ENABLE=false",
        image_id,
        env=env,
    )
    receipt = {
        "container_id": container,
        "owner_token": token,
        "image_id": image_id,
        "application_storage_touched": False,
        "removed": False,
    }
    client = None
    try:
        address = docker("port", container, "9000/tcp")
        assert address.startswith("127.0.0.1:")
        endpoint = "http://" + address
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 0},
                connect_timeout=2,
                read_timeout=2,
            ),
        )
        for _ in range(60):
            try:
                client.list_buckets()
                break
            except (EndpointConnectionError, ClientError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Owned RustFS did not become ready")
        bucket = "qai-browser-" + token
        client.create_bucket(Bucket=bucket)
        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": [origin],
                        "AllowedMethods": ["PUT", "GET", "HEAD"],
                        "AllowedHeaders": ["*"],
                        "ExposeHeaders": ["ETag"],
                        "MaxAgeSeconds": 600,
                    }
                ]
            },
        )
        receipt.update(endpoint=endpoint, bucket=bucket, origin=origin)
        (output / "storage.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        yield (
            {
                "object_store_backend": "s3",
                "s3_endpoint_url": endpoint,
                "s3_public_endpoint_url": endpoint,
                "s3_access_key": access,
                "s3_secret_key": secret,
                "s3_bucket": bucket,
            },
            client,
            receipt,
        )
    finally:
        if client is not None:
            client.close()
        assert (
            docker(
                "inspect",
                container,
                "--format",
                '{{index .Config.Labels "crashcap.qai.browser-storage"}}',
            )
            == token
        )
        docker("rm", "-f", "-v", container)
        receipt["removed"] = True
        (output / "storage.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )


def main():
    from crashcap_api.config import Settings
    from crashcap_api.storage import create_object_store

    output = (
        Path(__file__).resolve().parents[2]
        / "target/qa-symbol-import/browser-storage"
        / uuid4().hex
    )
    with owned_storage(output) as (overrides, client, receipt):
        settings = Settings.model_validate(
            {**Settings.for_test(output).model_dump(), **overrides}
        )
        store = create_object_store(settings)
        payload = b"owned browser transport qualification"
        upload = store.presign_put(
            "qualification/transport.bin", len(payload), "application/octet-stream"
        )
        with httpx.Client(timeout=15) as http:
            preflight = http.options(
                upload.url,
                headers={
                    "Origin": receipt["origin"],
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "content-type,x-amz-server-side-encryption",
                },
            )
            assert preflight.is_success, preflight.status_code
            assert (
                preflight.headers.get("access-control-allow-origin")
                == receipt["origin"]
            )
            response = http.put(
                upload.url,
                headers={**upload.headers, "Origin": receipt["origin"]},
                content=payload,
            )
            assert response.is_success, response.status_code
            assert (
                response.headers.get("access-control-allow-origin") == receipt["origin"]
            )
            assert (
                "etag"
                in response.headers.get("access-control-expose-headers", "").lower()
            )
        assert b"".join(store.stream("qualification/transport.bin")) == payload
        head = client.head_object(
            Bucket=overrides["s3_bucket"], Key="qualification/transport.bin"
        )
        assert head["ServerSideEncryption"] == "AES256"
        receipt.update(
            status="PASS",
            preflight_status=preflight.status_code,
            put_status=response.status_code,
            verified_length=len(payload),
            server_side_encryption=head["ServerSideEncryption"],
        )
    print(json.dumps({"status": "PASS", "receipt": str(output / "storage.json")}))


if __name__ == "__main__":
    main()
