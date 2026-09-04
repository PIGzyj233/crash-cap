# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Crash-Cap is a Windows-native (x64, user-mode, MSVC C/C++) minidump analysis platform that **runs
on Linux**. A Rust core (`dmp-core`) turns each DMP into a versioned, evidence-bearing structured
report; a Python control plane manages ingest, symbols, tasks, and retrieval; a React app presents
it. Deployment target is an **anonymous trusted intranet** — no login, no RBAC, no DELETE endpoints,
plain HTTP.

## Authority order

When sources conflict, resolve in this order — do not invent product rules:

1. `contracts/*.schema.json`, `contracts/drafts/qa-symbol-import/*.schema.json` — versioned machine contracts; the latter path is used by the current runtime
2. `docs/design.md` — the implementation and review authority (Chinese; §-numbered)
3. `docs/adr/` — accepted architecture decisions; follow superseding ADRs
4. `CONTEXT.md` — canonical domain vocabulary, including terms to *avoid*
5. `docs/implementation-roadmap.md`, `docs/qa-symbol-import-guide.md` — delivery scope and acceptance; consult the QA guide for first-launch deployment or symbol-import work
6. `miniprd.md` — historical blueprint only, superseded by `docs/design.md`

`CONTEXT.md` matters in practice: Occurrence ≠ Analysis Run, Build ≠ Version, Artifact ≠ Artifact
Blob, Current Analysis ≠ latest attempt. Use those distinctions in code, tests, and prose.

## Repository layout

```text
core/               Rust dmp-core CLI: inspect | analyze | identify → versioned Canonical
artifact-identity/  Shared bounded PE/PDB identity parser (code_id / debug_id)
crashcap-ci/        Rust `crashcap` binary: local + CI Build publisher
tests/schema/       Draft 2020-12 contract test package (+ validate-instance bin)
contracts/          JSON Schemas: analysis-result, build-manifest, task-message, publication…
platform/api/       FastAPI control plane (crashcap_api)
platform/worker/    Dramatiq workers (crashcap_worker) — also imported by the API for in-process tests
platform/cli/       Local-only ops CLI (crashcap_cli → crashcap-ops)
platform/frontend/  React 19 + TS + Vite + Ant Design + TanStack Query
platform/migrations/ Standalone Alembic script location
fixtures/           Golden fixture metadata + expectations (binaries are never committed)
scripts/            Gates, evidence generators, fixture builders, openapi codegen, ops tooling
deploy/, infra/     Compose stacks, Dockerfiles, symbolicator gateway, RustFS
docs/evidence/      Local, Git-ignored gate output and replay inputs
tools/crashcap/     Committed signed-ish release binaries + SHA256SUMS + release.json
```

## Commands

Rust (workspace root, Cargo workspace of 4 crates):

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace --all-targets
cargo test -p crash-cap-schema-tests                # contract compatibility matrix
cargo test -p dmp-core canonical                    # single test / filter
cargo run -q -p crash-cap-schema-tests --bin validate-instance -- \
  contracts/analysis-result-v1.schema.json path/to/canonical.json
