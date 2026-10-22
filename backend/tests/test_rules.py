"""Unit tests for the pure detection rules. No database is involved —
these construct lightweight stand-ins for Transaction rows, since the rule
functions only rely on duck-typed attribute access.
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from detection.rules import (
    HIGH_VALUE_THRESHOLD,
    VELOCITY_MAX_TRANSFERS,
    check_circular_flow,
    check_high_value,
    check_velocity,
)


def _txn(**overrides):
    defaults = dict(
        id=1,
        transaction_ref="TXN-TEST",
        from_account="ACC-A",
        to_account="ACC-B",
        amount=Decimal("100.00"),
        currency="INR",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestHighValue:
    def test_at_threshold_is_not_flagged(self):
        txn = _txn(amount=HIGH_VALUE_THRESHOLD)
        assert check_high_value(txn) is None

    def test_above_threshold_is_flagged(self):
        txn = _txn(amount=HIGH_VALUE_THRESHOLD + Decimal("1"))
        result = check_high_value(txn)
        assert result is not None
        assert result.rule_code == "TXN_HIGH_VALUE"
        assert result.severity == "HIGH"
        assert result.evidence["amount"] == str(txn.amount)


class TestVelocity:
    def test_below_limit_is_not_flagged(self):
        txn = _txn(id=VELOCITY_MAX_TRANSFERS - 1)
        recent = [_txn(id=i) for i in range(1, VELOCITY_MAX_TRANSFERS)]
        assert check_velocity(txn, recent) is None

    def test_at_limit_is_flagged(self):
        txn = _txn(id=VELOCITY_MAX_TRANSFERS)
        recent = [
            _txn(id=i, transaction_ref=f"TXN-{i}")
            for i in range(1, VELOCITY_MAX_TRANSFERS + 1)
        ]
        result = check_velocity(txn, recent)
        assert result is not None
        assert result.rule_code == "TXN_VELOCITY"
        assert result.evidence["transfer_count"] == VELOCITY_MAX_TRANSFERS
        assert result.evidence["account"] == txn.from_account


class TestCircularFlow:
    def test_three_hop_cycle_is_flagged(self):
        t1 = _txn(
            id=1,
            transaction_ref="T1",
            from_account="A",
            to_account="B",
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        )
        t2 = _txn(
            id=2,
            transaction_ref="T2",
            from_account="B",
            to_account="C",
            created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        t3 = _txn(
            id=3,
            transaction_ref="T3",
            from_account="C",
            to_account="A",
            created_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        )
        result = check_circular_flow(t3, [t1, t2, t3])
        assert result is not None
        assert result.rule_code == "TXN_CIRCULAR_FLOW"
        assert result.evidence["account_path"] == ["A", "B", "C"]
        assert result.evidence["transaction_refs"] == ["T1", "T2", "T3"]

    def test_two_hop_direct_round_trip_is_not_flagged_by_default(self):
        # A -> B -> A is only 2 hops; the default minimum is 3, since the
        # documented example is a 3-hop cycle (A -> B -> C -> A).
        t1 = _txn(
            id=1,
            transaction_ref="T1",
            from_account="A",
            to_account="B",
            created_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        )
        t2 = _txn(
            id=2,
            transaction_ref="T2",
            from_account="B",
            to_account="A",
            created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        assert check_circular_flow(t2, [t1, t2]) is None

    def test_no_cycle_returns_none(self):
        t1 = _txn(id=1, from_account="A", to_account="B")
        assert check_circular_flow(t1, [t1]) is None

    def test_out_of_order_timestamps_do_not_count(self):
        # B -> C happens BEFORE A -> B chronologically, so it can't be part
        # of a plausible chain of fund movements starting at A -> B.
        t1 = _txn(
            id=1,
            transaction_ref="T1",
            from_account="A",
            to_account="B",
            created_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        )
        t2 = _txn(
            id=2,
            transaction_ref="T2",
            from_account="B",
            to_account="C",
            created_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )
        t3 = _txn(
            id=3,
            transaction_ref="T3",
            from_account="C",
            to_account="A",
            created_at=datetime(2026, 1, 1, 0, 6, tzinfo=timezone.utc),
        )
        assert check_circular_flow(t3, [t1, t2, t3]) is None
