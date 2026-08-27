# Phase 2 Gate Evidence

- Generated: `2026-08-26T15:39:45.480819+00:00`
- Decision: **PASS / GO**
- Passed: `13/13`
- Scope: local source, contract, PostgreSQL migration, Redis queue persistence, platform, CLI, and frontend verification; this is not proof that an external intranet deployment or remote CI runner executed the workflow.
- Integration services: PostgreSQL `skipped (CRASH_CAP_TEST_DATABASE_URL unset)`; Redis `skipped (CRASHCAP_TEST_REDIS_URL unset)`.

| Step | Result | Seconds | Command |
| --- | --- | ---: | --- |
| `markdown-links` | PASS | 1.13 | `C:\Python314\python.exe scripts/ci/check_markdown_links.py` |
| `rust-format` | PASS | 0.274 | `cargo fmt --check` |
| `rust-clippy` | PASS | 0.479 | `cargo clippy --workspace --all-targets --locked -- -D warnings` |
| `rust-tests-and-contracts` | PASS | 5.801 | `cargo test --workspace --locked` |
| `schema-matrix` | PASS | 0.501 | `C:\Python314\python.exe scripts/schema/validate.py` |
| `python-lint` | PASS | 0.071 | `uv run ruff check .` |
| `python-types` | PASS | 0.447 | `uv run mypy api worker cli` |
| `platform-tests` | PASS | 42.408 | `uv run pytest -q` |
| `publisher-cli-contract` | PASS | 0.009 | `E:\ai-services\crash-cap\tools\crashcap\windows-x86_64\crashcap.exe --help` |
| `frontend-openapi` | PASS | 2.675 | `pnpm openapi:check` |
| `frontend-tests` | PASS | 11.742 | `pnpm test -- --run` |
| `frontend-types` | PASS | 2.567 | `pnpm lint` |
| `frontend-build` | PASS | 11.356 | `pnpm build` |

## Gate assertions

- MSVC is the only producer marked `supported`; clang-cl and Crashpad remain `experimental` until producer-specific fixtures pass the frozen Golden metrics.
- Content Build registration is unique by `(workspace_id, fingerprint_version, content_fingerprint)`; local and CI Publications can point to the same Build.
- Publication readiness requires every declared PE/PDB to match its expected size/SHA-256 and pass identity validation; Ready atomically seals the Build.
- Workspace-scoped Artifact Blobs reuse only server-verified PE/PDB bytes; every Build retains its exact expectations, and pair mismatch does not poison an individually valid Blob.
- Source bundle ingest rejects traversal, symlinks, encryption, nested archives, oversized input, and excessive compression ratio before source is consumed.
- Symbol upload can target an affected Build/module, batch reprocess preserves old Runs and Occurrence count, and progress is available by SSE with polling fallback.
- Workspace in-app rules are versioned in Run Spec; rule changes create new Runs and cannot override the system-module deny floor.
- Existing Build Manifest v1 and Canonical v1 readers remain covered by the compatibility suite.
