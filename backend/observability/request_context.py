"""A per-request ID, available anywhere in the call stack via a ContextVar
rather than threaded through every function signature -- so code deep
inside detection/investigation logic can log with the same request_id as
the route handler that invoked it, with no coupling between them.
"""

from __future__ import annotations

from contextvars import ContextVar

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)
