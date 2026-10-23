"""FastAPI dependencies for authentication and role-based access control.

`CurrentUser` is required on every /api/v1/* route except /api/v1/auth/login
itself (and the unauthenticated /health* checks) -- see main.py and each
router. `require_role(...)` additionally restricts an endpoint to specific
roles (e.g. bulk detection reruns are ADMIN-only).
"""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

import models
from auth.security import decode_access_token
from db import get_db

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
        raise _CREDENTIALS_ERROR from exc

    raw_user_id = payload.get("sub")
    if raw_user_id is None:
        raise _CREDENTIALS_ERROR
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError) as exc:
        raise _CREDENTIALS_ERROR from exc

    user = db.get(models.User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


CurrentUser = Annotated[models.User, Depends(get_current_user)]


def require_role(*allowed_roles: str):
    """Returns a dependency that accepts any already-authenticated user
    whose role is in `allowed_roles`, else 403."""

    def checker(user: CurrentUser) -> models.User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {', '.join(allowed_roles)}.",
            )
        return user

    return checker
