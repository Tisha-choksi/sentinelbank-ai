"""Seeds the two demo accounts this prototype ships with, idempotently.
There is no self-registration (see api/auth.py), so something has to create
the first users -- this stands in for the internal provisioning process a
real bank would use. Safe to call on every startup: it only inserts users
that don't already exist by email.

Demo credentials (local prototype only -- never reuse these anywhere real):
  admin@sentinelbank.ai   / Admin123!   (ADMIN)
  analyst@sentinelbank.ai / Analyst123! (ANALYST)
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from auth.security import hash_password

DEMO_USERS = [
    {
        "email": "admin@sentinelbank.ai",
        "full_name": "Priya Admin",
        "password": "Admin123!",
        "role": "ADMIN",
    },
    {
        "email": "analyst@sentinelbank.ai",
        "full_name": "Jordan Analyst",
        "password": "Analyst123!",
        "role": "ANALYST",
    },
]


def seed_demo_users(db: Session) -> None:
    for spec in DEMO_USERS:
        existing = db.execute(
            select(models.User).where(models.User.email == spec["email"])
        ).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(
            models.User(
                email=spec["email"],
                full_name=spec["full_name"],
                hashed_password=hash_password(spec["password"]),
                role=spec["role"],
            )
        )
    db.commit()
