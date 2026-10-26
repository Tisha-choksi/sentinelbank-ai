"""Assigns a request ID to every inbound request (reusing an incoming
X-Request-ID header if the caller already has one, e.g. from an upstream
proxy), logs a structured "request completed" line, records Prometheus
request-count/latency metrics, and echoes the request ID back in the
response headers for client-side support/debugging correlation.

This middleware is the authoritative safety net for unhandled exceptions,
not just a thin wrapper around error_handlers.py's `@app.exception_handler
(Exception)`: Starlette's BaseHTTPMiddleware has a long-standing quirk
where an exception raised deeper in the stack can propagate straight past
a registered Exception handler and out through `call_next()` here, rather
than arriving as a normal Response. Without the try/except below, that
path would skip metrics/logging entirely AND return a response with no
X-Request-ID header -- exactly the failure mode this middleware exists to
prevent. The registered handler in error_handlers.py still runs first and
covers the common case; this is strictly a backstop for the cases it
doesn't reach.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from observability.metrics import record_request
from observability.request_context import get_request_id, set_request_id

logger = logging.getLogger("sentinelbank.request")


def _path_template(request: Request) -> str:
    """The route template ("/api/v1/alerts/{alert_id}") rather than the
    resolved path, so metrics/logs group by endpoint, not by every distinct
    ID ever requested."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # Backstop: see module docstring. error_handlers.py's handler
            # didn't catch this one, so this IS the last line of defense
            # before it would otherwise reach the client as a raw 500 with
            # no request_id and (depending on server config) a leaked
            # traceback.
            duration_seconds = time.monotonic() - start
            path_template = _path_template(request)
            record_request(request.method, path_template, 500, duration_seconds)
            logger.exception(
                "unhandled_exception_bypassed_handler",
                extra={"method": request.method, "path": path_template},
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error. Include the request_id when reporting this.",
                    "request_id": get_request_id(),
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response

        duration_seconds = time.monotonic() - start
        path_template = _path_template(request)
        record_request(request.method, path_template, response.status_code, duration_seconds)

        log_level = logging.WARNING if response.status_code >= 500 else logging.INFO
        logger.log(
            log_level,
            "request_completed",
            extra={
                "method": request.method,
                "path": path_template,
                "status_code": response.status_code,
                "duration_ms": round(duration_seconds * 1000, 1),
            },
        )

        response.headers["X-Request-ID"] = request_id
        return response
