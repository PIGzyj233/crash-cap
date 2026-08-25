# Artifact Producer compatibility matrix

The machine-readable views are `GET /api/v1/artifact-producers` and the legacy
compatibility alias `GET /api/v1/ci/producers`. Publication origin (local/CI) is
tracked separately from Artifact Producer capability.

| Producer | Status | Accepted baseline | Promotion gate |
| --- | --- | --- | --- |
| MSVC | supported | Windows native C/C++ x64 PE plus complete PDB 7.0 and standard user-mode Minidump | Frozen Phase 0 Golden: 21/21, exception/crash-thread/PDB mismatch 100%, top-3 business frames within gate, zero silent wrong symbols |
| clang-cl | experimental | Candidate PE x64 plus complete PDB 7.0 | Add clang-cl-owned fixtures and reference summaries, then pass the frozen metrics |
| Crashpad | experimental | Candidate Windows x64 user-mode Minidump producer | Add Crashpad-captured fixtures and pass the frozen metrics |

Build Publication v1 accepts only the MSVC baseline. The unified `crashcap`
client validates exact local paths, x64 PE/full-PDB identity, streams SHA-256 and
uploads, and waits for `ready`/`sealed`. The checked-in Windows and Linux binaries
need neither Python nor Rust.

```powershell
$env:CRASHCAP_API_URL = "http://127.0.0.1:8000/api/v1"
tools\crashcap\windows-x86_64\crashcap.exe doctor
tools\crashcap\windows-x86_64\crashcap.exe publish --profile release --origin ci
```

The repository config is `crashcap.toml`; reusable GitLab jobs are in
`.gitlab/ci/crashcap.yml`. The runner must be inside the approved intranet and
must reach both API and S3 Gateway. Do not expose either anonymous endpoint to a
public hosted runner.
