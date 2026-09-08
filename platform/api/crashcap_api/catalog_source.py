"""Private exact-content HTTP routes for the frozen pair Symbolicator source."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import Receive, Scope, Send

from .config import Settings
from .ids import new_ulid
from .services.catalog_materials import (
    CatalogMaterialError,
    select_material,
)
from .services.material_cache import MaterialCache
from .storage import ObjectStore

LOGGER = logging.getLogger(__name__)


class CachedMaterialResponse(FileResponse):
    def __init__(self, path: Path, headers: dict[str, str], release: Callable[[], None]) -> None:
        self.release = release
        super().__init__(path, media_type="application/octet-stream", headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.release()


def install_catalog_source(
    app: FastAPI, settings: Settings, sessions: sessionmaker[Session], store: ObjectStore
) -> None:
    capacity = threading.BoundedSemaphore(settings.catalog_source_max_downloads)
    cache = MaterialCache(settings, store)
    app.state.material_cache = cache

    @app.api_route(
        "/v3/pairs/{workspace_id}/{pair_id}/{debug_prefix}/{debug_rest}/{leaf}",
        methods=["GET", "HEAD"],
    )
    def fetch(
        workspace_id: str,
        pair_id: str,
        debug_prefix: str,
        debug_rest: str,
        leaf: str,
        request: Request,
    ) -> Response:
        request_id = "csr_" + new_ulid()
        material = None
        leased = False
        acquired = False
        try:
            if not settings.catalog_source_enabled:
                raise CatalogMaterialError("CATALOG_SOURCE_DISABLED", "unknown")
            if (
                re.fullmatch(r"[0-9a-f]{64}", pair_id) is None
                or re.fullmatch(r"[0-9a-f]{2}", debug_prefix) is None
                or re.fullmatch(r"[0-9a-f]{30,94}", debug_rest) is None
                or leaf not in {"executable", "debuginfo"}
            ):
                raise CatalogMaterialError("CATALOG_PATH_NOT_FOUND", "permanent", status=404)
            with sessions() as session:
                material = select_material(
                    session,
                    pair_id,
                    debug_prefix + debug_rest,
                    "pe" if leaf == "executable" else "pdb",
                    max_locations=settings.catalog_source_max_locations,
                    workspace_id=workspace_id,
                )
            acquired = capacity.acquire(blocking=False)
            if not acquired:
                raise CatalogMaterialError("CATALOG_DOWNLOAD_BUSY", "transient")
            path, hit = cache.acquire(material)
            leased = True
            headers = {
                "Cache-Control": "private, max-age=86400, immutable",
                "ETag": f'"sha256:{material.raw_sha256}"',
                "X-Content-Type-Options": "nosniff",
                "X-CrashCap-Source-ID": f"crash-cap:pair:{pair_id}:http-v3",
                "X-CrashCap-Raw-SHA256": material.raw_sha256,
                "X-Request-ID": request_id,
                "X-CrashCap-Cache": "hit" if hit else "materialized",
            }
            LOGGER.info(
                "catalog source verified request_id=%s pair_id=%s kind=%s cache_hit=%s",
                request_id,
                pair_id,
                material.kind,
                hit,
            )

            def release() -> None:
                assert material is not None
                cache.release(material)
                capacity.release()

            response = CachedMaterialResponse(path, headers, release)
            leased = False
            acquired = False
            return response
        except CatalogMaterialError as error:
            LOGGER.warning(
                "catalog source failed request_id=%s pair_id=%s code=%s failure_class=%s",
                request_id,
                pair_id[:64],
                error.code,
                error.failure_class,
            )
            return JSONResponse(
                status_code=error.status,
                content={
                    "error": {
                        "code": error.code,
                        "failure_class": error.failure_class,
                        "request_id": request_id,
                    }
                },
                headers={
                    "Cache-Control": "no-store",
                    "X-Request-ID": request_id,
                    **({"Retry-After": "1"} if error.failure_class == "transient" else {}),
                },
            )
        finally:
            if acquired:
                capacity.release()
            if leased and material is not None:
                cache.release(material)
