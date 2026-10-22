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
from sqlalchemy.orm import Session

import models
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
    summary: str
    findings: dict[str, Any]
    evidence_snapshot: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None
    reviewed_by: str | None


class ReviewRequest(BaseModel):
    status: str = Field(description="One of APPROVED, DISMISSED, ESCALATED")
    reviewed_by: str = Field(min_length=1, max_length=128)


@router.post(
    "/alerts/{alert_id}/investigate",
    response_model=ReportResponse,
    status_code=201,
)
def investigate_alert(alert_id: int, db: DbSession):
    """Run the AI investigation workflow for an alert. Safe to call more
    than once — each run is recorded as a new report rather than
    overwriting a previous one."""
    try:
        report = run_investigation(db, alert_id)
    except InvestigationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return report


@router.get("/alerts/{alert_id}/reports", response_model=list[ReportResponse])
def list_reports_for_alert(alert_id: int, db: DbSession):
    result = db.execute(
        select(models.InvestigationReport)
        .where(models.InvestigationReport.alert_id == alert_id)
        .order_by(models.InvestigationReport.id)
    )
    return result.scalars().all()


@router.post("/reports/{report_id}/review", response_model=ReportResponse)
def review_report(report_id: int, payload: ReviewRequest, db: DbSession):
    """The controlled human-approval step: a report sits at PENDING_REVIEW
    (or FAILED) until an analyst explicitly approves, dismisses, or
    escalates it. Nothing downstream acts on a report before this happens.
    """
    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {sorted(REVIEW_STATUSES)}",
        )

    report = db.get(models.InvestigationReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    report.status = payload.status
    report.reviewed_by = payload.reviewed_by
    report.reviewed_at = datetime.now(timezone.utc)
    db.add(
        models.AuditLog(
            entity_type="investigation_report",
            entity_id=report.id,
            action=f"REPORT_{payload.status}",
            actor=payload.reviewed_by,
            details=f"Report #{report.id} marked {payload.status} by {payload.reviewed_by}",
        )
    )
    db.commit()
    db.refresh(report)
    return report
