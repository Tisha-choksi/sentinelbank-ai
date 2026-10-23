"""Typed contracts for the AI investigation workflow.

`EvidenceBundle` is the exact, closed set of facts the model is allowed to
reason about — built from verified database records, never raw ORM objects
passed straight into a prompt. `InvestigationFindings` is the exact shape
the model must answer in, including which transaction refs and account
numbers it is citing.

Requiring explicit citations (rather than scanning free text afterward) is
what lets the LLM node deterministically check that every factual claim is
grounded in retrieved evidence, instead of trusting the model's prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class TransactionEvidence:
    transaction_ref: str
    from_account: str
    to_account: str
    amount: str
    currency: str
    status: str
    created_at: str


@dataclass
class AccountEvidence:
    account_number: str
    owner_name: str
    account_type: str
    status: str


@dataclass
class EvidenceBundle:
    alert_id: int
    rule_code: str
    severity: str
    alert_description: str
    alert_evidence: dict[str, Any]
    primary_transaction: TransactionEvidence
    related_transactions: list[TransactionEvidence] = field(default_factory=list)
    known_accounts: list[AccountEvidence] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    def known_transaction_refs(self) -> set[str]:
        refs = {self.primary_transaction.transaction_ref}
        refs.update(t.transaction_ref for t in self.related_transactions)
        return refs

    def known_account_numbers(self) -> set[str]:
        accounts = {
            self.primary_transaction.from_account,
            self.primary_transaction.to_account,
        }
        for t in self.related_transactions:
            accounts.add(t.from_account)
            accounts.add(t.to_account)
        return accounts


class InvestigationFindings(BaseModel):
    """The structured report the model must produce. `cited_transaction_refs`
    and `cited_accounts` are checked against the EvidenceBundle after
    generation — anything cited that wasn't actually retrieved is treated as
    an ungrounded claim and rejected.
    """

    summary: str = Field(min_length=1, max_length=2048)
    confirmed_facts: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    cited_transaction_refs: list[str] = Field(default_factory=list)
    cited_accounts: list[str] = Field(default_factory=list)
