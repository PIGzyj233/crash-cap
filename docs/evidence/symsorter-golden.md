# Golden Symbolicator symsorter evidence

- symsorter: **26.7.2** (symsorter-Windows-x86_64.exe)
- expected SHA-256: `b13e3b176ab8a5c1bacbf4743061496c27240bba56220f6b73318804944a3ccd`
- observed SHA-256: `b13e3b176ab8a5c1bacbf4743061496c27240bba56220f6b73318804944a3ccd`
- complete fixtures discovered: **11**
- complete fixtures sorted: **11**
- complete fixture failures: **0**
- non-complete fixtures not published: **11**

| Fixture | Code ID | Debug ID | symsorter | Unified layout | Query boundary |
| --- | --- | --- | --- | --- | --- |
| p0-b01-null-read | `6A87124AC8000` | `5295C1F4535D4F8AA0B1989805198BB815` | `sorted` | `ready` | delegated |
| p0-d03-abort | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted` | `ready` | delegated |
| p0-d03-cpp-uncaught | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d03-illegal-execute | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d03-null-write | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d03-std-terminate | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d04-async-thread-pool | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d04-deep-business-stack | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d04-multithread | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |
| p0-d04-release-inline | `6A871E19C9000` | `9472158E9A3443C787B78A8A3448D0D730` | `sorted` | `ready` | delegated |
| p0-d04-stack-overflow | `6A871E18CA000` | `CF34E342F3604E87BA508387BB89876630` | `sorted_existing_duplicate` | `ready` | delegated |

## Not published

- `p0-d05-missing-pdb`: `missing_pdb`; artifact_treatment is not complete
- `p0-d05-missing-pe`: `missing_pe`; artifact_treatment is not complete
- `p0-d05-pe-mismatch`: `pe_mismatch`; artifact_treatment is not complete
- `p0-d05-wrong-pdb`: `wrong_pdb`; artifact_treatment is not complete
- `p0-d06-corrupt-dmp`: `corrupt_dump`; artifact_treatment is not complete
- `p0-d06-explicit-hang`: `explicit_hang`; artifact_treatment is not complete
- `p0-d06-non-x64`: `non_x64`; artifact_treatment is not complete
- `p0-d06-truncated-dmp`: `truncated_dump`; artifact_treatment is not complete
- `p0-d06-unknown-no-exception`: `unknown_no_exception`; artifact_treatment is not complete
- `p0-d07-upstream-invalid-parameter`: `authorized_real_no_local_artifacts`; artifact_treatment is not complete
- `placeholder`: `unknown`; artifact_treatment is not complete

## Query boundary

The sort evidence proves only the pinned PE/PDB was accepted and placed in Unified layout.
Several debug fixtures intentionally share one compiler-produced PE/PDB identity; after the first write, symsorter reports a duplicate-file warning and the script validates the existing same-ID layout rather than treating Sorted 0 as a new artifact.
For every complete fixture, the first expected business-frame symbol is recorded in JSON and the actual address query is delegated to `scripts/phase0/golden_runner.py`.

## Reproduction

```text
PYTHONDONTWRITEBYTECODE=1 python scripts/symbolicator/sort_golden.py --clean
```
