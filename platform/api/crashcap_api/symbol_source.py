from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .catalog_source import install_catalog_source
from .config import Settings
from .db import Database
from .storage import ObjectStore, create_object_store

WORKSPACE_RE = re.compile(r"^wsp_[0-9A-HJKMNP-TV-Z]{26}$")
DEBUG_PREFIX_RE = re.compile(r"^[0-9a-f]{2}$")
DEBUG_REST_RE = re.compile(r"^[0-9a-f]{30,94}$")


def create_symbol_source_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    store: ObjectStore | None = None,
) -> FastAPI:
    selected = settings or Settings()
    selected_database = database or Database(selected)
    selected_store = store or create_object_store(selected)
    owns_database = database is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        selected_database.assert_supported_postgres()
        selected_database.check()
        selected.task_tmp_root.mkdir(parents=True, exist_ok=True)
        yield
        if owns_database:
            selected_database.dispose()

    app = FastAPI(
        title="Crash-Cap Internal Symbol Source",
        description="Analysis-network-only Workspace-scoped Unified symbol source.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        selected_database.check()
        return {"status": "ok"}

    install_catalog_source(app, selected, selected_database.sessions, selected_store)
    return app


def run() -> None:
    application = create_symbol_source_app()
    uvicorn.run(
        application,
        host="0.0.0.0",  # noqa: S104 - reachable only on the internal analysis network
        port=int(os.environ.get("PORT", "8081")),
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    run()
