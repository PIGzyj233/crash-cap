# Upload v3 acceptance

Run the native CLI against an explicitly supplied deployment. This creates uniquely
named test Workspaces and uploads small real MSVC fixtures. It never resets a
database, removes existing files, or reuses another Workspace's private symbols.

```powershell
./scripts/fixtures/build_p0_b01.ps1
python scripts/upload_v3/acceptance.py `
  --api-url http://127.0.0.1:8082/api/v3 `
  --cli tools/crashcap/windows-x86_64/crashcap.exe `
  --fixture-dir fixtures/p0-b01-null-read/generated `
  --output target/upload-v3/acceptance
```

The fixture GUID is changed consistently in PE, PDB and DMP to isolate each run
from existing public files while preserving actual code, stacks and source lines.
`result.json` records checks; receipts record every upload; Canonical files retain
before/after results. A nonzero exit is a failed run even if earlier uploads succeeded.

The ordinary Rust, Python, PostgreSQL and frontend checks are defined in
[the v3 CI workflow](../../.github/workflows/qa-symbol-import.yml).
`owned_browser_storage.py` and `owned_browser_symbolicator.py` provide disposable
native test infrastructure for the PostgreSQL integration tests.

Build-era publishing, draft-contract generation, compatibility replay and Phase 0/2
gates have been removed. Historical evidence remains in `docs/evidence`; it is not
evidence for this implementation. See [the current guide](../../docs/upload-v3-guide.md).
