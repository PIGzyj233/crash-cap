# Crash-Cap Phase 1 PostgreSQL migrations

This directory is a standalone Alembic script location for the Phase 1
anonymous, trusted-intranet data model.  It creates the 14 tables in
`docs/design.md` §10 and intentionally does not create `users`, `roles`,
`tenants`, or `memberships` tables.

PostgreSQL 15 or newer is required because `missing_symbols` uses
`UNIQUE NULLS NOT DISTINCT (workspace_id, debug_id, code_id)` so missing IDs
cannot create duplicate rows.

Render SQL without a database:

```bash
python -m alembic -c platform/migrations/alembic.ini upgrade head --sql
```

Run the migration against the configured database:

```bash
python -m alembic -c platform/migrations/alembic.ini upgrade head
python -m alembic -c platform/migrations/alembic.ini downgrade base
```

The local test suite renders both directions in PostgreSQL offline mode.  Set
`CRASH_CAP_TEST_DATABASE_URL` to enable the optional PostgreSQL integration
test.
