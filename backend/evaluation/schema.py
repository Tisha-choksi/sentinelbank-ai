"""Typed schema for the investigation-evaluation dataset.

Each ScenarioSpec is self-contained: enough to rebuild the exact database
state it was derived from (transactions + accounts), plus the ground truth
a Phase 2 harness grades a real (or simulated) investigation against.

Critically, the alert fields (`rule_code`, `severity`, `alert_evidence`,
etc.) are never hand-authored — the generator runs the real
`detection.service.run_detection` against the fixtures and records whatever
it actually produced. That keeps the dataset's ground truth from drifting
out of sync with the real rule logic.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "high_value_transfer",
    "high_velocity",
    "circular_flow",
    "missing_account_records",
    "legitimate_unusual_activity",
    "conflicting_incomplete_evidence",
    "invalid_citation",
    "model_failure",
]

CATEGORIES: tuple[Category, ...] = (
    "high_value_transfer",
    "high_velocity",
    "circular_flow",
    "missing_account_records",
    "legitimate_unusual_activity",
    "conflicting_incomplete_evidence",
    "invalid_citation",
    "model_failure",
)


class TransactionFixture(BaseModel):
    transaction_ref: str
    from_account: str
    to_account: str
    amount: str
    currency: str = "INR"
    created_at: str  # ISO 8601, so chronological ordering/windows replay exactly


class AccountFixture(BaseModel):
    account_number: str
    owner_name: str
    account_type: str = "SAVINGS"
    status: str = "ACTIVE"


class ScenarioSpec(BaseModel):
    id: str
    category: Category
    description: str

    # --- database state to recreate before running the investigation ---
    transactions: list[TransactionFixture]
    accounts: list[AccountFixture] = Field(default_factory=list)

    # Which transaction the alert attaches to, and the alert exactly as
    # produced by the real detection engine against the fixtures above.
    primary_transaction_ref: str
    rule_code: str
    severity: str
    alert_description: str
    alert_evidence: dict[str, Any]

    # Injected model behavior. Only set for the two system-resilience
    # categories (invalid_citation, model_failure) -- for every other
    # category this is None, meaning "run a normally-behaving model and
    # grade its real output against the ground truth below."
    simulated_llm_response: dict[str, Any] | None = None
    simulated_llm_failure: Literal["timeout", "malformed_json", "wrong_shape"] | None = None

    # --- grading ground truth ---
    expected_status: Literal["PENDING_REVIEW", "FAILED"]
    expected_facts: list[str] = Field(default_factory=list)
    allowed_transaction_refs: list[str] = Field(default_factory=list)
    allowed_accounts: list[str] = Field(default_factory=list)
    expected_uncertainty_keywords: list[str] = Field(default_factory=list)
    forbidden_claim_keywords: list[str] = Field(default_factory=list)
    notes: str = ""
