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

# Categories 1-6: grade real (or simulated) model *quality* against live
# evidence. These are the only ones that call a real model and the only
# ones durations/facts/uncertainty are scored against.
QUALITY_CATEGORIES: frozenset[Category] = frozenset(
    {
        "high_value_transfer",
        "high_velocity",
        "circular_flow",
        "missing_account_records",
        "legitimate_unusual_activity",
        "conflicting_incomplete_evidence",
    }
)

# Categories 7-8: deliberately adversarial, fully deterministic (canned
# response/failure, no real model call). expected_status is always FAILED
# -- a 100% "failure rate" here is the system working correctly, not a
# defect, which is why these are scored as a rejection rate, never folded
# into the same "failure rate" as the quality categories.
RESILIENCE_CATEGORIES: frozenset[Category] = frozenset(
    {"invalid_citation", "model_failure"}
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
    # v2 scorer input: one synonym set per expected uncertainty concept
    # (e.g. ["account registry", "unregistered", "could not be verified"]).
    # A concept counts as surfaced if ANY synonym appears, checked across
    # uncertainties + recommended_checks + summary together rather than one
    # literal phrase in one field. See evaluation/metrics.py::score_result_v2.
    expected_uncertainty_concepts: list[list[str]] = Field(default_factory=list)
    forbidden_claim_keywords: list[str] = Field(default_factory=list)
    notes: str = ""
