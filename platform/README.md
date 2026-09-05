# Crash-Cap Platform

FastAPI, Dramatiq, PostgreSQL, S3-compatible storage, Symbolicator and React implement HTTP v3 and Canonical 2.0. Uploads are enabled by default; each file is verified by the real Core parser in production. Unit fixtures explicitly select test storage and queues.

```text
uv sync --extra dev
uv run pytest
uv run ruff check api worker cli tests migrations
uv run mypy api worker cli
```

See [the upload integration guide](../docs/integration/crashcap.md), [design](../docs/design.md), and [deployment guide](../docs/upload-v3-guide.md). New deployments start at the empty v3 baseline. Rollback restores the old stack and its data backup, never a reverse migration. The anonymous platform is deployed on a trusted intranet; raw downloads remain disabled by default.
