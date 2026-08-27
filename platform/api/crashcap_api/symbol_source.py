from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from starlette.background import BackgroundTask

from .config import Settings
from .db import Database
from .models import ArtifactBlob, ArtifactBlobPair, Workspace
from .services.artifact_payloads import ArtifactPayloadError, BlobMaterializer, payload_head_valid
from .storage import ObjectNotFoundError, ObjectStore, create_object_store

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

    @app.exception_handler(ArtifactPayloadError)
    async def payload_error(_request: Request, error: ArtifactPayloadError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SYMBOL_PAYLOAD_UNAVAILABLE",
                    "message": error.code,
                }
            },
        )

    @app.exception_handler(ObjectNotFoundError)
    async def object_missing(_request: Request, _error: ObjectNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "SYMBOL_PAYLOAD_UNAVAILABLE",
                    "message": "payload_object_missing",
                }
            },
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        selected_database.check()
        return {"status": "ok"}

    @app.api_route(
        "/v1/workspaces/{workspace_id}/inventories/{inventory}/{debug_prefix}/{debug_rest}/{leaf}",
        methods=["GET", "HEAD"],
    )
    def fetch_symbol(
        workspace_id: str,
        inventory: int,
        debug_prefix: str,
        debug_rest: str,
        leaf: str,
        request: Request,
    ) -> Response:
        if (
            not WORKSPACE_RE.fullmatch(workspace_id)
            or inventory < 0
            or not DEBUG_PREFIX_RE.fullmatch(debug_prefix)
            or not DEBUG_REST_RE.fullmatch(debug_rest)
            or leaf not in {"executable", "debuginfo"}
        ):
            raise HTTPException(status_code=404, detail="symbol not found")
        debug_id = f"{debug_prefix}{debug_rest}"
        kind = "pe" if leaf == "executable" else "pdb"
        with selected_database.sessions() as session:
            workspace = session.get(Workspace, workspace_id)
            # In-flight analyses keep the inventory captured at Run creation.
            # A later unrelated Build may advance the Workspace counter; older
            # source IDs remain valid because Blob/pair rows are immutable and
            # the requested Unified path still carries the exact debug identity.
            if workspace is None or workspace.symbol_inventory_version < inventory:
                raise HTTPException(status_code=404, detail="symbol inventory not found")
            pair_column = (
                ArtifactBlobPair.pe_blob_id if kind == "pe" else ArtifactBlobPair.pdb_blob_id
            )
            rows = session.scalars(
                select(ArtifactBlob)
                .join(ArtifactBlobPair, pair_column == ArtifactBlob.id)
                .where(
                    ArtifactBlobPair.workspace_id == workspace_id,
                    ArtifactBlobPair.state == "published",
                    ArtifactBlob.workspace_id == workspace_id,
                    ArtifactBlob.kind == kind,
                    ArtifactBlob.verification_status == "verified",
                    ArtifactBlob.payload_verified_at.is_not(None),
                    func.lower(ArtifactBlob.debug_id) == debug_id,
                )
                .distinct()
                .order_by(ArtifactBlob.id)
            ).all()
            if len(rows) != 1:
                raise HTTPException(status_code=404, detail="symbol not found")
            blob = rows[0]

        materializer = BlobMaterializer(selected_store, selected.task_tmp_root)
        headers = {
            "Cache-Control": "private, max-age=86400, immutable",
            "X-Content-Type-Options": "nosniff",
        }
        if request.method == "HEAD":
            if not payload_head_valid(selected_store, blob):
                raise HTTPException(status_code=503, detail="symbol payload unavailable")
            headers["Content-Length"] = str(blob.size)
            return Response(status_code=200, media_type="application/octet-stream", headers=headers)

        try:
            materializer.payload_head(blob)
        except ObjectNotFoundError as error:
            raise HTTPException(status_code=503, detail="symbol payload missing") from error

        root = Path(tempfile.mkdtemp(prefix=f"symbol-{blob.id}-", dir=selected.task_tmp_root))
        destination = root / leaf
        try:
            materializer.materialize(blob, destination)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return FileResponse(
            destination,
            media_type="application/octet-stream",
            filename=None,
            headers=headers,
            background=BackgroundTask(shutil.rmtree, root, ignore_errors=True),
        )

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
