# crashcap-ci Rust migration evidence

- Verified: `2026-08-23`
- Version: `crashcap-ci 1.0.0`
- Decision: **LOCAL PASS / TARGET GITLAB PENDING**
- Phase 2 local gate: `13/13 PASS`
- Rust CLI tests: `24/24 PASS`
- Platform tests: `107 PASS, 2 SKIPPED`
- Core Docker builder regression: `PASS`

## Checked-in artifacts

| Target | Bytes | SHA-256 | Dependency result |
| --- | ---: | --- | --- |
| Windows x64 MSVC | 7,952,896 | `6d041e88b84c5f1f85e5d21ae83462b5410649972de94c23c5f5d5a02490559d` | Only Windows system DLL imports; no dynamic CRT, Python, or OpenSSL |
| Linux x64 musl | 8,041,168 | `9c3ab0d7e5d000344e7b5c7a680c6e9b68c8aaec37028ee8bd9371f658488769` | Static PIE; no ELF `NEEDED` entry or `INTERP` segment |

`SHA256SUMS` verified both files. `release.json` records Rust `1.96.1`, target, pinned Linux builder image, reproducible flags, linkage, and the same hashes without a timestamp. The Windows binary is intentionally `NotSigned`; repository SHA-256 is the current integrity gate.

## Real protocol and idempotency gate

The current local `/api/v1` Compose stack accepted a real MSVC Build publication:

- Workspace: `wsp_01M0H7Y0D058EJY6CAR3H3QXBF`
- Producer identity: `msvc / rust-native-final-gate-20260823`
- Build: `bld_01M0Q1FYB92Y98CRPE26T7GVVE`
- Windows first run: PE and PDB returned `uploaded`; `ci-status.ready=true`.
- Windows second run: the same Build ID returned; PE and PDB returned `already_verified`.
- Linux replay: the same Build ID returned; PE and PDB returned `already_verified`; `ci-status.ready=true`.
- A minimal `alpine:3.23` container with neither Rust nor Python installed executed `--version` and the real protocol replay successfully.

The Rust mock suite also covers embedded Manifest v1/v2 validation, unknown/invalid versions, missing/duplicate and case-insensitive Artifact resolution, streaming SHA-256, experimental producer gating, sorted JSON, single PUT, multipart boundaries and ETags, 5xx/transport retries, ordinary 4xx no-retry, upload rejection/quarantine, CI timeout/rejection, and final stdout/stderr secret redaction.

## Evidence boundary

Local GitLab YAML parsing passed, but GitLab CI Lint and remote Windows/Linux jobs were not available in this run. A clean Windows Runner was also not available. Therefore:

- `GATE-RCCI-01` through `GATE-RCCI-05`: **PASS locally**.
- `GATE-RCCI-06`: **PARTIAL** — minimal Linux runtime passed; local Windows binary passed, but a clean Windows Runner did not run.
- `GATE-RCCI-07`: **PASS locally**.
- `GATE-RCCI-08`: **NOT RUN remotely** — no Pipeline/Job ID exists yet.

Do not promote this record into proof of a remote GitLab Runner or target intranet deployment. That final evidence must come from the actual Runner and GitLab CI Lint.
