# RustFS qualification deployment

This directory contains the disposable single-node/single-disk (SNSD) RustFS
deployment used by Phase 0 P0-E01--P0-E10. The application is expected to use
only the standard S3 contract exercised by `qualification/s3/adapter.py`.

## Fixed candidate

```text
Image:  ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc
Digest: sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831
Release: RustFS 1.0.0-rc.2 (pre-release)
```

The digest is the multi-architecture image manifest. The qualification report
also records the platform-specific image digest returned by Docker. RustFS is
still a pre-release candidate, so a passing local S3 qualification is not a
production durability or distributed-failure claim.

The container has host bind mounts for qualification data, logs, and a
short-lived TLS certificate under `.runtime/` (ignored by source control). Only
the HTTPS S3 listener at `127.0.0.1:9000` is published; the Console port is not
published. `run.sh` creates a qualification-only CA and a SAN-covered server
certificate, while boto3 and the pre-signed URL probes perform strict CA and
hostname verification. No insecure verification bypass is used. Credentials
and the RPC secret are supplied through a temporary environment file, never
checked in or printed in the report. The Compose file uses RustFS's documented
scanner/ILM test controls to accelerate the standard Days-based lifecycle case;
this is called out in the report and is not a production expiry-latency claim.

## Run

From the repository root, with Docker Desktop running:

```bash
bash qualification/s3/run.sh
```

Useful options:

```bash
KEEP_RUSTFS=1 bash qualification/s3/run.sh
LIFECYCLE_WAIT_SECONDS=90 bash qualification/s3/run.sh
```

The command writes the machine-readable and Markdown evidence reports to
`docs/evidence/rustfs-qualification.json` and
`docs/evidence/rustfs-qualification.md`. A report is `QUALIFIED` only when all
ten P0-E cases are `PASS`; `NOT_PROVEN` is deliberately not treated as a pass.

## Replacement boundary

The adapter deliberately exposes S3 operations, not RustFS management APIs.
Replacing RustFS requires a compatible Compose endpoint and a new run of the
same qualification suite. A replacement is not eligible for storage freeze if
private-bucket access, presigning, multipart cleanup, streaming reads,
lifecycle, SSE, restart consistency, or backup/restore is not proven.
