"""Explicit tests for the foreign-key relationships declared in models.py:
which deletes cascade, which ones merely detach (SET NULL), and that the
unique/check constraints actually hold at the database level -- not just
assumed from reading the column definitions.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

import models
from auth.security import hash_password


def _make_transaction(db, ref="TXN-FK-1"):
    txn = models.Transaction(
        transaction_ref=ref,
        from_account="ACC-A",
        to_account="ACC-B",
        amount=Decimal("1000.00"),
        currency="INR",
        status="RECEIVED",
        created_at=datetime.now(timezone.utc),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def _make_alert(db, txn, rule_code="TXN_HIGH_VALUE"):
    alert = models.Alert(
        transaction_id=txn.id,
        rule_code=rule_code,
        severity="HIGH",
        status="OPEN",
        description="test",
        evidence={},
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _make_report(db, alert):
    report = models.InvestigationReport(
        alert_id=alert.id,
        status="PENDING_REVIEW",
        model_provider="ollama",
        model_name="llama3.1:8b",
        prompt_version="v2-strict-citation-rules",
        summary="test",
        findings={},
        evidence_snapshot={},
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


class TestCascadeDeletes:
    def test_deleting_transaction_cascades_to_its_alerts(self, db_session):
        txn = _make_transaction(db_session)
        alert = _make_alert(db_session, txn)
        alert_id = alert.id

        db_session.delete(txn)
        db_session.commit()

        assert db_session.get(models.Alert, alert_id) is None

    def test_deleting_alert_cascades_to_its_reports(self, db_session):
        txn = _make_transaction(db_session)
        alert = _make_alert(db_session, txn)
        report = _make_report(db_session, alert)
        report_id = report.id

        db_session.delete(alert)
        db_session.commit()

        assert db_session.get(models.InvestigationReport, report_id) is None

    def test_deleting_transaction_cascades_through_alert_to_report(self, db_session):
        """Two hops: Transaction -> Alert -> InvestigationReport, both
        declared CASCADE, so deleting the transaction must remove both."""
        txn = _make_transaction(db_session)
        alert = _make_alert(db_session, txn)
        report = _make_report(db_session, alert)
        alert_id, report_id = alert.id, report.id

        db_session.delete(txn)
        db_session.commit()

        assert db_session.get(models.Alert, alert_id) is None
        assert db_session.get(models.InvestigationReport, report_id) is None


class TestSetNullOnDelete:
    def test_deleting_reviewing_user_detaches_report_without_deleting_it(self, db_session):
        txn = _make_transaction(db_session)
        alert = _make_alert(db_session, txn)
        report = _make_report(db_session, alert)

        user = models.User(
            email="reviewer@sentinelbank.ai",
            full_name="Test Reviewer",
            hashed_password=hash_password("Whatever123!"),
            role="ANALYST",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        report.status = "APPROVED"
        report.reviewed_by = user.full_name
        report.reviewed_by_user_id = user.id
        report.reviewed_at = datetime.now(timezone.utc)
        db_session.commit()

        db_session.delete(user)
        db_session.commit()
        # The DB applies ON DELETE SET NULL directly -- SQLAlchemy's
        # identity map doesn't know that happened (expire_on_commit=False),
        # so without this the stale in-memory object would still show the
        # old reviewed_by_user_id.
        db_session.expire_all()

        refreshed = db_session.get(models.InvestigationReport, report.id)
        assert refreshed is not None, "deleting the user must not delete the report"
        assert refreshed.reviewed_by_user_id is None
        # the historical display name is preserved even once the account is gone
        assert refreshed.reviewed_by == "Test Reviewer"
        assert refreshed.status == "APPROVED"

    def test_deleting_case_detaches_alert_without_deleting_it(self, db_session):
        txn = _make_transaction(db_session)
        alert = _make_alert(db_session, txn)

        case = models.InvestigationCase(
            case_ref="CASE-FK-1",
            status="OPEN",
        )
        db_session.add(case)
        db_session.commit()
        db_session.refresh(case)

        alert.case_id = case.id
        db_session.commit()

        db_session.delete(case)
        db_session.commit()
        db_session.expire_all()

        refreshed = db_session.get(models.Alert, alert.id)
        assert refreshed is not None
        assert refreshed.case_id is None


class TestConstraints:
    def test_duplicate_alert_rule_pair_is_rejected(self, db_session):
        txn = _make_transaction(db_session)
        _make_alert(db_session, txn, rule_code="TXN_HIGH_VALUE")

        db_session.add(
            models.Alert(
                transaction_id=txn.id,
                rule_code="TXN_HIGH_VALUE",
                severity="HIGH",
                status="OPEN",
                description="duplicate",
                evidence={},
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_invalid_user_role_is_rejected(self, db_session):
        db_session.add(
            models.User(
                email="bad-role@sentinelbank.ai",
                full_name="Bad Role",
                hashed_password=hash_password("Whatever123!"),
                role="SUPERUSER",  # not in the allowed CHECK set
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # session must still be usable after the rollback
        assert db_session.query(models.User).count() == 0

    def test_duplicate_user_email_is_rejected(self, db_session):
        db_session.add(
            models.User(
                email="dup@sentinelbank.ai",
                full_name="First",
                hashed_password=hash_password("Whatever123!"),
                role="ANALYST",
            )
        )
        db_session.commit()

        db_session.add(
            models.User(
                email="dup@sentinelbank.ai",
                full_name="Second",
                hashed_password=hash_password("Whatever123!"),
                role="ANALYST",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
