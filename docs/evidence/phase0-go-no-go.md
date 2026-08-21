# Phase 0 Go/No-Go

Decision: **GO**  
Status: **PASS**  
Evaluated (UTC): `2026-08-20T18:28:45.326668Z`  
Core OCI digest: `sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b`

| Gate | Result | Observed |
| --- | --- | --- |
| `GATE-P0-01` exception code accuracy = 100% | **PASS** | `{"name":"valid_complete_matched_exception_code_accuracy","numerator":11,"denominator":11,"rate":1.0,"status":"PASS","eligible_fixture_ids":["p0-b01-null-read","p0-d03-null-write","p0-d03-illegal-execute","p0-d03-cpp-u...` |
| `GATE-P0-02` crashing thread accuracy = 100% | **PASS** | `{"name":"crashing_thread_accuracy","numerator":11,"denominator":11,"rate":1.0,"status":"PASS","eligible_fixture_ids":["p0-b01-null-read","p0-d03-null-write","p0-d03-illegal-execute","p0-d03-cpp-uncaught","p0-d03-std-t...` |
| `GATE-P0-03` PDB mismatch detection = 100% | **PASS** | `{"name":"pdb_mismatch_detection_rate","numerator":2,"denominator":2,"rate":1.0,"status":"PASS","eligible_fixture_ids":["p0-d05-wrong-pdb","p0-d05-pe-mismatch"],"skipped_fixture_ids":[]}` |
| `GATE-P0-04` top-3 business-frame equivalence >= 95% | **PASS** | `{"name":"complete_symbol_sample_top3_business_frame_equivalence","numerator":11,"denominator":11,"rate":1.0,"status":"PASS","eligible_fixture_ids":["p0-b01-null-read","p0-d03-null-write","p0-d03-illegal-execute","p0-d...` |
| `GATE-P0-05` silent wrong symbols = 0 | **PASS** | `{"count":0,"status":"PASS","scope":"wrong_pdb and pe_mismatch target frames with symbols despite non-matched artifact status"}` |
| `GATE-P0-06` 20-50 auditable Golden fixtures | **PASS** | `{"golden_status":"PASS","fixture_count":21,"counts":{"PASS":21}}` |
| `GATE-P0-07` RustFS S3 qualification | **PASS** | `{"status":"QUALIFIED","case_count":10,"digest":"sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831","endpoint":"https://127.0.0.1:9000","tls_peer_verification":"strict CA and SAN verification"}` |
| `GATE-P0-08` stable v1 contracts and /api/v1 | **PASS** | `{"contract_status":"PASS","canonical_count":18,"api_prefix":"/api/v1"}` |
| `GATE-P0-09` recorded Go/No-Go decision | **PASS** | `{"decision":"GO","failed_prerequisites":[]}` |

## Supporting checks

| Check | Result |
| --- | --- |
| `SUPPORT-CORE-OCI` final Core image identity and sandbox | **PASS** |
| `SUPPORT-SYMBOLICATOR` pinned loopback Symbolicator policy | **PASS** |
| `SUPPORT-CALIBRATION` F03-F07 frozen calibration | **PASS** |
| `SUPPORT-AUTHORIZED` authorized real-origin sample boundary | **PASS** |
| `SUPPORT-CI` local required CI checks | **PASS** |
| `SUPPORT-TOOLCHAIN` required Phase 0 toolchain | **PASS** |

## Evidence boundary

- Verification was executed locally on Docker Desktop and the recorded Windows/MSVC toolchain.
- No remote GitHub Actions run and no production deployment/network were executed by this report.
- The authorized real-origin case is a pinned public upstream test artifact stored in a private local RustFS bucket; it is not a Crash-Cap production incident.
- RustFS qualification is single-node local Docker evidence and does not prove distributed durability or production RPO/RTO.

Machine-readable evidence: `E:\ai-services\crash-cap\docs\evidence\phase0-go-no-go.json`
