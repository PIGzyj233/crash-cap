# Real large-PDB local UAT — 2026-08-24

## Evidence boundary

This is a local Windows/Docker Desktop UAT against the existing loopback-bound
Crash-Cap Compose stack. It is not evidence of a remote GitLab Runner, a target
intranet host, or production. The source EXE/PDB under
`E:\cplus_proj\light-streamer-ng` were read only; the old failed Workspace was
not reused or deleted.

## Source artifacts

| Kind | Path | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| PE | `E:\cplus_proj\light-streamer-ng\deploy\bin\lightstreamer.exe` | 12,935,168 | `721610d79e9aa01975755d46b411db59521b91aa37c31573e0ed05f7070273ce` |
| PDB | `E:\cplus_proj\light-streamer-ng\deploy\bin\lightstreamer.pdb` | 357,560,320 | `c0838b3692564157c1de256784ed4beae3fd21c6954307245cb87f6a8198d69a` |

The rebuilt Core identified both files with
`debug_id=dade83fe90d54eb59c3ebf3fb36ee57e1a`; the PE also reported
`code_id=6A8BC392C6F000`, and the PDB reported `is_fastlink=false`.

## Rebuilt local runtime

- Source baseline: `a1765e64ab9e5dbbfc24aac0495a8563478637e7` before the uncommitted fix.
- Core image: `crash-cap/dmp-core:phase1`, image ID
  `sha256:ff7052a98ae61b6e358c518949d6080257b5124b2c4b28745d91c97ddb51a2c5`,
  non-root user `65532:65532`.
- Worker image: `crash-cap/worker:phase1`, image ID
  `sha256:4280fc3fa40b9337b7f80f61c5492f63cef202a69fc2bf7bfbcb82daf263e41c`,
  non-root user `10001:10001`.
- Only `worker-ingest` was force-recreated from the rebuilt Worker image. Its
  configured Core digest matched the rebuilt Core image and its health was
  `healthy` before the UAT.

Build commands:

```text
docker build --file deploy/core/Dockerfile --tag crash-cap/dmp-core:phase1 .
docker build --file platform/worker/Dockerfile --tag crash-cap/worker:phase1 .
cargo build --release --locked --package crashcap-ci
```

The Compose recreation reused the existing external runtime env/secret files
by path; secret values were not printed or copied into this repository.

## Fresh identity and first publish

- Workspace: `wsp_01M0S7QTME8GWP28FVTKR4D04Z`
  (`lightstreamer-large-pdb-fix-20260824-991d`)
- Build: `bld_01M0S7S5GQWH4AYFBF9H2Z47FY`
- Module: `mod_01M0S7S5JCCPXS4QZ2AS3Q4214`
- Producer identity: `msvc` /
  `local-lightstreamer-2fc98e6-large-pdb-fix-20260824-991d`
- PE Upload: `upl_01M0S7S5NQ25QRK490HXFAAZJ5` — `ACCEPTED`
- PDB Upload: `upl_01M0S7S8YHQ07X3D9SVC39XCQS` — `ACCEPTED`
- PE Artifact: `art_01M0S7S8JXQAKJM6H9FYV881M3` — `verified`
- PDB Artifact: `art_01M0S7SKB11CCZX5FE8E60KWFQ` — `verified`

Command (exit code 0):

```text
target/release/crashcap-ci.exe --api-url http://127.0.0.1:58080/api/v1 --workspace wsp_01M0S7QTME8GWP28FVTKR4D04Z --manifest E:/ai-services/crash-cap/.runtime/lightstreamer-symbol-uat/build-manifest.json --artifact-root E:/cplus_proj/light-streamer-ng/deploy/bin --producer msvc --producer-build-id local-lightstreamer-2fc98e6-large-pdb-fix-20260824-991d --wait-seconds 1800
```

While the PE was `verified` and the PDB was still `pending`, the exact Unified
path for this Workspace/debug ID did not exist
(`unified_exists_while_pdb_pending=false`). After both Artifacts were verified,
`GET /api/v1/builds/bld_01M0S7S5GQWH4AYFBF9H2Z47FY/ci-status` returned
`ready=true`, with no missing or rejected artifacts.

## Unified verification

Unified identity path:

```text
/var/lib/crashcap/symbols/wsp_01M0S7QTME8GWP28FVTKR4D04Z/da/de83fe90d54eb59c3ebf3fb36ee57e1a
```

| Unified file | Bytes | SHA-256 |
| --- | ---: | --- |
| `executable` | 12,935,168 | `721610d79e9aa01975755d46b411db59521b91aa37c31573e0ed05f7070273ce` |
| `debuginfo` | 357,560,320 | `c0838b3692564157c1de256784ed4beae3fd21c6954307245cb87f6a8198d69a` |

`executable.meta` (63 bytes) and `debuginfo.meta` (64 bytes) both existed.
No Workspace staging directory or debug-ID backup directory remained.

## Idempotent rerun

Re-running the exact `crashcap-ci` command returned the same Workspace and
Build, reported both the PE and PDB as `already_verified`, kept
`ci_status.ready=true`, and exited 0. No second Upload or Build was created.

## Gates

- Rust: `cargo fmt --all --check`, workspace clippy with `-D warnings`, and
  `cargo test --workspace --locked` passed.
- Platform: ruff and mypy passed; pytest reported `112 passed, 2 skipped` in the
  ordinary run. The skipped PostgreSQL/Redis tests were then executed against
  isolated disposable containers by the Phase 2 gate.
- Phase 2: `python scripts/phase2/gate.py` reported `13/13 PASS / GO`, with both
  PostgreSQL and Redis integrations executed. See `phase2-gate.md` and
  `phase2-gate.json` in this directory.
