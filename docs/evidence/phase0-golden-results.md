# Phase 0 Golden Runner Results

Status: **PASS**  
Generated: `2026-08-20T18:17:20.702951+00:00`  
Fixture index: `E:\ai-services\crash-cap\fixtures\index.json`  
Core image digest supplied: `sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b`  
Symbolicator: `http://127.0.0.1:3021`; version `26.7.2`

This report is execution evidence. `SKIP` and `INCOMPLETE` are not passing analyses; they are excluded from rate denominators.

## Counts

`{"PASS": 21}`

## Metrics

| Metric | Numerator | Denominator | Rate | Status |
|---|---:|---:|---:|---|
| valid_complete_matched_exception_code_accuracy | 11 | 11 | 1.0000 | PASS |
| crashing_thread_accuracy | 11 | 11 | 1.0000 | PASS |
| pdb_mismatch_detection_rate | 2 | 2 | 1.0000 | PASS |
| complete_symbol_sample_top3_business_frame_equivalence | 11 | 11 | 1.0000 | PASS |
| silent_wrong_symbol_count | 0 | — | — | PASS |

## Fixture execution

| Fixture | Category | Treatment | Status | Diff / skip reason |
|---|---|---|---|---|
| `p0-b01-null-read` | P0-D03 | complete | **PASS** | — |
| `p0-d03-null-write` | P0-D03 | complete | **PASS** | — |
| `p0-d03-illegal-execute` | P0-D03 | complete | **PASS** | — |
| `p0-d03-cpp-uncaught` | P0-D03 | complete | **PASS** | — |
| `p0-d03-std-terminate` | P0-D03 | complete | **PASS** | — |
| `p0-d03-abort` | P0-D03 | complete | **PASS** | — |
| `p0-d04-stack-overflow` | P0-D04 | complete | **PASS** | — |
| `p0-d04-multithread` | P0-D04 | complete | **PASS** | — |
| `p0-d04-release-inline` | P0-D04 | complete | **PASS** | — |
| `p0-d04-async-thread-pool` | P0-D04 | complete | **PASS** | — |
| `p0-d04-deep-business-stack` | P0-D04 | complete | **PASS** | — |
| `p0-d05-missing-pdb` | P0-D05 | missing_pdb | **PASS** | — |
| `p0-d05-wrong-pdb` | P0-D05 | wrong_pdb | **PASS** | — |
| `p0-d05-missing-pe` | P0-D05 | missing_pe | **PASS** | — |
| `p0-d05-pe-mismatch` | P0-D05 | pe_mismatch | **PASS** | — |
| `p0-d06-corrupt-dmp` | P0-D06 | corrupt_dump | **PASS** | — |
| `p0-d06-truncated-dmp` | P0-D06 | truncated_dump | **PASS** | — |
| `p0-d06-non-x64` | P0-D06 | non_x64 | **PASS** | — |
| `p0-d06-explicit-hang` | P0-D06 | explicit_hang | **PASS** | — |
| `p0-d06-unknown-no-exception` | P0-D06 | unknown_no_exception | **PASS** | — |
| `p0-d07-upstream-invalid-parameter` | P0-D07 | authorized_real_no_local_artifacts | **PASS** | — |

Each fixture directory under `target/phase0-golden` contains the copied `expected.json`, real `inspect.json` when inspect succeeded, `raw/` engine outputs, `canonical.json` when analyze produced one, and `diff.json`.

## Limitations

- Placeholder and non-golden entries from `fixtures/index.json` are excluded.
- Missing generated binaries or dumps are recorded as `SKIP`; fixture metadata alone never contributes to a metric.
- A top-three symbol equivalence rate requires a completed Symbolicator response. Without `--symbolicator`, those samples remain `INCOMPLETE`.
- WOW64/x86 rejection is proven from the SysWOW64 ntdll plus WOW64 runtime module set when an AMD64 collector SystemInfo stream is present.
- The runner does not claim production authorization for the synthetic fixture corpus.

Machine-readable evidence: `E:\ai-services\crash-cap\docs\evidence\phase0-golden-results.json`
This report: `E:\ai-services\crash-cap\docs\evidence\phase0-golden-results.md`
