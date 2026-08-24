# Crash-Cap Platform

Phase 2 consists of a FastAPI control plane, Dramatiq workers, a React frontend,
the local-only operations CLI, and the native idempotent `crashcap-ci` producer CLI.
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
../tools/crashcap-ci/windows-x86_64/crashcap-ci.exe --help
```

No authentication or DELETE API is present. This service must only be exposed
on a trusted intranet/VPN. Raw binary download is disabled by default.

Phase 2 CI publication and source-bundle constraints are documented in
[the third-party CI integration guide](../docs/integration/crashcap-ci.md),
[the producer matrix](../docs/operations/phase2-ci-producer-matrix.md), and
[the source-bundle policy](../docs/operations/phase2-source-bundles.md).
The producer CLI embeds both accepted Manifest schemas and needs neither Python
nor a checked-out `contracts/` directory at runtime.
