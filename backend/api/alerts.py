"""Endpoints for running fraud detection and reviewing the alerts it
produces. Route handlers stay thin — all detection logic lives in
`detection.rules` and `detection.service`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from auth.dependencies import CurrentUser, require_role
from db import get_db
from detection import service

router = APIRouter(prefix="/api/v1", tags=["alerts"])

DbSession = Annotated[Session, Depends(get_db)]


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: int
    case_id: int | None
    rule_code: str
    severity: str
    status: str
    description: str
    evidence: dict[str, Any]
    created_at: datetime


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(db: DbSession, _user: CurrentUser):
    result = db.execute(select(models.Alert).order_by(models.Alert.id))
    return result.scalars().all()


@router.post("/detection/run", response_model=list[AlertResponse])
def run_detection(db: DbSession, _user: Annotated[models.User, Depends(require_role("ADMIN"))]):
    """Rerun detection rules across every stored transaction. Existing
    alerts for a (transaction, rule) pair are never duplicated, so this is
    safe to call repeatedly. ADMIN-only: a fleet-wide rescan is a bulk
    operation, not a routine analyst action."""
    return service.run_detection_for_all(db)
