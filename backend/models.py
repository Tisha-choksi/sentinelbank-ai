from datetime import datetime, timezone
from decimal import Decimal

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    transaction_ref: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    from_account: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    to_account: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="INR",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="RECEIVED",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",
    )


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    account_number: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    owner_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="SAVINGS",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ACTIVE",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "account_type IN ('SAVINGS', 'CURRENT')",
            name="ck_accounts_account_type",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'FROZEN', 'CLOSED')",
            name="ck_accounts_status",
        ),
    )


class InvestigationCase(Base):
    __tablename__ = "investigation_cases"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    case_ref: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="OPEN",
    )
    assigned_to: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    summary: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    alerts: Mapped[list["Alert"]] = relationship(back_populates="case")

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'CLOSED')",
            name="ck_investigation_cases_status",
        ),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="OPEN",
    )
    description: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    transaction: Mapped["Transaction"] = relationship(back_populates="alerts")
    case: Mapped["InvestigationCase | None"] = relationship(back_populates="alerts")
    reports: Mapped[list["InvestigationReport"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_alerts_severity",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'RESOLVED', 'DISMISSED')",
            name="ck_alerts_status",
        ),
        UniqueConstraint(
            "transaction_id",
            "rule_code",
            name="uq_alerts_transaction_rule",
        ),
    )


class InvestigationReport(Base):
    """A single AI-investigation run over an alert. Each rerun creates a new
    row rather than overwriting a previous one, so report history, the
    model/version used, and the exact evidence it saw are all reproducible.
    """

    __tablename__ = "investigation_reports"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("investigation_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING_REVIEW",
    )
    model_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unspecified",
    )
    summary: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
    )
    findings: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    alert: Mapped["Alert"] = relationship(back_populates="reports")
    reviewer: Mapped["User | None"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_REVIEW', 'APPROVED', 'DISMISSED', 'ESCALATED', 'FAILED')",
            name="ck_investigation_reports_status",
        ),
    )


class User(Base):
    """Analysts and administrators. There is no self-registration --
    accounts are provisioned (seeded, for this prototype) internally, the
    way real banking staff accounts are, not signed up by anonymous
    visitors.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ANALYST",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('ANALYST', 'ADMIN')",
            name="ck_users_role",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    entity_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
    )
    details: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
