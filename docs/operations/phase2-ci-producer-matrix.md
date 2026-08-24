# Phase 2 CI producer compatibility matrix

The authoritative machine-readable view is `GET /api/v1/ci/producers`. The matrix is conservative: a producer is not `supported` merely because it can emit a `.dmp` or `.pdb` file.

| Producer | Status | Accepted baseline | Promotion gate |
| --- | --- | --- | --- |
| MSVC | supported | Windows native C/C++ x64 PE plus complete PDB 7.0 and standard user-mode Minidump | Frozen Phase 0 Golden: 21/21, exception/crash-thread/PDB mismatch 100%, top-3 business frames within gate, zero silent wrong symbols |
| clang-cl | experimental | Candidate PE x64 plus complete PDB 7.0 | Add clang-cl-owned fixtures, reference CDB summaries, then pass the same Golden metrics before changing the status |
| Crashpad | experimental | Candidate Windows native C/C++ x64 user-mode Minidump producer | Add Crashpad-captured fixtures with collection metadata, then pass the same Golden metrics before changing the status |

`crashcap-ci` refuses experimental producers unless `--allow-experimental` is supplied explicitly. That switch is for qualification only; it does not promote support status.

## Idempotent CI identity

A CI Build is identified by `(workspace_id, producer, producer_build_id)`. Retrying the same immutable metadata returns the same Build. Reusing that identity with a different Version, commit, build number, channel, architecture, or toolchain returns `409 CONFLICT`.

The Rust native CLI embeds Manifest v1/v2 schemas, validates local file completeness before network upload, streams SHA-256 and file bodies, supports S3 multipart, waits for verification/ingest, and exits non-zero until `GET /api/v1/builds/{build_id}/ci-status` reports `ready=true`. The committed Windows and Linux binaries require neither Python nor Rust on the producer Runner.

Example on a trusted intranet runner:

```powershell
tools\crashcap-ci\windows-x86_64\crashcap-ci.exe `
  --api-url http://127.0.0.1:8000/api/v1 `
  --workspace desktop-client `
  --manifest out/build-manifest.json `
  --artifact-root out/build-package `
  --producer msvc `
  --producer-build-id $env:CI_PIPELINE_ID
```

Linux x86_64 runners use `tools/crashcap-ci/linux-x86_64/crashcap-ci` with the
same arguments. Both templates verify `tools/crashcap-ci/SHA256SUMS` before
execution; reusable GitLab jobs live in `.gitlab/ci/crashcap-ci.yml`.

The runner must already be inside the approved intranet perimeter. Do not expose the anonymous API or presigned object-storage gateway to a public hosted runner.
