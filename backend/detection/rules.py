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

    Detection runs as each transaction is created, so a cycle only becomes
    visible on its *closing* transaction — the one whose `to_account` is the
    same account that started the chain. So we search backward in time from
    `transaction.to_account` (the candidate origin) for a chronological path
    of earlier transfers that arrives at `transaction.from_account`; if one
    exists, `transaction` itself closes the loop.

    `recent_transactions` must contain every transaction within
    CIRCULAR_LOOKBACK_SECONDS before (and including) `transaction`, used to
    build the account transfer graph.
    """
    origin = transaction.to_account
    target = transaction.from_account

    graph: dict[str, list["Transaction"]] = {}
    for t in recent_transactions:
        if t.id == transaction.id:
            continue
        graph.setdefault(t.from_account, []).append(t)

    # The closing transaction itself is one hop, so the earlier path needs
    # at least (CIRCULAR_MIN_HOPS - 1) hops to meet the overall minimum.
    min_path_hops = max(CIRCULAR_MIN_HOPS - 1, 1)
    max_path_hops = max(CIRCULAR_MAX_HOPS - 1, min_path_hops)

    path = _find_chronological_path(
        start=origin,
        target=target,
        graph=graph,
        not_after=transaction.created_at,
        min_hops=min_path_hops,
        max_hops=max_path_hops,
    )
    if path is None:
        return None

    full_path = path + [transaction]
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
            "transaction_refs": [t.transaction_ref for t in full_path],
            "hops": len(full_path),
        },
    )


def _find_chronological_path(
    start: str,
    target: str,
    graph: dict[str, list["Transaction"]],
    not_after,
    min_hops: int,
    max_hops: int,
) -> list["Transaction"] | None:
    """Depth-first search for a chronological path of transfers from `start`
    to `target`, each hop's `created_at` at or after the previous hop's (and
    never later than `not_after`), with between `min_hops` and `max_hops`
    transactions. Returns the path, or None if no such path exists.
    """

    def dfs(
        current_account: str,
        last_time,
        path: list["Transaction"],
        visited_accounts: set[str],
    ) -> list["Transaction"] | None:
        if len(path) >= min_hops and current_account == target:
            return path
        if len(path) >= max_hops:
            return None

        for nxt in graph.get(current_account, []):
            if last_time is not None and nxt.created_at < last_time:
                continue
            if nxt.created_at > not_after:
                continue
            if nxt.to_account != target and nxt.to_account in visited_accounts:
                continue

            visited_accounts.add(nxt.to_account)
            result = dfs(nxt.to_account, nxt.created_at, path + [nxt], visited_accounts)
            if result is not None:
                return result
            visited_accounts.discard(nxt.to_account)

        return None

    return dfs(start, None, [], {start})
