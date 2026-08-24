from __future__ import annotations

from pathlib import Path

import pytest
from crashcap_api.migrate import migration_config

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def test_migration_config_uses_database_only_configuration() -> None:
    url = "postgresql+psycopg://crashcap:p%40ss@postgres:5432/crashcap"

    config = migration_config(database_url=url, migrations_root=MIGRATIONS)

    assert config.get_main_option("sqlalchemy.url") == url
    assert Path(config.get_main_option("script_location")) == MIGRATIONS.resolve()


def test_migration_config_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRASHCAP_DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="CRASHCAP_DATABASE_URL is required"):
        migration_config(migrations_root=MIGRATIONS)


def test_migration_config_rejects_missing_revision_root(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Alembic config not found"):
        migration_config(database_url="postgresql://unused", migrations_root=tmp_path)
