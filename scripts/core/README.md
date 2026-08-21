# Core OCI verification

`verify_oci.py` builds `deploy/core/Dockerfile`, checks the pinned builder and
runtime image identities, exports the runtime filesystem to ensure build-time
files were not copied, and runs `dmp-core version` plus a minimal x64
`dmp-core inspect` under a non-root, read-only-root container.

Run from the repository root or any working directory:

```text
python scripts/core/verify_oci.py
```

The command writes `docs/evidence/core-oci.json` and
`docs/evidence/core-oci.md`. It uses only a generated temporary dump and does
not read credentials. `--no-build` is available for smoke-only reruns against
an existing local image.
