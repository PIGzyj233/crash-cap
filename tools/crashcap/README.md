# Native crashcap delivery

This directory is the fixed download root for the unified local/CI publisher:

- `windows-x86_64/crashcap.exe`: Windows x64, statically linked MSVC CRT.
- `linux-x86_64/crashcap`: Linux x64, statically linked musl.
- `SHA256SUMS`: post-signing hashes for both files.
- `release.json`: version, compiler, linkage, signing state and certificate fingerprint.

Read the [local and CI integration guide](../../docs/integration/crashcap.md) before use.
Consumers must verify `SHA256SUMS`; general availability additionally requires
`release.json.signing.status=authenticode-signed` and an approved certificate fingerprint.

Maintainers rebuild both targets from the repository root:

```powershell
./scripts/crashcap/build-release.ps1
```

An organization signing certificate can be applied before hashes are recorded:

```powershell
./scripts/crashcap/build-release.ps1 `
  -AuthenticodeCertificateThumbprint "<approved-thumbprint>" `
  -TimestampServer "<approved-timestamp-url>"
```

The binaries require no Python or Rust runtime. The Windows CLI publishes only
already-built x64 MSVC PE/full-PDB 7.0 artifacts; it never invokes MSBuild/CMake,
clones a repository or uploads source by default.
