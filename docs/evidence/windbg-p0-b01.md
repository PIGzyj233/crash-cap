# Portable CDB reference evidence

The machine-level CDB/WinDbg probes in the initial toolchain inventory were
missing from `PATH`. A portable official WinDbg package was therefore obtained
without installing a debugger:

```text
winget download --id Microsoft.WinDbg --exact --version 1.2606.22001.0 --download-directory scripts/symbolicator/.tools/windbg --accept-source-agreements --accept-package-agreements --disable-interactivity
```

The downloaded MSIX was hash-verified by `winget` and the local observed hash
is recorded in `windbg-p0-b01.json`:

```text
package: Microsoft.WinDbg 1.2606.22001.0
sha256: 12e63fb884347567bdd35f67f7aad61b26a08f8404553dad6951a10776f7d771
x64 inner MSIX sha256: ae309d63724c72b9918ecc72f94a594e6dbfa4631757a7138943ac3367767ae0
```

The bundle can be unpacked without registering the app (7-Zip is required):

```text
7z e scripts/symbolicator/.tools/windbg/WinDbg_1.2606.22001.0_X64_msix_en-US.msix windbg_win-x64.msix -oscripts/symbolicator/.tools/windbg/x64-package
7z x scripts/symbolicator/.tools/windbg/x64-package/windbg_win-x64.msix -oscripts/symbolicator/.tools/windbg/x64-package/unpacked
```

The x64 package was unpacked below the ignored
`scripts/symbolicator/.tools/windbg/x64-package/unpacked/amd64/` directory.
It contains `cdb.exe` version `10.0.29617.1000`; no machine-level installation
or registry change was performed.

## Reproduction

With the official MSIX downloaded and unpacked to the paths above, run:

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/symbolicator/windbg/verify_portable_cdb.ps1
```

The script invokes:

```text
cdb.exe -z fixtures/p0-b01-null-read/generated/null-read.dmp -y fixtures/p0-b01-null-read/generated -lines -cf scripts/symbolicator/windbg/cdb-p0-b01.commands
```

The command file reloads symbols, runs `!analyze -v`, selects `.ecxr`, prints
`kv`, and quits. The output is reduced to machine-readable evidence; no dump,
PE, PDB, or debugger package is tracked.

## Observed result

The portable x64 CDB run returned exit code `0` and agreed with the local
DbgHelp verifier:

```text
status: PASS_WITH_OS_SYMBOL_BOUNDARY
exception: 0xC0000005
exception_address: 0x00007FF76C371322
function: null_read_target!crashcap::trigger_null_read
source: scripts/fixtures/null_read_target.cpp:76
```

The CDB symbol path resolved the application PE/PDB and source line. Because no
Windows OS symbol cache was supplied, `!analyze -v` reports
`WRONG_SYMBOLS`/missing `ntdll`, `kernel32`, and `KERNELBASE` symbols. That is an
explicit debugger boundary, not a failure of the application-symbol result.
The full command, package hash, CDB hash/version, parsed result, and boundary
are in [windbg-p0-b01.json](windbg-p0-b01.json).
