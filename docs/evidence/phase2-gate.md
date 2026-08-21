# Phase 2 Gate Evidence

- Generated: `2026-08-21T11:31:01.691116+00:00`
- Decision: **PASS / GO**
- Passed: `13/13`
- Scope: local source, contract, PostgreSQL migration, Redis queue persistence, platform, CLI, and frontend verification; this is not proof that an external intranet deployment or remote CI runner executed the workflow.
- Integration services: PostgreSQL `executed`; Redis `executed`.

| Step | Result | Seconds | Command |
| --- | --- | ---: | --- |
| `markdown-links` | PASS | 0.851 | `C:\Python314\python.exe scripts/ci/check_markdown_links.py` |
| `rust-format` | PASS | 0.217 | `cargo fmt --check` |
| `rust-clippy` | PASS | 0.443 | `cargo clippy --workspace --all-targets -- -D warnings` |
| `rust-tests-and-contracts` | PASS | 1.131 | `cargo test --workspace` |
| `schema-matrix` | PASS | 0.503 | `C:\Python314\python.exe scripts/schema/validate.py` |
| `python-lint` | PASS | 0.065 | `uv run ruff check .` |
| `python-types` | PASS | 0.41 | `uv run mypy api worker cli ci` |
| `platform-tests` | PASS | 18.508 | `uv run pytest -q` |
| `ci-cli-contract` | PASS | 0.565 | `uv run crashcap-ci --help` |
| `frontend-openapi` | PASS | 2.227 | `pnpm openapi:check` |
| `frontend-tests` | PASS | 1.765 | `pnpm test -- --run` |
| `frontend-types` | PASS | 0.508 | `pnpm lint` |
| `frontend-build` | PASS | 11.112 | `pnpm build` |

## Gate assertions

- MSVC is the only producer marked `supported`; clang-cl and Crashpad remain `experimental` until producer-specific fixtures pass the frozen Golden metrics.
- Build registration is idempotent by `(workspace_id, producer, producer_build_id)` and rejects identity reuse with conflicting immutable metadata.
- CI readiness requires a valid Manifest and verified PE/PDB for every declared module; a declared source bundle must also complete safe ingest.
- Source bundle ingest rejects traversal, symlinks, encryption, nested archives, oversized input, and excessive compression ratio before source is consumed.
- Symbol upload can target an affected Build/module, batch reprocess preserves old Runs and Occurrence count, and progress is available by SSE with polling fallback.
- Workspace in-app rules are versioned in Run Spec; rule changes create new Runs and cannot override the system-module deny floor.
- Existing Build Manifest v1 and Canonical v1 readers remain covered by the compatibility suite.
