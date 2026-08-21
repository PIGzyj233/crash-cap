from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .redaction import redact, sanitize_details


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = redact(message)
        super().__init__(self.message)
        self.status_code = status_code
        self.details = sanitize_details(details or {})


def error_payload(
    code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": redact(message),
            "details": sanitize_details(details or {}),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error_payload(error.code, error.message, error.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, error: RequestValidationError
    ) -> JSONResponse:
        safe_errors = []
        for item in error.errors():
            safe_errors.append(
                {
                    "type": item.get("type"),
                    "loc": [str(part) for part in item.get("loc", ())],
                    "msg": item.get("msg"),
                }
            )
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "VALIDATION", "request validation failed", {"errors": safe_errors}
            ),
        )
