# P0-B01: x64 MSVC null-pointer read

## Reproduction

From the repository root on Windows:

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/fixtures/build_p0_b01.ps1
python scripts/fixtures/harness.py --output fixtures/harness-summary.json
```

The first command loads `vcvarsall.bat x64`, builds the target, independent
collector and DbgHelp verifier, launches the target, waits for its unhandled
exception filter, calls `MiniDumpWriteDump` from the collector process, and
then checks the dump with `MiniDumpReadDumpStream`. The second command only
discovers declarative metadata and accepts the generated verifier result; it
does not execute arbitrary fixture metadata.

## Last observed run

The run completed with exit code 0 and reported:

```text
Generated and verified p0-b01-null-read in E:\ai-services\crash-cap\fixtures\p0-b01-null-read\generated
code_id=6A87124AC8000 debug_id=5295c1f4535d4f8aa0b1989805198bb815 exception=0xC0000005 thread=11480
```

The stable verifier fields were:

```json
{
  "ok": true,
  "magic_ascii": "MDMP",
  "architecture": "x86_64",
  "exception": {
    "code": "0xC0000005",
    "name": "EXCEPTION_ACCESS_VIOLATION",
    "access_type": "read",
    "fault_address": "0x0000000000000000"
  },
  "crashing_thread": { "must_be_nonzero": true }
}
```

`code_id`, `debug_id`, process/thread IDs and absolute addresses are generated
values. The current values and SHA-256 hashes are in the ignored local
`generated/manifest.json`; the derivation rules are in `expected.json`.

## Blocker and boundary

`cdb.exe` and `windbg.exe` were not found in the Windows SDK/AppX paths during
the BASE-06 inventory. `reference/cdb-summary.txt` is therefore an explicit
NOT RUN expectation, not debugger output. The local DbgHelp verifier proves
the dump header, x64 system stream, exception stream and thread/module streams;
it does not prove CDB/WinDbg stack equivalence or Symbolicator line lookup.

The generated DMP, PE, PDB, collector and verifier binaries are local-only and
ignored by `fixtures/.gitignore`.
