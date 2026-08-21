# P0-D07 upstream evidence boundary

- Source: `rust-minidump/rust-minidump`, pinned commit `4bc091396bdb88a6810ecb3746edd0f97d949e67`
- Path: `testdata/invalid-parameter.dmp`
- License: MIT at the pinned commit
- SHA-256: `5edaec6b6d8e360c8f26c5907d3ccb29d79cfd4c66d617b23005a2f1396aff9b`
- Size: `44629` bytes
- Sanitized facts: Windows x64, exception `0xC000000D`, crash thread `5896`, 6 threads, 31 modules
- Storage: private RustFS object with SSE-S3; anonymous GET is rejected

This is a contributor-generated, public-upstream real-origin test artifact. It
is not a Crash-Cap production incident. Matching PE/PDB files and an upstream
CDB/WinDbg stack oracle are unavailable, so it is excluded from complete-symbol
frame-equivalence metrics. Absolute module paths and raw memory are omitted.
