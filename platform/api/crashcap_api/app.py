from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.processor import WorkerProcessor
from crashcap_worker.symbols import SymbolIngestor
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from . import __version__
from .config import Settings
from .db import Database
from .errors import register_error_handlers
from .ids import new_ulid
from .metrics import refresh_operational_metrics
from .queueing import MemoryTaskDispatcher, create_dispatcher
from .redaction import configure_logging
from .routes import router
from .services.common import assert_no_delete_routes
from .storage import create_object_store

HTTP_REQUESTS = Counter(
    "crashcap_http_requests_total",
    "HTTP requests handled by the anonymous Phase 1 API",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "crashcap_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
)


def create_app(settings: Settings | None = None) -> FastAPI:
    selected = settings or Settings()
    configure_logging(selected.log_level)
    database = Database(selected)
    store = create_object_store(selected)
    dispatcher = create_dispatcher(selected)
    processor = WorkerProcessor(
        selected,
        database.sessions,
        store,
        dispatcher,
        CoreExecutor(selected),
        SymbolIngestor(selected),
    )
    if isinstance(dispatcher, MemoryTaskDispatcher):
        dispatcher.register("verify_upload", processor.verify_upload)
        dispatcher.register("ingest_artifact", processor.ingest_artifact)
        dispatcher.register("reindex_symbols", processor.reindex_symbols)
        dispatcher.register("analyze_occurrence", processor.analyze_occurrence)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        database.assert_supported_postgres()
        database.check()
        yield
        database.dispose()

    app = FastAPI(
        title="Crash-Cap API",
        version=__version__,
        description=(
            "Anonymous trusted-intranet crash analysis control plane. "
            "There are intentionally no login, RBAC, or DELETE endpoints."
        ),
        lifespan=lifespan,
    )
    app.state.settings = selected
    app.state.database = database
    app.state.store = store
    app.state.dispatcher = dispatcher
    app.state.processor = processor
    register_error_handlers(app)
    if selected.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(selected.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH"],
            allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id")
        if not request_id or len(request_id) > 128 or any(ord(char) < 32 for char in request_id):
            request_id = f"req_{new_ulid()}"
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        duration = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
        HTTP_DURATION.labels(request.method, route_path).observe(duration)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz", include_in_schema=False)
    def health() -> JSONResponse:
        database.check()
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/readyz", include_in_schema=False)
    def ready() -> JSONResponse:
        database.check()
        return JSONResponse(
            {
                "status": "ready",
                "queue": selected.queue_mode,
                "object_store": selected.object_store_backend,
            }
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        refresh_operational_metrics(database.sessions, dispatcher)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(router)
    # FastAPI may represent included routers as nested route objects; validate
    # the authoritative Phase 1 router directly so a DELETE cannot hide there.
    assert_no_delete_routes(router.routes)
    return app
