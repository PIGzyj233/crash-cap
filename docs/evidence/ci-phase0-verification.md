# Phase 0 QA/OPS Verification

- Overall: **PARTIAL**
- Required CI checks passed: **True**
- Started: `2026-08-20T18:28:32.873445+00:00`
- Finished: `2026-08-20T18:28:36.652084+00:00`
- Phase 0 gate eligible from this run: **False**

## Checks

| Check | Status | Duration | Reason |
| --- | --- | ---: | --- |
| `markdown_links` | **PASS** | 256 ms | - |
| `schema_draft_2020_12` | **PASS** | 475 ms | - |
| `cargo_fmt` | **PASS** | 223 ms | - |
| `cargo_clippy` | **PASS** | 455 ms | - |
| `cargo_test` | **PASS** | 847 ms | - |
| `fixture_metadata_contract` | **PASS** | 96 ms | - |
| `symbolicator_gateway_unit` | **PASS** | 1258 ms | - |
| `s3_adapter_offline` | **PASS** | 162 ms | - |
| `golden_runner` | **SKIP** | 0 ms | generated binaries and a running Symbolicator are required; use --run-golden with --core-image-digest |
| `s3_qualification` | **SKIP** | 0 ms | Docker-backed RustFS qualification is an explicit/manual lane; use --run-s3 |
| `symbolicator_container_smoke` | **SKIP** | 0 ms | Docker-backed Symbolicator smoke is an explicit/manual lane; use --run-docker |
| `windows_fixture_generation` | **SKIP** | 0 ms | Windows SDK/CDB fixture generation is an explicit/manual lane; use --run-windows-fixture |

## Interpretation

- `PASS` means the check was executed and passed in this local run.
- `FAIL` means the check was attempted and failed; it is not downgraded to a skip.
- `SKIP` marks an external or not-yet-wired lane that was intentionally not attempted.
- The default aggregator does not start Windows SDK builds, Docker Compose stacks, RustFS, or Symbolicator containers.
- A successful local aggregator is not evidence that a remote GitHub Actions run completed.

## Reproduce

```bash
python scripts/phase0/verify.py --output docs/evidence/ci-phase0-verification.json
```

Optional/manual lanes:

```bash
python scripts/phase0/verify.py --run-s3 --run-docker --run-windows-fixture
```

Evidence JSON: `docs/evidence/ci-phase0-verification.json`
