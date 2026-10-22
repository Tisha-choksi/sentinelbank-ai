"""Fraud detection rules.

These are initial demonstration rules, not universal banking fraud
criteria. Thresholds are tunable via environment variables so they can be
adjusted against synthetic data without changing code.

Each rule is a pure function: given a transaction and whatever context it
needs (recent transactions for the same account, or a wider window for graph
analysis), it returns an `AlertCandidate` or `None`. Rules do not touch the
database themselves — see `detection.engine` for persistence and
duplicate-prevention.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import Transaction


def _env_decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


# --- Configurable thresholds ---

HIGH_VALUE_THRESHOLD = _env_decimal("FRAUD_HIGH_VALUE_THRESHOLD", "200000")

VELOCITY_WINDOW_SECONDS = _env_int("FRAUD_VELOCITY_WINDOW_SECONDS", 300)
VELOCITY_MAX_TRANSFERS = _env_int("FRAUD_VELOCITY_MAX_TRANSFERS", 5)

CIRCULAR_LOOKBACK_SECONDS = _env_int("FRAUD_CIRCULAR_LOOKBACK_SECONDS", 86400)
CIRCULAR_MIN_HOPS = _env_int("FRAUD_CIRCULAR_MIN_HOPS", 3)
CIRCULAR_MAX_HOPS = _env_int("FRAUD_CIRCULAR_MAX_HOPS", 5)


@dataclass
class AlertCandidate:
    rule_code: str
    severity: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


def check_high_value(transaction: "Transaction") -> AlertCandidate | None:
    """TXN_HIGH_VALUE: transaction exceeds a configurable threshold."""
    if transaction.amount <= HIGH_VALUE_THRESHOLD:
        return None
    return AlertCandidate(
        rule_code="TXN_HIGH_VALUE",
        severity="HIGH",
        description=(
            f"Transaction {transaction.transaction_ref} of "
            f"{transaction.amount} {transaction.currency} exceeds the "
            f"high-value threshold of {HIGH_VALUE_THRESHOLD} {transaction.currency}."
        ),
        evidence={
            "amount": str(transaction.amount),
            "currency": transaction.currency,
            "threshold": str(HIGH_VALUE_THRESHOLD),
        },
    )


def check_velocity(
    transaction: "Transaction",
    recent_same_account: list["Transaction"],
) -> AlertCandidate | None:
    """TXN_VELOCITY: an account sends several transfers within a short window.

    `recent_same_account` must contain the transactions sent from
    `transaction.from_account` within VELOCITY_WINDOW_SECONDS before (and
    including) `transaction` itself.
    """
    count = len(recent_same_account)
    if count < VELOCITY_MAX_TRANSFERS:
        return None
    refs = sorted(t.transaction_ref for t in recent_same_account)
    return AlertCandidate(
        rule_code="TXN_VELOCITY",
        severity="MEDIUM",
        description=(
            f"Account {transaction.from_account} sent {count} transfers "
            f"within {VELOCITY_WINDOW_SECONDS} seconds, at or above the "
            f"limit of {VELOCITY_MAX_TRANSFERS}."
        ),
        evidence={
            "account": transaction.from_account,
            "window_seconds": VELOCITY_WINDOW_SECONDS,
            "transfer_count": count,
            "transaction_refs": refs,
        },
    )


def check_circular_flow(
    transaction: "Transaction",
    recent_transactions: list["Transaction"],
) -> AlertCandidate | None:
    """TXN_CIRCULAR_FLOW: funds move through a sequence of accounts and
    return to the starting account (e.g. A -> B -> C -> A).

    `recent_transactions` must contain every transaction within
    CIRCULAR_LOOKBACK_SECONDS before (and including) `transaction`, used to
    build the account transfer graph.
    """
    origin = transaction.from_account

    graph: dict[str, list["Transaction"]] = {}
    for t in recent_transactions:
        graph.setdefault(t.from_account, []).append(t)

    path = _find_cycle_back_to_origin(origin, transaction, graph)
    if path is None:
        return None

    account_path = [origin] + [t.to_account for t in path]
    return AlertCandidate(
        rule_code="TXN_CIRCULAR_FLOW",
        severity="CRITICAL",
        description=(
            "Funds routed through "
            f"{' -> '.join(account_path)} and returned to the originating "
            f"account {origin}."
        ),
        evidence={
            "account_path": account_path,
            "transaction_refs": [t.transaction_ref for t in path],
            "hops": len(path),
        },
    )


def _find_cycle_back_to_origin(
    origin: str,
    start: "Transaction",
    graph: dict[str, list["Transaction"]],
) -> list["Transaction"] | None:
    """Depth-first search for a chronological path of transfers starting at
    `start` that eventually routes back to `origin`, with at least
    CIRCULAR_MIN_HOPS transactions and at most CIRCULAR_MAX_HOPS. Each hop's
    `created_at` must be at or after the previous hop's, so the path
    represents a plausible sequence of fund movements rather than an
    arbitrary graph cycle.
    """

    def dfs(
        current: "Transaction",
        path: list["Transaction"],
        visited_accounts: set[str],
    ) -> list["Transaction"] | None:
        if current.to_account == origin:
            if len(path) >= CIRCULAR_MIN_HOPS:
                return path
            return None

        if len(path) >= CIRCULAR_MAX_HOPS:
            return None

        for nxt in graph.get(current.to_account, []):
            if nxt.id == current.id:
                continue
            if nxt.created_at < current.created_at:
                continue
            if nxt.to_account != origin and nxt.to_account in visited_accounts:
                continue

            visited_accounts.add(nxt.to_account)
            result = dfs(nxt, path + [nxt], visited_accounts)
            if result is not None:
                return result
            visited_accounts.discard(nxt.to_account)

        return None

    return dfs(start, [start], {origin, start.to_account})
