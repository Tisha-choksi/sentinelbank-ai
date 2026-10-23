"""Structural and self-consistency checks for the synthetic evaluation
dataset. These re-verify the dataset independently of `evaluation.generate`
-- replaying each scenario's fixtures through the real detection engine
again here, rather than trusting whatever the generator claims, catches
drift if the detection rules change without the dataset being regenerated.
"""

from datetime import datetime
from decimal import Decimal

import pytest

import models
from detection import service
from evaluation.generate import FAILURE_MODES, build_dataset
from evaluation.schema import CATEGORIES

MIN_TOTAL = 300
MAX_TOTAL = 400


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


def test_dataset_size_is_in_range(dataset):
    assert MIN_TOTAL <= len(dataset) <= MAX_TOTAL


def test_every_category_is_represented(dataset):
    seen = {s.category for s in dataset}
    assert seen == set(CATEGORIES)


def test_category_counts_are_reasonably_balanced(dataset):
    counts = {}
    for s in dataset:
        counts[s.category] = counts.get(s.category, 0) + 1
    for category, count in counts.items():
        assert count >= 30, f"{category} has only {count} scenarios"


def test_scenario_ids_are_unique(dataset):
    ids = [s.id for s in dataset]
    assert len(ids) == len(set(ids))


def test_every_scenario_replays_to_the_expected_alert(db_session, dataset):
    """The critical check: rebuild each scenario's DB state independently
    and confirm the real detection engine still produces an alert matching
    the stored rule_code. This is what keeps the dataset's labels honest.

    `conflicting_incomplete_evidence` is excluded on purpose: its stored
    fixtures are deliberately *missing* a transaction the original alert's
    evidence referenced (simulating data loss after the fact), so replaying
    only the stored rows will not re-trigger the same rule -- that's the
    whole point of the category, and it's checked separately by
    `test_conflicting_incomplete_evidence_has_a_real_gap`.
    """
    for scenario in dataset:
        if scenario.category == "conflicting_incomplete_evidence":
            continue
        for acc in scenario.accounts:
            db_session.merge(models.Account(**acc.model_dump()))
        db_session.commit()

        rows = {}
        for t in scenario.transactions:
            row = models.Transaction(
                transaction_ref=t.transaction_ref,
                from_account=t.from_account,
                to_account=t.to_account,
                amount=Decimal(t.amount),
                currency=t.currency,
                status="RECEIVED",
                created_at=datetime.fromisoformat(t.created_at),
            )
            db_session.add(row)
            db_session.commit()
            db_session.refresh(row)
            rows[t.transaction_ref] = row
            service.run_detection(db_session, row)

        primary = rows.get(scenario.primary_transaction_ref)
        assert primary is not None, (
            f"{scenario.id}: primary_transaction_ref "
            f"{scenario.primary_transaction_ref!r} was dropped from its own "
            "stored fixtures -- the generator should never drop the "
            "primary transaction."
        )
        alert = (
            db_session.query(models.Alert)
            .filter_by(transaction_id=primary.id, rule_code=scenario.rule_code)
            .one_or_none()
        )
        assert alert is not None, (
            f"{scenario.id}: replaying its fixtures did not reproduce a "
            f"{scenario.rule_code} alert on {scenario.primary_transaction_ref}"
        )

        # Clean up so the next scenario in this loop starts from a clean
        # slate within the same shared session/engine.
        db_session.query(models.Alert).delete()
        db_session.query(models.Transaction).delete()
        db_session.query(models.Account).delete()
        db_session.commit()


def test_invalid_citation_scenarios_actually_cite_unknown_evidence(dataset):
    for scenario in dataset:
        if scenario.category != "invalid_citation":
            continue
        assert scenario.simulated_llm_response is not None
        assert scenario.simulated_llm_failure is None
        assert scenario.expected_status == "FAILED"

        cited = set(scenario.simulated_llm_response.get("cited_transaction_refs", []))
        known = set(scenario.allowed_transaction_refs)
        assert cited - known, (
            f"{scenario.id}: simulated_llm_response doesn't actually cite "
            "anything outside the known evidence, so it wouldn't exercise "
            "the grounding check at all."
        )


def test_model_failure_scenarios_carry_a_valid_failure_mode(dataset):
    for scenario in dataset:
        if scenario.category != "model_failure":
            continue
        assert scenario.simulated_llm_response is None
        assert scenario.simulated_llm_failure in FAILURE_MODES
        assert scenario.expected_status == "FAILED"


def test_conflicting_incomplete_evidence_has_a_real_gap(dataset):
    for scenario in dataset:
        if scenario.category != "conflicting_incomplete_evidence":
            continue
        referenced = set(scenario.alert_evidence.get("transaction_refs", []))
        stored = {t.transaction_ref for t in scenario.transactions}
        assert referenced - stored, (
            f"{scenario.id}: alert evidence doesn't actually reference any "
            "transaction missing from the stored fixtures."
        )


def test_legitimate_unusual_activity_accounts_share_an_owner(dataset):
    for scenario in dataset:
        if scenario.category != "legitimate_unusual_activity":
            continue
        owners = {a.owner_name for a in scenario.accounts}
        assert len(owners) == 1, (
            f"{scenario.id}: expected every account to share one owner "
            "(the whole point of this category), got {owners}"
        )
