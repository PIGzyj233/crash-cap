# PostgreSQL migrations

PostgreSQL 15+ is required. `0001_upload_v3` is the original empty baseline; `0002_user_auth` adds local identities, sessions, upload tokens, shared throttling and attribution backfill without changing historical evidence objects.

Run `crashcap-migrate` against the configured database. To render SQL without connecting:

```sh
python -m alembic -c platform/migrations/alembic.ini upgrade head --sql
```

The authentication revision seeds ci-bot, system and legacy-unknown. Old uploads (including CLI uploads) become legacy-unknown. Restore the previous stack and data backup to roll back; reverse migration into anonymous records is not supported.

See [authentication rollout](../../docs/authentication.md). Set `QAI_CATALOG_DATABASE_URL` to an owned PostgreSQL test instance to run the real migration and history-backfill tests; tests create and remove isolated schemas.
