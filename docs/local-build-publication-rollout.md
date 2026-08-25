# Local Build Publication implementation and rollout

Status date: 2026-08-25. Implementation baseline: `main@e7edfdf`.

This checklist separates repository implementation evidence from target-network
acceptance. A local PASS does not claim that an intranet developer machine,
organization signing service, production PostgreSQL, or a real DMP executed the
workflow.

## LP0 - domain and contracts

- [x] LP-001: `CONTEXT.md` defines Build Publication, Publication Origin,
  Artifact Producer, Build Content Fingerprint, Expected Artifact and Sealed Build.
- [x] LP-002: ADR-0010 records content Build identity, source-specific
  Publications, immutable Ready/Sealed behavior and the legacy boundary.
- [x] LP-003: `build-publication-v1`, `crashcap.toml` v1 and
  `build-content-v1` canonical fingerprint behavior are executable contracts.
- [x] GATE-LP0-local: schema, Manifest v1/v2 and HTTP representation fixtures
  remain in the repository gate.

## LP1 - data and server protocol

- [x] LP-101: migration 0006 adds content identity fields, `pub_` Publications,
  exact Artifact expectations, constraints/indexes and legacy defaults. It refuses
  downgrade after any content Build exists.
- [x] LP-102: registration computes the fingerprint server-side, uses
  transaction-scoped PostgreSQL locks for Publication/content winners, and allows
  local and CI Publications to share one Build.
- [x] LP-103: upload init accepts only the expected name/kind/size/hash; Worker
  checks actual bytes and shared PE/PDB identity; Ready atomically writes
  `sealed_at`, after which Manifest and Artifact mutations fail closed.
- [x] LP-104: explicit response models, OpenAPI, operation logs and bounded-label
  metrics cover registration, bytes, verification time, conflicts and rejections.
  Legacy Build/Manifest, `/ci/producers` and `/ci-status` routes remain.
- [x] GATE-LP1-local: SQLite protocol tests cover reuse, cross-origin dedupe,
  byte replacement rejection and sealing; rendered migration SQL covers PostgreSQL
  DDL.
- [ ] GATE-LP1-target: execute migration and simultaneous-client tests against the
  selected PostgreSQL backup/restore environment.

## LP2 - unified native CLI

- [x] LP-201: the only delivered binary is `crashcap`; Windows/Linux fixed
  artifacts and GitHub/GitLab templates use `crashcap.toml` plus `publish`.
- [x] LP-202: Core and CLI share `crashcap-artifact-identity`; there is one x64
  PE/full-PDB/FASTLINK identity implementation.
- [x] LP-203: `init`, `validate` and `doctor` implement profile/version/Git/path
  rules. Workspace creation and ambiguous entrypoint/module roles require explicit
  flags.
- [x] LP-204: Publication registration, streamed PUT/multipart, transport retry,
  interrupted-upload re-initialization under the same Publication identity,
  Ready polling and credential-free receipt are implemented.
- [x] GATE-LP2-local: Rust tests, Clippy, Windows execution, Linux container
  execution and release hashes pass without a target Python/Rust runtime. A
  checked-in native CLI test runs `init`, interrupts the first PDB multipart,
  retries under the same Publication, reuses the verified PE, reaches Ready,
  replays without PUTs and proves local/CI Build reuse plus receipt redaction.
- [ ] GATE-LP2-target: publish a real near-limit PDB from a clean Windows machine
  while recording peak RSS and interrupted multipart recovery.

## LP3 - product and operations

- [x] LP-301: the Workspace developer page exposes downloads and an exact init
  command. Build detail shows Local/CI/Legacy, fingerprint, sealed/Git state and
  per-file recovery reasons.
- [x] LP-302: the frontend image serves fixed `/downloads/crashcap/` files with
  no directory listing or SPA fallback. Release metadata distinguishes
  `unsigned-pilot` from `authenticode-signed` and records post-signing identity.
- [x] LP-303: local/CI guide, sample configuration, troubleshooting and repository
  templates use the unified client.
- [x] LP-304: Prometheus metrics use bounded `origin`, `outcome` and `reason`
  labels for Publications, bytes, verification, conflicts and rejection.
- [x] GATE-LP3-local: frontend types/tests/build, OpenAPI drift, delivery metadata,
  nginx policy and Compose static validation are automated. API, Worker, Core and
  Frontend production Dockerfiles build; the Frontend container serves the exact
  checked-in EXE hash and returns 404 for missing tools and the download directory.
- [ ] GATE-LP3-target: capture signed-download and browser evidence on the chosen
  main Compose host.

## LP4 - pilot and cutover (external hard gate)

- [ ] Enable `CRASHCAP_BUILD_PUBLICATIONS_ENABLED=true` only in the named pilot
  environment; default remains false.
- [ ] A named developer publishes real local MSVC Release output from the target
  intranet/VPN.
- [ ] A real DMP resolves the content Build through both reported and auto-unique
  paths and displays correct symbols.
- [ ] Exercise identical replay, changed rebuild, interrupted upload, wrong PDB,
  near-limit PDB and dirty/unknown Git state.
- [ ] Apply the organization Authenticode certificate and approve its thumbprint,
  target perimeter, backup/restore and browser evidence.

Rollback disables the feature flag and UI exposure while retaining migration
0006 and registered data. Existing Workers may finish submitted verification.
Legacy Build, CI, Manifest and browser paths remain available. Database downgrade
is forbidden after content Build creation.
