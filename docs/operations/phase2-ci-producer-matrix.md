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

The CLI validates Manifest and local file completeness before network upload, streams SHA-256, supports S3 multipart, waits for verification/ingest, and exits non-zero until `GET /api/v1/builds/{build_id}/ci-status` reports `ready=true`.

Example on a trusted intranet runner:

```powershell
uv run crashcap-ci `
  --api-url http://127.0.0.1:8000/api/v1 `
  --workspace desktop-client `
  --manifest out/build-manifest.json `
  --artifact-root out/build-package `
  --producer msvc `
  --producer-build-id $env:GITHUB_RUN_ID
```

The runner must already be inside the approved intranet perimeter. Do not expose the anonymous API or presigned object-storage gateway to a public hosted runner.
