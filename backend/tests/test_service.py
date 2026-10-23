"""Tests for detection.service: rule orchestration, duplicate-alert
prevention, and database rollback behavior. These use the in-memory SQLite
fixture from conftest.py rather than the real Postgres container.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

import models
from detection import service
from detection.rules import VELOCITY_MAX_TRANSFERS


def _make_transaction(
    db,
    *,
    transaction_ref,
    amount,
    from_account="ACC-A",
    to_account="ACC-B",
    created_at=None,
    currency="INR",
):
    txn = models.Transaction(
        transaction_ref=transaction_ref,
        from_account=from_account,
        to_account=to_account,
        amount=amount,
        currency=currency,
        status="RECEIVED",
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


class TestRunDetection:
    def test_high_value_creates_alert(self, db_session):
        txn = _make_transaction(
            db_session, transaction_ref="HV1", amount=Decimal("999999.00")
        )
        alerts = service.run_detection(db_session, txn)
        assert {a.rule_code for a in alerts} == {"TXN_HIGH_VALUE"}

    def test_low_value_creates_no_alert(self, db_session):
        txn = _make_transaction(
            db_session, transaction_ref="LOW1", amount=Decimal("10.00")
        )
        assert service.run_detection(db_session, txn) == []

    def test_velocity_creates_alert_at_threshold(self, db_session):
        base_time = datetime.now(timezone.utc)
        last = None
        for i in range(VELOCITY_MAX_TRANSFERS):
            last = _make_transaction(
                db_session,
                transaction_ref=f"VEL{i}",
                amount=Decimal("10.00"),
                from_account="ACC-VEL",
                to_account=f"ACC-DEST-{i}",
                created_at=base_time + timedelta(seconds=i),
            )
        alerts = service.run_detection(db_session, last)
        assert any(a.rule_code == "TXN_VELOCITY" for a in alerts)

    def test_circular_flow_creates_alert(self, db_session):
        base_time = datetime.now(timezone.utc)
        _make_transaction(
            db_session,
            transaction_ref="C1",
            amount=Decimal("10"),
            from_account="A",
            to_account="B",
            created_at=base_time,
        )
        _make_transaction(
            db_session,
            transaction_ref="C2",
            amount=Decimal("10"),
            from_account="B",
            to_account="C",
            created_at=base_time + timedelta(seconds=1),
        )
        closing = _make_transaction(
            db_session,
            transaction_ref="C3",
            amount=Decimal("10"),
            from_account="C",
            to_account="A",
            created_at=base_time + timedelta(seconds=2),
        )
        alerts = service.run_detection(db_session, closing)
        assert any(a.rule_code == "TXN_CIRCULAR_FLOW" for a in alerts)


class TestDuplicatePrevention:
    def test_rerunning_detection_does_not_duplicate_alerts(self, db_session):
        txn = _make_transaction(
            db_session, transaction_ref="HV2", amount=Decimal("999999.00")
        )
        first_run = service.run_detection(db_session, txn)
        assert len(first_run) == 1

        second_run = service.run_detection(db_session, txn)
        assert second_run == []

        stored = (
            db_session.query(models.Alert)
            .filter_by(transaction_id=txn.id, rule_code="TXN_HIGH_VALUE")
            .all()
        )
        assert len(stored) == 1

    def test_run_detection_for_all_is_idempotent(self, db_session):
        _make_transaction(
            db_session, transaction_ref="HV3", amount=Decimal("500000.00")
        )
        first_run = service.run_detection_for_all(db_session)
        assert len(first_run) == 1

        second_run = service.run_detection_for_all(db_session)
        assert second_run == []
        assert db_session.query(models.Alert).count() == 1

    def test_unique_constraint_rejects_duplicate_alert_rows_directly(self, db_session):
        # Defense in depth: even bypassing service's own existence check,
        # the database itself must refuse a duplicate (transaction_id,
        # rule_code) pair.
        txn = _make_transaction(
            db_session, transaction_ref="DUP1", amount=Decimal("500000.00")
        )
        service.run_detection(db_session, txn)

        duplicate = models.Alert(
            transaction_id=txn.id,
            rule_code="TXN_HIGH_VALUE",
            severity="HIGH",
            status="OPEN",
            description="duplicate",
            evidence={},
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestRollbackBehavior:
    def test_duplicate_transaction_ref_rolls_back_cleanly(self, db_session):
        _make_transaction(
            db_session, transaction_ref="ROLLBACK1", amount=Decimal("1.00")
        )

        conflicting = models.Transaction(
            transaction_ref="ROLLBACK1",
            from_account="ACC-C",
            to_account="ACC-D",
            amount=Decimal("1.00"),
            currency="INR",
            status="RECEIVED",
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(conflicting)
        with pytest.raises(IntegrityError):
            db_session.commit()

        db_session.rollback()

        count = (
            db_session.query(models.Transaction)
            .filter_by(transaction_ref="ROLLBACK1")
            .count()
        )
        assert count == 1

        # The session must still be usable after rollback.
        _make_transaction(
            db_session, transaction_ref="ROLLBACK2", amount=Decimal("1.00")
        )
        assert db_session.query(models.Transaction).count() == 2

    def test_failed_commit_does_not_persist_partial_alert_state(self, db_session):
        txn = _make_transaction(
            db_session, transaction_ref="ROLLBACK3", amount=Decimal("600000.00")
        )
        service.run_detection(db_session, txn)
        assert db_session.query(models.Alert).count() == 1

        bad_alert = models.Alert(
            transaction_id=txn.id,
            rule_code="TXN_HIGH_VALUE",  # duplicate -> violates unique constraint
            severity="HIGH",
            status="OPEN",
            description="should not persist",
            evidence={},
        )
        db_session.add(bad_alert)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # The original alert from run_detection is untouched, and the
        # failed insert left no trace.
        alerts = db_session.query(models.Alert).all()
        assert len(alerts) == 1
        assert alerts[0].description != "should not persist"
