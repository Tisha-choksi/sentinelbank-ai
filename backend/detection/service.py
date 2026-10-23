"""Runs detection rules against transactions and persists the resulting
alerts. This is the only part of the detection package that touches the
database — `detection.rules` stays pure so the rule logic can be tested
without a live session.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from detection.rules import (
    CIRCULAR_LOOKBACK_SECONDS,
    VELOCITY_WINDOW_SECONDS,
    check_circular_flow,
    check_high_value,
    check_velocity,
)


def run_detection(db: Session, transaction: models.Transaction) -> list[models.Alert]:
    """Evaluate every rule against `transaction` and persist any new alerts.

    Rerunning this for the same transaction is safe: alerts are keyed by
    (transaction_id, rule_code), enforced both here (an explicit check) and
    at the database level (a unique constraint) so concurrent reruns can't
    slip through.
    """
    candidates = []

    high_value = check_high_value(transaction)
    if high_value is not None:
        candidates.append(high_value)

    velocity_window_start = transaction.created_at - timedelta(
        seconds=VELOCITY_WINDOW_SECONDS
    )
    recent_same_account = (
        db.execute(
            select(models.Transaction)
            .where(models.Transaction.from_account == transaction.from_account)
            .where(models.Transaction.created_at >= velocity_window_start)
            .where(models.Transaction.created_at <= transaction.created_at)
        )
        .scalars()
        .all()
    )
    velocity = check_velocity(transaction, recent_same_account)
    if velocity is not None:
        candidates.append(velocity)

    circular_window_start = transaction.created_at - timedelta(
        seconds=CIRCULAR_LOOKBACK_SECONDS
    )
    recent_all = (
        db.execute(
            select(models.Transaction)
            .where(models.Transaction.created_at >= circular_window_start)
            .where(models.Transaction.created_at <= transaction.created_at)
        )
        .scalars()
        .all()
    )
    circular = check_circular_flow(transaction, recent_all)
    if circular is not None:
        candidates.append(circular)

    if not candidates:
        return []

    created: list[models.Alert] = []
    for candidate in candidates:
        already_exists = db.execute(
            select(models.Alert.id)
            .where(models.Alert.transaction_id == transaction.id)
            .where(models.Alert.rule_code == candidate.rule_code)
        ).scalar_one_or_none()
        if already_exists is not None:
            continue

        alert = models.Alert(
            transaction_id=transaction.id,
            rule_code=candidate.rule_code,
            severity=candidate.severity,
            status="OPEN",
            description=candidate.description,
            evidence=candidate.evidence,
        )
        db.add(alert)
        created.append(alert)

    if created:
        db.commit()
        for alert in created:
            db.refresh(alert)

    return created


def run_detection_for_all(db: Session) -> list[models.Alert]:
    """Rerun detection across every stored transaction. Useful for
    backfilling alerts after a rule change, and for verifying that reruns
    don't create duplicates.
    """
    transactions = (
        db.execute(select(models.Transaction).order_by(models.Transaction.id))
        .scalars()
        .all()
    )
    created: list[models.Alert] = []
    for transaction in transactions:
        created.extend(run_detection(db, transaction))
    return created
