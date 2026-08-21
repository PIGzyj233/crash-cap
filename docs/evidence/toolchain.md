# Phase 0 toolchain evidence

Checked (UTC): `2026-08-20T18:26:30.0709644Z`

This is a point-in-time, read-only inventory. `available` means the command or local image was observed; it does not prove a complete Phase 0 analysis path.

| Component | Status | Version / identity | Path or reference |
| --- | --- | --- | --- |
| Rust compiler | `available` | rustc 1.96.1 (31fca3adb 2026-06-26)<br>binary: rustc<br>commit-hash: 31fca3adb283cc9dfd56b49cdee9a96eb9c96ffd | `C:\Users\Admin\.cargo\bin\rustc.exe` |
| Cargo | `available` | cargo 1.96.1 (356927216 2026-06-26) | `C:\Users\Admin\.cargo\bin\cargo.exe` |
| Docker CLI | `available` | Docker version 29.6.1, build 8900f1d | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` |
| Docker Compose plugin | `available` | Docker Compose version v5.3.0 | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` |
| docker-compose compatibility CLI | `available` | Docker Compose version v5.1.4 | `C:\Program Files\Docker\Docker\resources\bin\docker-compose.exe` |
| CMake | `available` | cmake version 4.3.1-msvc1<br><br>CMake suite maintained and supported by Kitware (kitware.com/cmake). | `C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe` |
| MSVC compiler | `available` | Microsoft (R) C/C++ Optimizing Compiler Version 19.51.36248 for x64<br>版权所有(C) Microsoft Corporation。保留所有权利。<br>System.Management.Automation.RemoteException | `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231\bin\HostX64\x64\cl.exe` |
| MSVC linker | `available` | Microsoft (R) Incremental Linker Version 14.51.36248.0<br>Copyright (C) Microsoft Corporation.  All rights reserved.<br> | `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231\bin\HostX64\x64\link.exe` |
| MSVC dumpbin | `available` | Microsoft (R) COFF/PE Dumper Version 14.51.36248.0<br>Copyright (C) Microsoft Corporation.  All rights reserved.<br> | `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Tools\MSVC\14.51.36231\bin\HostX64\x64\dumpbin.exe` |
| CDB | `available` | cdb version 10.0.29617.1000 | `E:\ai-services\crash-cap\scripts\symbolicator\.tools\windbg\x64-package\unpacked\amd64\cdb.exe` |
| WinDbg | `available` | 1.2606.22001.0 | `E:\ai-services\crash-cap\scripts\symbolicator\.tools\windbg\x64-package\unpacked\DbgX.Shell.exe` |
| Symbolicator CLI | `missing` |  | `symbolicator` |
| symsorter | `available` | symsorter 26.7.2 | `E:\ai-services\crash-cap\scripts\symbolicator\.tools\symsorter\26.7.2\symsorter-Windows-x86_64.exe` |
| RustFS CLI | `missing` |  | `rustfs` |
| Windows SDK | `available` | 10.0.22621.0, 10.0.26100.0 | `C:\Program Files (x86)\Windows Kits\10` |
| Windows SDK DbgHelp.dll | `available` |  | `C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll` |
| VS vcvarsall x64 | `available` | 14.51.36231 | `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvarsall.bat` |
| RustFS qualified image | `available` | version=v1.0.0-rc.2<br>ghcr.io/rustfs/rustfs@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831 | `ghcr.io/rustfs/rustfs:1.0.0-rc.2-glibc@sha256:450779bc3f86400e934b4506e2ca53e1e3c2e332965ae0c55fe8b3afed89c831` |
| Symbolicator pinned image | `available` | ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959 | `ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959` |
| Core local OCI image | `available` | crash-cap/dmp-core@sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b | `crash-cap/dmp-core:p0-a04` |

## Re-run

```text
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/env/check-toolchain.ps1
```

## Evidence boundary

- Rust, Cargo, Docker/Compose, MSVC/SDK, CMake, CDB/WinDbg, Symbolicator and RustFS status is recorded in `toolchain.json`.
- The RustFS digest is only a local-image identity until the S3 qualification tests pin and approve it.
- Missing CDB/WinDbg means the fixture reference transcript remains an expectation, not a debugger-backed result.
- Missing Symbolicator is an environment blocker for the SYM lane; this inventory does not install or pull it. CMake is available through the VS installation but is not required by the current fixture generator.
