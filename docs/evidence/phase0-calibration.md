# Phase 0 F03–F07 calibration evidence

- Overall: **PASS**
- Checked (UTC): `2026-08-20T18:16:49.994842Z`
- Core executable: `E:\ai-services\crash-cap\target\release\dmp-core.exe`
- Core OCI image digest: `sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b`
- Remote CI: **not executed**

| Item | Status | Phase 0 decision |
| --- | --- | --- |
| `F03` | **PASS** | retain missing_pe and missing_pe_unwind as PARTIAL evidence; do not fail the valid dump, do not construct Exact |
| `F04` | **PASS** | freeze 0.45/0.35/0.20 for stable v1 based on the Golden gate and deterministic denominator boundary matrices; keep denominator warnings visible |
| `F05` | **PASS** | Accept symbol merge only when original_index, address, and module provenance are consistent; rejected mappings remain counted quality warnings and never fill another physical frame |
| `F06` | **PASS** | freeze exact-v1.0 with a 16-byte relative-address bucket for stable v1; do not infer zero theoretical or semantic collisions from this sample |
| `F07` | **PASS** | retain Microsoft source as deployment-owned allowlisted egress; keep cache temperature and source attribution explicit, and classify network failures as unavailable rather than business PDB mismatch |

## F03 missing-PE measurement

- Exact same dump with restored PE/PDB versus `pe_path=null`; CDB business frames: `['crashcap::trigger_null_read', 'wmain']`.
- Missing-PE business-frame loss versus CDB: `2/2` (`1.0`).
- Trust: restored `{'context': 1, 'cfi': 4}`, missing-PE `{'context': 1, 'scan': 10}`.
- Quality: restored `0.55`, missing-PE `0.09545454545454546`.

## F05 alignment result

- Real raw mappings accepted: `6`; rejected: `0`.
- Validator rejects mutated wrong physical mapping: `True`.
- Current Core wrong-index mock fills: `0`; required: `0`.

## F07 Microsoft symbols

- Valid public queries: `6`, successes: `6`, observed network failure rate: `0.0`.
- Successful latencies (ms): `[4409.12, 14.85, 15.18, 19664.97, 18.94, 4.86]`.
- Cold cache proven: **True**.
- Request-owned source rejection: `REQUEST_SOURCES_FORBIDDEN`.

## Reproduce

```text
python scripts/calibration/phase0_calibration.py --core-image-digest sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b --reset-symbolicator-cache
```

The JSON evidence contains command tails, raw mapping summaries, temporary restored-artifact boundaries, and per-probe machine-readable data.

## Evidence boundary

Fixtures, the Phase 0 Golden runner, the roadmap, and contracts were not modified by this tool. The samples are local synthetic MSVC outputs. The exact disposable Symbolicator test cache was reset only when explicitly requested; no remote CI or production egress proof is claimed.