```

Python platform (all commands run **from `platform/`**, uv-managed):

```bash
uv sync --extra dev
uv run pytest                                       # SQLite + local object store + memory queue
uv run pytest tests/test_task_handoff.py -k fencing -x
uv run ruff check .
uv run mypy api worker cli                          # strict mode
python -m alembic -c migrations/alembic.ini upgrade head --sql   # render DDL, no DB needed
```

Optional integration lanes are **skipped unless** these are set to disposable databases:
`CRASH_CAP_TEST_DATABASE_URL` (PostgreSQL), `CRASHCAP_TEST_REDIS_URL` / `CRASH_CAP_TEST_REDIS_URL`.
Markers: `integration`, `compose`, `capacity`.

Frontend (from `platform/frontend/`, pnpm 11 / Node 24):

```bash
pnpm install
pnpm test                  # vitest run
pnpm test -- --run src/api/polling.test.ts
pnpm lint                  # tsc --noEmit
pnpm build
pnpm openapi:generate      # regenerate openapi.json + src/generated/openapi.ts
pnpm openapi:check         # fails on drift — run after any response-model change
```

Aggregate gates (from repo root) — these are the checks that actually decide "done":

```bash
python scripts/phase2/gate.py        # current full gate: rust + schema + python + frontend
python scripts/phase0/verify.py      # lightweight lane; --run-s3 / --run-docker / --run-windows-fixture opt in
python scripts/phase0/gate.py        # evaluates local evidence in docs/evidence/, never fabricates a pass
python scripts/schema/validate.py
python scripts/ci/check_markdown_links.py
python scripts/core/verify_oci.py    # builds deploy/core/Dockerfile, checks pinned digests
```

Rebuild the committed publisher binaries (Windows host, Docker for the musl target):

```powershell
./scripts/crashcap/build-release.ps1
```

## Architecture: the invariants that shape the code

**Anonymous intranet.** No auth, no user/role/tenant tables, no DELETE routes.
`assert_no_delete_routes` runs at app construction; `Settings.validate_security_boundary` rejects
public binds in production and non-`http://` S3 endpoints. Workspace isolation prevents symbol,
cache, and statistics crosstalk — it is *not* access control.

**Uploads require server-side byte verification.** DMP uploads go directly to object storage via
presigned URLs. Independent PE/PDB imports stream through the v2 API into staging with size/hash
verification; the Worker validates complete pair identity before catalog availability.

**Occurrence / Blob / Analysis Run are separate** (ADR-0002). One distinct accepted DMP per
workspace = one Occurrence, forever. Reanalysis creates a new immutable `analysis_run`;
`occurrences.current_run_id` selects an eligible `COMPLETE|PARTIAL` result. QA analyses use
the evidence-v1 comparison and explicit post-result review (ADR-0021), not creation order alone.
A later failure preserves a useful Current. Crash counts read Current, one per Occurrence.

**Durable task handoff with fenced execution** (ADR-0006). Business state and the task intent commit
in the *same* PostgreSQL transaction; a separate relay delivers at-least-once to Redis. Workers take
ownership via lease + monotonic generation. Every terminal state, Canonical winner, Current Analysis
promotion, group projection, and Symbol Health write **must be generation-fenced**. Never claim
exactly-once. Long Core/RustFS/Symbolicator work must not hold a DB lock. Failure semantics per
crash point are tabulated in `docs/architecture/task-failure-matrix.md`.

**Core owns the final Canonical result** (ADR-0007, ADR-0019). QA analysis freezes context,
resolution manifest, selected materials and engine identities before execution. Core emits
Canonical 1.1; the Worker validates and stores it without post-assembly mutation.

**Symbol Health is a durable projection** (ADR-0009). Built from each Occurrence's Current Analysis
winner; `operation_logs` is append-only audit and must never be replayed as a read source. Rollout
staging: `legacy → shadow-soft → strict-writer → projection-read`.

**Identity matching only.** Modules match on `code_id` (from PE only) and `debug_id` (PDB 7.0
RSDS GUID+age, stored lowercase without hyphens) — never filename, never product version. A wrong
PDB is `pdb_mismatch` and must not symbolicate that module. Missing symbols produce `PARTIAL`, never
`FAILED`.

**Build identity is content-based** (ADR-0010). `build-content-v1` fingerprints the normalized
Manifest plus every expected PE/PDB's kind/name/size/SHA-256. Build Publications record provenance
(`local` | `ci`) and are idempotent; local and CI publications can share one Build. A Build seals
once all Expected Artifacts verify, after which Manifest and Artifact mutations fail closed.

**Storage identity and global symbol availability are separate** (ADR-0011, ADR-0018).
Existing Artifact Blobs retain Workspace-scoped storage identity. The global catalog can select
verified complete pairs across Workspaces; roles, Build attribution and source policies remain
local to the consuming Workspace. Same identity with different valid bytes is an explicit conflict.

