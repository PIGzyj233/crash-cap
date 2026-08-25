# Crash-Cap Platform

The platform consists of a FastAPI control plane, Dramatiq workers, a React frontend,
the local-only operations CLI, and the native idempotent `crashcap` local/CI publisher.
The `/api/v1` HTTP prefix and Phase 1 `1.0` readers remain stable; Build Manifest
`2.0` is used only when source-bundle metadata is required.

The production path uses PostgreSQL, Redis, RustFS through the standard S3 API,
and one-shot `dmp-core` containers. Unit and contract tests use SQLite, an
on-disk object-store double, and an in-process durable-task double; those test
doubles are deliberately selected only by explicit settings.

```text
uv sync --extra dev
uv run pytest
uv run ruff check api worker cli tests
uv run mypy
../tools/crashcap/windows-x86_64/crashcap.exe --help
```

No authentication or DELETE API is present. This service must only be exposed
on a trusted intranet/VPN. Raw binary download is disabled by default.

Local/CI publication and source-bundle constraints are documented in
[the integration guide](../docs/integration/crashcap.md),
[the producer matrix](../docs/operations/phase2-ci-producer-matrix.md), and
[the source-bundle policy](../docs/operations/phase2-source-bundles.md).
The publisher CLI generates Manifest v1 from `crashcap.toml` and needs neither
Python nor a checked-out `contracts/` directory at runtime.
