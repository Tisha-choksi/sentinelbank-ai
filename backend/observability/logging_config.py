"""Structured (JSON) logging. Every emitted line carries the current
request_id (from the ContextVar set by RequestIDMiddleware) automatically,
so application code never has to pass it around explicitly -- just
`logger.warning("login_failed", extra={"attempted_email": email})`.

Anything that looks like a credential is scrubbed from `extra` fields
before serialization, as a backstop against an `extra={...}` call
accidentally including a password or token -- callers still must not log
secrets themselves (see auth/dependencies.py, api/auth.py), but this limits
the blast radius of a mistake.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from observability.request_context import get_request_id

_SENSITIVE_KEYS = {
    "password",
    "hashed_password",
    "access_token",
    "token",
    "authorization",
    "jwt_secret_key",
}

# Standard attributes every LogRecord already has -- only genuinely extra
# fields (passed via `extra={...}`) get copied into the JSON payload.
_STANDARD_LOGRECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_KEYS or key == "request_id":
                continue
            if key.lower() in _SENSITIVE_KEYS:
                continue
            payload[key] = value

        # Full traceback goes to the server-side log only -- never to an
        # HTTP response (see observability/error_handlers.py).
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn's own loggers otherwise use their own plain-text formatter;
    # route them through the same JSON handler for one consistent log
    # stream.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [handler]
        uv_logger.propagate = False
