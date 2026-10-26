"""Login and the current-user endpoint. There is no public registration --
accounts are provisioned internally (seeded for this prototype in
db_seed.py), matching how real banking staff accounts are issued.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from auth.dependencies import CurrentUser
from auth.security import create_access_token, verify_password
from db import get_db
from observability.metrics import record_auth_failure

logger = logging.getLogger("sentinelbank.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession):
    user = db.execute(
        select(models.User).where(models.User.email == payload.email)
    ).scalar_one_or_none()

    # Same generic message whether the email doesn't exist or the password
    # is wrong -- never reveal which one it was. The attempted *email* is
    # safe to log (useful for spotting brute-force/enumeration attempts);
    # the attempted password never is, and never appears in this function.
    if user is None or not user.is_active or not verify_password(
        payload.password, user.hashed_password
    ):
        logger.warning(
            "login_failed",
            extra={"attempted_email": payload.email, "reason": "invalid_credentials"},
        )
        record_auth_failure("invalid_credentials")
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_access_token(subject=str(user.id), role=user.role)
    return TokenResponse(access_token=token, role=user.role, full_name=user.full_name)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user
