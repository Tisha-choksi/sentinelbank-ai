"""Exception handlers enforcing one consistent error response shape across
the whole API: `{"detail": ..., "request_id": ...}`.

HTTPException and validation-error details are messages this codebase
wrote itself, so they're already safe to return as-is. Anything
*unexpected* (a genuine bug, a DB error, etc.) is logged in full
server-side -- including the traceback, via logger.exception -- and
reduced to a generic message before it ever reaches the client. An
unhandled exception's own message can easily contain a SQL fragment, a
file path, or other internals that have no business being public.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from observability.request_context import get_request_id

logger = logging.getLogger("sentinelbank.errors")

_SENSITIVE_FIELD_NAMES = {"password", "hashed_password", "access_token", "token"}


def _scrub_validation_errors(errors: list[dict]) -> list[dict]:
    """Pydantic validation errors echo back the offending input value --
    useful for "amount must be positive", but never acceptable for a field
    named like a credential, even though that just means someone's own
    attempted (and failed) password is involved, not a stored secret.
    """
    scrubbed = []
    for err in errors:
        err = dict(err)
        loc = err.get("loc", ())
        if any(str(part).lower() in _SENSITIVE_FIELD_NAMES for part in loc):
            err.pop("input", None)
        scrubbed.append(err)
    return scrubbed


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": get_request_id()},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": _scrub_validation_errors(exc.errors()),
                "request_id": get_request_id(),
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        logger.exception(
            "unhandled_exception",
            extra={"method": request.method, "path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error. Include the request_id when reporting this.",
                "request_id": get_request_id(),
            },
        )
