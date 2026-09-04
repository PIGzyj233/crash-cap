"""Qualification-gated symbol imports; uploads are bound to one immutable item."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from .errors import ApiError
from .ids import new_ulid
from .models import SymbolImportFile
from .response_contracts import ERROR_RESPONSES
from .routes import SessionDep, SettingsDep, StoreDep
from .services.symbol_imports import (
    complete_item,
    create_import,
    get_item,
    import_result,
    require_enabled,
)
from .storage import stream_sha256

router = APIRouter(prefix="/api/v2/symbol-imports", responses=ERROR_RESPONSES)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportFileClaim(StrictModel):
    name: str = Field(min_length=1, max_length=1024)
    raw_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    raw_size: int = Field(gt=0, le=2**53 - 1, strict=True)


class ImportPairClaim(StrictModel):
    client_pair_id: str = Field(min_length=1, max_length=128)
    pe: ImportFileClaim
    pdb: ImportFileClaim


class ImportRequest(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_label: str = Field(min_length=1, max_length=512)
    pairs: list[ImportPairClaim] = Field(min_length=1, max_length=200)


class ImportItemResult(StrictModel):
    item_id: str
    client_pair_id: str
    state: Literal["staging", "queued", "verifying", "available", "rejected", "retry_exhausted"]
    pair_id: str | None
    error_code: str | None
    pe_upload_id: str
    pdb_upload_id: str


class ImportResult(StrictModel):
    import_id: str
    items: list[ImportItemResult]


class FileResult(StrictModel):
    upload_id: str
    state: Literal["uploaded"] = "uploaded"


@router.post(
    "", response_model=ImportResult, status_code=201, responses={200: {"model": ImportResult}}
)
def post_import(
    body: ImportRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> object:
    require_enabled(settings)
    batch, created = create_import(session, settings, body.model_dump())
    session.commit()
    response.status_code = 201 if created else 200
    return import_result(session, batch.id)


@router.get("/{import_id}", response_model=ImportResult)
def get_import(import_id: str, session: SessionDep) -> object:
    return import_result(session, import_id)


@router.post("/{import_id}/items/{item_id}/complete", response_model=ImportResult, status_code=202)
def post_complete(
    import_id: str, item_id: str, session: SessionDep, settings: SettingsDep
) -> object:
    require_enabled(settings)
    complete_item(session, settings, import_id, item_id)
    session.commit()
    return import_result(session, import_id)


@router.put(
    "/{import_id}/items/{item_id}/files/{kind}",
    response_model=FileResult,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def put_file(
    import_id: str,
    item_id: str,
    kind: Literal["pe", "pdb"],
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    store: StoreDep,
) -> FileResult:
    require_enabled(settings)
    get_item(session, import_id, item_id)
    file = session.scalar(
        select(SymbolImportFile).where(
            SymbolImportFile.item_id == item_id, SymbolImportFile.kind == kind
        )
    )
    assert file is not None
    file_id, expected_sha, expected_size = file.id, file.raw_sha256, file.raw_size
    # No DB transaction or row lock spans the client upload or object-store I/O.
    session.rollback()
    if request.headers.get("content-encoding", "identity") != "identity":
        raise ApiError(
            "VALIDATION", "Import staging accepts raw identity bytes only", status_code=422
        )
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdecimal() or int(declared) != expected_size):
        raise ApiError(
            "UPLOAD_SIZE_MISMATCH", "Content-Length differs from the file claim", status_code=422
        )
    key = f"symbol-import-staging/{import_id}/{item_id}/{file_id}/{new_ulid()}"
    with tempfile.TemporaryDirectory(prefix="crashcap-import-upload-") as temporary:
        path = Path(temporary) / "payload"
        total, sha = 0, hashlib.sha256()
        with path.open("xb") as target:
            async for block in request.stream():
                total += len(block)
                if total > expected_size:
                    raise ApiError(
                        "UPLOAD_SIZE_MISMATCH", "Upload exceeds the file claim", status_code=422
                    )
                sha.update(block)
                target.write(block)
        if total != expected_size or sha.hexdigest() != expected_sha:
            raise ApiError(
                "UPLOAD_HASH_MISMATCH", "Uploaded bytes differ from the file claim", status_code=422
            )
        await run_in_threadpool(store.put_file, key, path, "application/octet-stream")
        actual_sha, actual_size, _ = await run_in_threadpool(stream_sha256, store, key)
        if (actual_sha, actual_size) != (expected_sha, expected_size):
            raise ApiError(
                "STAGING_READBACK_FAILED",
                "Staged upload failed readback verification",
                status_code=503,
            )
    item = get_item(session, import_id, item_id, lock=True)
    file = session.scalar(
        select(SymbolImportFile)
        .where(SymbolImportFile.id == file_id)
        .execution_options(populate_existing=True)
    )
    assert file is not None
    if file.object_key is None:
        if item.state != "staging":
            raise ApiError(
                "IMPORT_FROZEN", "Completed import files cannot be changed", status_code=409
            )
        file.object_key = key
    # Same-byte retries never overwrite or rebind the winning object. Unbound
    # attempt objects stay in the staging namespace for later retention work.
    session.commit()
    return FileResult(upload_id=file_id)
