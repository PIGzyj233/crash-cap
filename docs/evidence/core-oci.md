# P0-A04 Core OCI evidence

- Overall status: **PASS**
- Checked (UTC): `2026-08-20T18:12:20.192034Z`
- Image: `crash-cap/dmp-core:p0-a04`
- Remote CI executed: **no** (local Docker CLI only)

## Base images

| Stage | Pinned reference | OS/arch | Local ID | Status |
| --- | --- | --- | --- | --- |
| `builder` | `rust:1.96-slim-bookworm@sha256:e18a79fc84dfcfc3ab5ba72290398a644c135c97eaa881447fddc354ee4701a3` | `linux/amd64` | `sha256:e18a79fc84dfcfc3ab5ba72290398a644c135c97eaa881447fddc354ee4701a3` | PASS |
| `runtime` | `gcr.io/distroless/cc-debian12:nonroot@sha256:adcd20c7b4c988b73cbfbddb26d2eee574571e6d7c9ffea29b3821e0690efb77` | `linux/amd64` | `sha256:adcd20c7b4c988b73cbfbddb26d2eee574571e6d7c9ffea29b3821e0690efb77` | PASS |

## Build and image identity

- Build status: **PASS**
- Build command: `docker build --pull --platform linux/amd64 --file 'E:\ai-services\crash-cap\deploy\core\Dockerfile' --tag crash-cap/dmp-core:p0-a04 .`
- Local image ID: `sha256:82b5e20837dcdf0857e955f8871c934ab32d4b7ab969fdaa2c9437b23697332b`
- Runtime user: `65532:65532`
- Runtime filesystem check: **PASS**
- Runtime files: `1789`; required binary present: `True`

## Smoke checks

- Read-only root configuration: **PASS**
- Runtime limits: `{'memory_bytes': 536870912, 'memory_swap_bytes': 536870912, 'pids_limit': 64, 'nano_cpus': 1000000000, 'network_mode': 'none', 'tmpfs': {'/tmp': 'rw,nosuid,nodev,noexec,size=16m'}}`
- `dmp-core version` in read-only container: **PASS**
- `dmp-core inspect` in read-only container: **PASS**

Exact command/output tails and the parsed inspect JSON are kept in `core-oci.json`.

## Boundary

This is a local Docker Desktop verification. It does not prove Windows DMP generation, remote CI execution, production registry provenance, or a full Symbolicator analysis.
