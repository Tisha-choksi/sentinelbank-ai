"""Password hashing and JWT issuance/verification.

Password hashing uses stdlib PBKDF2-HMAC-SHA256 rather than bcrypt/argon2 to
avoid a native-compiled dependency in this prototype -- 260,000 iterations
follows OWASP's current minimum recommendation for PBKDF2-SHA256. For a real
deployment, argon2id is preferable; swapping the hash function here doesn't
change any caller.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

PBKDF2_ITERATIONS = 260_000

# The literal placeholder text from .env.example -- if this is still the
# value in use, nobody has actually set up `.env` yet. Anyone can read this
# string straight out of the public repo, so refusing to start on it is
# the one guardrail that can't be skipped by forgetting a step: it would
# otherwise let a half-configured checkout run with a secret everyone
# already knows, silently turning the demo accounts into exploitable
# "production" credentials.
_PLACEHOLDER_JWT_SECRET = "change-me-dev-only-generate-a-real-secret"

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY is missing from the root .env file. Generate one "
        "with `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
    )
if JWT_SECRET_KEY == _PLACEHOLDER_JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET_KEY is still the placeholder value from .env.example. "
        "Generate a real secret with "
        "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
        "and set it in .env before starting the application."
    )
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest_hex = stored_hash.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(expected.hex(), digest_hex)


def create_access_token(*, subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError (or a subclass) on any invalid/expired token --
    callers should catch that one base class."""
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