**Analysis input selection precedes materialization** (ADR-0012). Candidate selection is a
metadata-only narrowing that reduces bytes downloaded; it never decides Build Resolution.
`artifact-selection-v1` is checkpointed alongside `inspect.json`.

**HTTP representation authority** (ADR-0008). `platform/api/crashcap_api/response_models.py` is the
authority — top-level models are `extra=forbid`, so adding or removing a wire field is an explicit
review. Canonical is the one exception: OpenAPI injects
`contracts/analysis-result-v1.schema.json` by source SHA-256 at build time. The browser aliases
generated types from `src/generated/openapi.ts`; do not hand-write parallel wire interfaces.

**Versioned everything.** `schema_version 1.0`, `norm-v1.0`, `group-v1.0`, `exact-v1.0`, quality
weights `0.45 / 0.35 / 0.20` are **frozen**. Changing a rule, enum, constraint, or bucketing means a
new contract/algorithm version with old readers retained — an optional property is not a way around
`additionalProperties: false`.

## Deployment configuration

Read `platform/api/crashcap_api/config.py` and `deploy/compose/phase1.yml` for current settings.
Keep API and Worker configuration consistent. QA first launch starts from empty project-owned
storage and does not promise old-version or mixed-image compatibility; use
`docs/operations/phase1-deployment.md` for deployment and `docs/qa-symbol-import-guide.md` for
reset boundaries and acceptance. Historical immutable Runs within the new version remain protected.

## Testing conventions

Tests assert domain semantics, not HTTP 200. Unit/contract tests select **explicit** doubles via
`Settings.for_test`: SQLite, on-disk object store (`object_store_backend="local"`), in-process
dispatcher (`queue_mode="memory"`), `core_executor="fake"`, `symbol_ingest_mode="fake"`. Production
paths (PostgreSQL, Redis, RustFS, one-shot `dmp-core` containers) are never silently substituted.
`platform/tests/conftest.py` provides `Phase1Harness` with `create_workspace` / `upload_artifact` /
`upload_dump` / `drain()` — reuse it rather than re-deriving the upload dance.

Golden fixtures in `fixtures/` are **metadata and expectations only**; real DMP/PE/PDB bytes live in
private object storage and must not be committed. `expected.json` may list `allowed_differences`
for addresses, paths, and thread IDs, but an exception code or a PDB mismatch is never optional.

## Conventions

- Rust: edition 2021, MSRV 1.80 (`.clippy.toml`), rustfmt `max_width = 100`,
  `use_small_heuristics = "Max"`; CI toolchain is pinned to 1.96.1.
- Python: 3.12+, ruff line length 100 with `E,F,I,B,UP,SIM,S` (bandit) enabled, mypy `strict`.
- Line endings are enforced by `.gitattributes`: LF for `.rs/.py/.toml/.json/.yml/.md/.sh`,
  **CRLF for `.ps1/.bat/.cmd`**.
- Documentation under `docs/` is primarily Chinese; code, identifiers, comments, and contracts are
  English. Match the surrounding file.
- Commits use Conventional-Commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `feat(ci):`).
- Never log raw memory, source text, tokens, or full presigned URLs — `crashcap_api/redaction.py`
  and `crashcap-ci/src/redaction.rs` exist for this and are covered by tests.

## Evidence discipline

`docs/evidence/` is Git-ignored local output. Gate generators may write JSON or Markdown receipts
there, and CI must upload any evidence that needs to outlive the job as a workflow artifact. Gate
scripts report honest `PASS`/`FAIL`/`SKIP` and refuse to convert a skip or missing input into a pass.
A local gate run is **not** evidence that a remote CI runner, a target intranet perimeter, a
production PostgreSQL, or a real DMP executed the workflow — keep that boundary explicit in any
status you write, and in `docs/` status lines.
