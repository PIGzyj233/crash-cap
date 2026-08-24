# Native crashcap-ci delivery

New producer projects should start with the
[third-party CI integration guide](../../docs/integration/crashcap-ci.md). It
covers MSVC build requirements, the Build Manifest, runner configuration,
success criteria, idempotent retries, and troubleshooting.

This directory contains the fixed-path, checked-in producer binaries:

- `windows-x86_64/crashcap-ci.exe`: Windows x64 with the MSVC CRT linked statically.
- `linux-x86_64/crashcap-ci`: Linux x64 statically linked against musl.

Consumers must verify the matching entry in `SHA256SUMS` before execution. The
machine-readable `release.json` records the pinned Rust compiler, target,
linkage, build flags, and hashes without embedding a build timestamp.

Maintainers rebuild both artifacts from the repository root with:

```powershell
./scripts/crashcap-ci/build-release.ps1
```

The Linux build runs in the pinned Rust Docker image. The delivered binaries
embed Build Manifest v1/v2 schemas and do not require Python, Rust, OpenSSL, or
the repository's `contracts/` directory at runtime.

## GitLab example

Include `.gitlab/ci/crashcap-ci.yml`, then extend the template matching the
runner operating system:

```yaml
include:
  - local: /.gitlab/ci/crashcap-ci.yml

publish:crashcap-build:
  extends: .crashcap-ci:windows
  variables:
    CRASHCAP_WORKSPACE: "desktop-client"
    CRASHCAP_MANIFEST: "out/build-manifest.json"
    CRASHCAP_ARTIFACT_ROOT: "out/build-package"
```

Set `CRASHCAP_API_URL` as a GitLab CI/CD variable. The template uses
`CI_PIPELINE_ID` as the stable producer Build identity, so retrying a Job in the
same Pipeline reuses the existing Crash-Cap Build.
