# Crash-Cap Platform

Phase 1 consists of a FastAPI control plane, Dramatiq workers, a React frontend,
and a small local-only operations CLI. New writes use the stable `1.0` machine
contracts and `/api/v1` HTTP prefix.

The production path uses PostgreSQL, Redis, RustFS through the standard S3 API,
and one-shot `dmp-core` containers. Unit and contract tests use SQLite, an
on-disk object-store double, and an in-process durable-task double; those test
doubles are deliberately selected only by explicit settings.

```text
uv sync --extra dev
uv run pytest
uv run ruff check api worker cli tests
uv run mypy
```

No authentication or DELETE API is present. This service must only be exposed
on a trusted intranet/VPN. Raw binary download is disabled by default.
