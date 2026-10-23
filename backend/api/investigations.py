"""Endpoints for triggering AI investigations and recording the human
analyst's review decision. Route handlers stay thin — the workflow itself
lives in `investigation.graph`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

import models
from auth.dependencies import CurrentUser
from db import get_db
from investigation.graph import InvestigationError, run_investigation

router = APIRouter(prefix="/api/v1", tags=["investigations"])

DbSession = Annotated[Session, Depends(get_db)]

REVIEW_STATUSES = {"APPROVED", "DISMISSED", "ESCALATED"}


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_id: int
    case_id: int | None
    status: str
    model_provider: str
    model_name: str
    prompt_version: str
    summary: str
    findings: dict[str, Any]
    evidence_snapshot: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None
    reviewed_by_user_id: int | None


class ReviewRequest(BaseModel):
    status: str = Field(description="One of APPROVED, DISMISSED, ESCALATED")


@router.post(
    "/alerts/{alert_id}/investigate",
    response_model=ReportResponse,
    status_code=201,
)
def investigate_alert(alert_id: int, db: DbSession, _user: CurrentUser):
    """Run the AI investigation workflow for an alert. Safe to call more
    than once — each run is recorded as a new report rather than
    overwriting a previous one."""
    try:
        report = run_investigation(db, alert_id)
    except InvestigationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return report


@router.get("/alerts/{alert_id}/reports", response_model=list[ReportResponse])
def list_reports_for_alert(alert_id: int, db: DbSession, _user: CurrentUser):
    result = db.execute(
        select(models.InvestigationReport)
        .where(models.InvestigationReport.alert_id == alert_id)
        .order_by(models.InvestigationReport.id)
    )
    return result.scalars().all()


@router.post("/reports/{report_id}/review", response_model=ReportResponse)
def review_report(
    report_id: int, payload: ReviewRequest, db: DbSession, user: CurrentUser
):
    """The controlled human-approval step: a report sits at PENDING_REVIEW
    (or FAILED) until an analyst explicitly approves, dismisses, or
    escalates it. Nothing downstream acts on a report before this happens.

    The reviewer identity comes from the authenticated session, never a
    client-supplied name -- a review is only as trustworthy as the identity
    behind it. Idempotent/duplicate review attempts (including two
    concurrent requests racing each other) are rejected with 409: the
    update only succeeds if `reviewed_by_user_id IS NULL`, checked and set
    atomically in a single UPDATE so a second request can't sneak in
    between a check and a write.
    """
    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {sorted(REVIEW_STATUSES)}",
        )

    now = datetime.now(timezone.utc)
    result = db.execute(
        sa_update(models.InvestigationReport)
        .where(models.InvestigationReport.id == report_id)
        .where(models.InvestigationReport.reviewed_by_user_id.is_(None))
        .values(
            status=payload.status,
            reviewed_by=user.full_name,
            reviewed_by_user_id=user.id,
            reviewed_at=now,
        )
    )

    if result.rowcount == 0:
        db.rollback()
        existing = db.get(models.InvestigationReport, report_id)
        if existing is None:
            raise HTTPException(
                status_code=404, detail=f"Report {report_id} not found"
            )
        raise HTTPException(
            status_code=409,
            detail=f"Report {report_id} was already reviewed by "
            f"{existing.reviewed_by} on {existing.reviewed_at}.",
        )

    db.add(
        models.AuditLog(
            entity_type="investigation_report",
            entity_id=report_id,
            action=f"REPORT_{payload.status}",
            actor=user.email,
            details=f"Report #{report_id} marked {payload.status} by {user.full_name} ({user.role}).",
        )
    )
    db.commit()

    report = db.get(models.InvestigationReport, report_id)
    db.refresh(report)
    return report
