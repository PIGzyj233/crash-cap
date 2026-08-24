# Phase 2 Gate Evidence

- Generated: `2026-08-23T10:19:08.115025+00:00`
- Decision: **PASS / GO**
- Passed: `13/13`
- Scope: local source, contract, PostgreSQL migration, Redis queue persistence, platform, CLI, and frontend verification; this is not proof that an external intranet deployment or remote CI runner executed the workflow.
- Integration services: PostgreSQL `skipped (CRASH_CAP_TEST_DATABASE_URL unset)`; Redis `skipped (CRASHCAP_TEST_REDIS_URL unset)`.

| Step | Result | Seconds | Command |
| --- | --- | ---: | --- |
| `markdown-links` | PASS | 0.88 | `C:\Python314\python.exe scripts/ci/check_markdown_links.py` |
| `rust-format` | PASS | 0.217 | `cargo fmt --check` |
| `rust-clippy` | PASS | 0.77 | `cargo clippy --workspace --all-targets --locked -- -D warnings` |
| `rust-tests-and-contracts` | PASS | 7.314 | `cargo test --workspace --locked` |
| `schema-matrix` | PASS | 0.534 | `C:\Python314\python.exe scripts/schema/validate.py` |
| `python-lint` | PASS | 0.077 | `uv run ruff check .` |
| `python-types` | PASS | 0.433 | `uv run mypy api worker cli` |
| `platform-tests` | PASS | 25.104 | `uv run pytest -q` |
| `ci-cli-contract` | PASS | 0.015 | `E:\ai-services\crash-cap\tools\crashcap-ci\windows-x86_64\crashcap-ci.exe --help` |
| `frontend-openapi` | PASS | 2.415 | `pnpm openapi:check` |
| `frontend-tests` | PASS | 1.814 | `pnpm test -- --run` |
| `frontend-types` | PASS | 0.526 | `pnpm lint` |
| `frontend-build` | PASS | 12.755 | `pnpm build` |

## Gate assertions

- MSVC is the only producer marked `supported`; clang-cl and Crashpad remain `experimental` until producer-specific fixtures pass the frozen Golden metrics.
- Build registration is idempotent by `(workspace_id, producer, producer_build_id)` and rejects identity reuse with conflicting immutable metadata.
- CI readiness requires a valid Manifest and verified PE/PDB for every declared module; a declared source bundle must also complete safe ingest.
- Source bundle ingest rejects traversal, symlinks, encryption, nested archives, oversized input, and excessive compression ratio before source is consumed.
- Symbol upload can target an affected Build/module, batch reprocess preserves old Runs and Occurrence count, and progress is available by SSE with polling fallback.
- Workspace in-app rules are versioned in Run Spec; rule changes create new Runs and cannot override the system-module deny floor.
- Existing Build Manifest v1 and Canonical v1 readers remain covered by the compatibility suite.
