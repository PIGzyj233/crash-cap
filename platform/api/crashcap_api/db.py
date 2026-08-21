from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import Settings
from .models import Base


class Database:
    def __init__(self, settings: Settings) -> None:
        connect_args: dict[str, object] = {}
        if settings.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        engine_options: dict[str, object] = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if settings.database_url in {
            "sqlite://",
            "sqlite+pysqlite://",
            "sqlite:///:memory:",
            "sqlite+pysqlite:///:memory:",
        }:
            engine_options["poolclass"] = StaticPool
        self.engine = create_engine(settings.database_url, **engine_options)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.sessions = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )
        if settings.create_schema:
            Base.metadata.create_all(self.engine)

    def session(self) -> Generator[Session]:
        with self.sessions() as session:
            yield session

    def check(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def assert_supported_postgres(self) -> None:
        if self.engine.dialect.name != "postgresql":
            return
        with self.engine.connect() as connection:
            version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
        if version < 150000:
            raise RuntimeError("Crash-Cap requires PostgreSQL 15+ for NULLS NOT DISTINCT")

    def dispose(self) -> None:
        self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
