# Architecture deepening G0 baseline

Status: **accepted for implementation** on `main@f4ee82e`, 2026-08-24. Target-environment data and object checks must be rerun immediately before migration; this local gate does not claim a production scan.

## Frozen behavior

| Surface | Reproducible authority | Normalization |
| --- | --- | --- |
| 21 Core Golden fixtures | `fixtures/index.json`, `docs/evidence/phase0-golden-results.json`, `python scripts/phase0/gate.py` | Compare fixture IDs and semantic metrics; ignore evidence generation time and absolute checkout paths. |
| Worker final Canonical | `test_phase1_pipeline.py`, `test_phase2_gate.py`, stable `analysis-result-v1` Schema | Generated IDs are mapped by domain role; timestamps are compared by source/precedence; object URLs, request IDs, temp paths, and ETags are ignored. |
| COMPLETE/PARTIAL and historical Run behavior | `test_phase1_pipeline.py::test_correct_pe_pdb_dump_runs_end_to_end`, `test_wrong_pdb_is_explicit_and_never_symbolicates`, `test_late_symbol_reprocess_preserves_history_and_total` | Canonical bytes need only be identical after dynamic identity/time normalization; enums, nullability, quality, fingerprint, and source context are exact. |
| source bundle | `test_phase2_gate.py::test_source_bundle_v2_is_safely_ingested_and_enriches_symbolicator_frames` | Source lines are exact; archive path and temporary extraction path are ignored. |
| dump/reported/uploaded/manual time | `test_phase1_pipeline.py::test_minidump_header_time_overrides_reported_time_and_manual_time_wins` | Convert to UTC ISO-8601 before comparison. |
| Four stable task messages | `contracts/task-message-v1.schema.json` and `test_architecture_g0.py` | `attempt_id` and `request_id` are dynamic; task type, routing, target field, schema, and additional-property rejection are exact. |
| HTTP interface | `http-route-inventory.json` and `test_architecture_g0.py` | Method/path/status/transport kind and consumer wave are exact; `/healthz`, `/readyz`, `/metrics`, docs, and OpenAPI are non-`/api/v1` operations and excluded. |

The checked-in Golden evidence is historical proof from its recorded Core/Symbolicator versions. Every changed checkout still reruns the applicable gate; target Compose, browser UAT, remote CI, and production evidence remain separate.

## Route and consumer inventory

`http-route-inventory.json` contains all 40 current `/api/v1` method/path operations, expected success status, transport class, known consumer, and representation migration wave. Wave 1 covers `crashcap`, Build Publication and upload/build paths, Wave 2 covers Occurrence/Analysis/SSE, and Wave 3 covers overview/group/Symbol/in-app/download paths. The inventory test fails when a route is added, removed, or method-changed without an explicit migration decision.

Transport exceptions are deliberate:

- Canonical is governed directly by `analysis-result-v1`, not a copied Pydantic model.
- SSE is governed by event fixtures and `text/event-stream` headers.
- downloads and uploads return presigned JSON; object bytes do not transit the API.
- all route failures use the stable error envelope and retain `X-Request-ID` behavior.

## Task failure model

The complete crash-point matrix is in `task-failure-matrix.md`. The two hard conclusions are that a transactional outbox without consumer fencing is unsafe, and that generation-scoped object keys are required because object storage cannot participate in the PostgreSQL finalize transaction.

## Data health preflight

Run the read-only scanner against the exact database and object store that will be migrated:

```powershell
cd platform
uv run crashcap-ops architecture-health --output ..\docs\evidence\architecture-health-target.json
```

Database-only mode is available when object credentials are intentionally unavailable:

```powershell
uv run crashcap-ops architecture-health --skip-object-check
```

That mode returns `PARTIAL`, never `PASS`. A full PASS requires zero illegal Current Analysis pointers, Group membership mismatches, duplicate result keys, legacy MissingSymbol count/replay mismatches, and missing Current Canonical objects. Double-null symbol identities are reported as migration input under ADR-0009 rather than silently treated as corruption.

## G0 decision record

The current implementation request accepts DEC-01–08 as recommended. Their durable record is:

- ADR-0006: transactional task intent, at-least-once relay, claim/lease/generation fencing, rollback floor.
- ADR-0007: Core owns final Canonical v1; Worker does not post-assemble.
- ADR-0008: explicit HTTP representations and generated consumer contracts.
- ADR-0009: monotonic Current Analysis and durable Symbol Health projection.

The same rules are reflected in `docs/design.md`; stable external contracts remain v1. Any later need to change a v1 field, requiredness, nullability, enum, or meaning stops this migration and requires a versioned contract decision.
