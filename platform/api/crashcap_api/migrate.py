from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

CONTAINER_MIGRATIONS_ROOT = Path("/opt/crashcap/migrations")
REPOSITORY_MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"


def migration_config(
    *,
    database_url: str | None = None,
    migrations_root: Path | None = None,
) -> Config:
    """Build an Alembic config without loading the application Settings object."""

    resolved_url = database_url or os.environ.get("CRASHCAP_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError("CRASHCAP_DATABASE_URL is required for crashcap-migrate")

    if migrations_root is None:
        configured_root = os.environ.get("CRASHCAP_MIGRATIONS_ROOT")
        if configured_root:
            migrations_root = Path(configured_root)
        elif CONTAINER_MIGRATIONS_ROOT.is_dir():
            migrations_root = CONTAINER_MIGRATIONS_ROOT
        else:
            migrations_root = REPOSITORY_MIGRATIONS_ROOT

    resolved_root = migrations_root.resolve()
    config_path = resolved_root / "alembic.ini"
    if not config_path.is_file():
        raise RuntimeError(f"Alembic config not found: {config_path}")

    config = Config(str(config_path))
    config.set_main_option("script_location", str(resolved_root))
    # ConfigParser treats percent signs as interpolation markers. Database URLs
    # commonly contain percent-encoded credentials, so escape them in-memory.
    config.set_main_option("sqlalchemy.url", resolved_url.replace("%", "%%"))
    return config


def run() -> None:
    """Upgrade the database once, then exit for Compose dependency gating."""

    command.upgrade(migration_config(), "head")


if __name__ == "__main__":
    run()
