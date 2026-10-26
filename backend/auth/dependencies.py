"""FastAPI dependencies for authentication and role-based access control.

`CurrentUser` is required on every /api/v1/* route except /api/v1/auth/login
itself (and the unauthenticated /health* checks) -- see main.py and each
router. `require_role(...)` additionally restricts an endpoint to specific
roles (e.g. bulk detection reruns are ADMIN-only).

Every auth failure and denied action is logged (safely -- never the raw
token or password, see observability/logging_config.py's scrubbing
backstop) and counted in the live Prometheus metrics, per the
observability definition of done.
"""

from __future__ import annotations

import logging
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

import models
from auth.security import decode_access_token
from db import get_db
from observability.metrics import record_action_denied, record_auth_failure

logger = logging.getLogger("sentinelbank.auth")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> models.User:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        logger.warning("invalid_token", extra={"reason": type(exc).__name__})
        record_auth_failure("invalid_token")
        raise _CREDENTIALS_ERROR from exc

    raw_user_id = payload.get("sub")
    if raw_user_id is None:
        logger.warning("invalid_token", extra={"reason": "missing_subject"})
        record_auth_failure("invalid_token")
        raise _CREDENTIALS_ERROR
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        logger.warning("invalid_token", extra={"reason": "non_integer_subject"})
        record_auth_failure("invalid_token")
        raise _CREDENTIALS_ERROR from exc

    user = db.get(models.User, user_id)
    if user is None or not user.is_active:
        logger.warning(
            "invalid_token",
            extra={"reason": "unknown_or_inactive_user", "user_id": user_id},
        )
        record_auth_failure("invalid_token")
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]


def require_role(*allowed_roles: str):
    """Returns a dependency that accepts any already-authenticated user
    whose role is in `allowed_roles`, else 403."""

    def checker(user: CurrentUser, request: Request) -> models.User:
        if user.role not in allowed_roles:
            path_template = getattr(request.scope.get("route"), "path", request.url.path)
            logger.warning(
                "action_denied",
                extra={
                    "user_email": user.email,
                    "user_role": user.role,
                    "required_roles": list(allowed_roles),
                    "path": path_template,
                },
            )
            record_action_denied(path_template, user.role)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return user

    return checker
