# Authorized Golden sample import

Run from the repository root:

```bash
bash scripts/authorized_samples/run.sh
```

The command downloads the sample from the immutable upstream commit embedded
in `import_rust_minidump.py`, verifies its SHA-256 and size, and stores it in a
private, SSE-S3-enabled RustFS bucket. The service is bound only to
`127.0.0.1:9002`. Credentials, RustFS data and the local DMP cache are in
ignored paths. The committed evidence is `docs/evidence/authorized-real-sample.*`.

The service is intentionally left running so the Golden runner can retrieve
the private object. To stop it without deleting the persistent volume:

```bash
docker compose --project-name crash-cap-authorized-fixtures \
  --env-file infra/rustfs/.runtime/authorized-fixtures.env \
  --file infra/rustfs/authorized-fixtures-compose.yaml stop
```

The sample is a public upstream real-origin test artifact under the upstream
MIT license. It is not evidence of a Crash-Cap production incident.

