"""Tests for the investigation evaluation module: dataset self-consistency,
metrics scoring, and the end-to-end runner. None of these call a real
model -- quality categories use small deterministic fakes, and the two
resilience categories (invalid_citation, model_failure) are already fully
deterministic by design.
"""

import re
from datetime import datetime
from decimal import Decimal

import pytest

import models
from detection import service
from evaluation.generate import FAILURE_MODES, build_dataset
from evaluation.metrics import aggregate, score_result
from evaluation.report import format_benchmark_table
from evaluation.runner import run_evaluation
from evaluation.schema import CATEGORIES, ScenarioSpec, TransactionFixture

MIN_TOTAL = 300
MAX_TOTAL = 400


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


# --- dataset structure and self-consistency ---


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
            f"(the whole point of this category), got {owners}"
        )


def test_uncertainty_concepts_stay_in_sync_with_keywords(dataset):
    """Every scenario's v2 concept list must have exactly one synonym set
    per v1 keyword, and each set must at least contain its original v1
    phrase -- otherwise the two scorers would silently drift apart.
    """
    for scenario in dataset:
        assert len(scenario.expected_uncertainty_concepts) == len(
            scenario.expected_uncertainty_keywords
        ), f"{scenario.id}: concepts/keywords length mismatch"
        for keyword, concept in zip(
            scenario.expected_uncertainty_keywords, scenario.expected_uncertainty_concepts
        ):
            assert keyword in concept, (
                f"{scenario.id}: v2 concept for {keyword!r} doesn't even "
                "contain the original v1 phrase"
            )


# --- metrics scoring ---


def _scenario(**overrides) -> ScenarioSpec:
    defaults = dict(
        id="test-scenario",
        category="high_value_transfer",
        description="test",
        transactions=[
            TransactionFixture(
                transaction_ref="TXN-1",
                from_account="ACC-A",
                to_account="ACC-B",
                amount="300000.00",
                created_at="2026-01-01T00:00:00+00:00",
            )
        ],
        accounts=[],
        primary_transaction_ref="TXN-1",
        rule_code="TXN_HIGH_VALUE",
        severity="HIGH",
        alert_description="test alert",
        alert_evidence={},
        expected_status="PENDING_REVIEW",
        expected_facts=["300000.00"],
        allowed_transaction_refs=["TXN-1"],
        allowed_accounts=["ACC-A", "ACC-B"],
        expected_uncertainty_keywords=["account registry"],
        forbidden_claim_keywords=["confirmed fraud"],
    )
    defaults.update(overrides)
    return ScenarioSpec(**defaults)


class TestScoreResult:
    def test_facts_and_uncertainty_hits_are_counted(self):
        scenario = _scenario()
        findings = {
            "summary": "Transfer of 300000.00 INR.",
            "confirmed_facts": ["Amount was 300000.00"],
            "uncertainties": ["Account registry has no record for ACC-A."],
            "cited_transaction_refs": ["TXN-1"],
            "cited_accounts": ["ACC-A", "ACC-B"],
        }
        result = score_result(
            scenario,
            actual_status="PENDING_REVIEW",
            duration_seconds=1.0,
            error=None,
            findings=findings,
        )
        assert result.facts_hit == 1 and result.facts_total == 1
        assert result.uncertainty_hit == 1 and result.uncertainty_total == 1
        assert not result.forbidden_claim_violated
        assert result.status_matches_expected

    def test_forbidden_claim_is_detected(self):
        scenario = _scenario()
        findings = {
            "summary": "This is confirmed fraud.",
            "confirmed_facts": [],
            "uncertainties": [],
            "cited_transaction_refs": ["TXN-1"],
            "cited_accounts": [],
        }
        result = score_result(
            scenario,
            actual_status="PENDING_REVIEW",
            duration_seconds=1.0,
            error=None,
            findings=findings,
        )
        assert result.forbidden_claim_violated

    def test_failed_result_skips_fact_scoring(self):
        scenario = _scenario()
        result = score_result(
            scenario,
            actual_status="FAILED",
            duration_seconds=0.5,
            error="Model generation failed: timeout",
            findings=None,
        )
        assert result.facts_hit == 0
        assert not result.status_matches_expected  # expected PENDING_REVIEW
        assert not result.is_hallucination_failure  # it's a timeout, not grounding


class TestUncertaintyScorerV2:
    """Covers exactly what the brittle v1 substring check got wrong: a
    semantically equivalent statement should count as a hit even without
    the literal phrase, a genuinely missing disclosure should still score
    zero, and an unrelated uncertainty must not count as a false hit for a
    concept it has nothing to do with.
    """

    def _scenario_with_concepts(self, concepts: list[list[str]]) -> ScenarioSpec:
        return _scenario(
            expected_uncertainty_keywords=[c[0] for c in concepts],
            expected_uncertainty_concepts=concepts,
        )

    def test_semantically_equivalent_statement_counts_as_a_hit(self):
        scenario = self._scenario_with_concepts(
            [["account registry", "unregistered", "could not be verified"]]
        )
        # Doesn't contain the literal phrase "account registry" at all --
        # this is the exact real-world case that motivated the v2 scorer.
        findings = {
            "summary": "ok",
            "confirmed_facts": [],
            "uncertainties": [
                "The accounts are unregistered, so ownership could not be verified."
            ],
            "recommended_checks": [],
            "cited_transaction_refs": [],
            "cited_accounts": [],
        }
        result = score_result(
            scenario, actual_status="PENDING_REVIEW", duration_seconds=1.0, error=None, findings=findings
        )
        assert result.uncertainty_hit_v2 == 1
        assert result.uncertainty_total_v2 == 1
        # v1, checking only `uncertainties` for the literal phrase, misses it.
        assert result.uncertainty_hit == 0

    def test_hit_in_recommended_checks_still_counts(self):
        scenario = self._scenario_with_concepts([["account registry", "unregistered"]])
        findings = {
            "summary": "ok",
            "confirmed_facts": [],
            "uncertainties": [],
            "recommended_checks": ["Verify the account registry records for both accounts."],
            "cited_transaction_refs": [],
            "cited_accounts": [],
        }
        result = score_result(
            scenario, actual_status="PENDING_REVIEW", duration_seconds=1.0, error=None, findings=findings
        )
        assert result.uncertainty_hit_v2 == 1

    def test_missing_disclosure_scores_zero(self):
        scenario = self._scenario_with_concepts(
            [["account registry", "unregistered", "could not be verified"]]
        )
        findings = {
            "summary": "A transfer of 300000.00 INR occurred.",
            "confirmed_facts": ["Amount was 300000.00"],
            "uncertainties": [],
            "recommended_checks": [],
            "cited_transaction_refs": [],
            "cited_accounts": [],
        }
        result = score_result(
            scenario, actual_status="PENDING_REVIEW", duration_seconds=1.0, error=None, findings=findings
        )
        assert result.uncertainty_hit_v2 == 0
        assert result.uncertainty_total_v2 == 1

    def test_unrelated_uncertainty_is_not_a_false_hit(self):
        # The model does express *some* uncertainty, just about something
        # that has nothing to do with the expected concept -- this must not
        # count, or the scorer would just be checking "did it hedge at all."
        scenario = self._scenario_with_concepts(
            [["account registry", "unregistered", "could not be verified"]]
        )
        findings = {
            "summary": "ok",
            "confirmed_facts": [],
            "uncertainties": ["It is unclear whether the currency conversion rate was accurate."],
            "recommended_checks": [],
            "cited_transaction_refs": [],
            "cited_accounts": [],
        }
        result = score_result(
            scenario, actual_status="PENDING_REVIEW", duration_seconds=1.0, error=None, findings=findings
        )
        assert result.uncertainty_hit_v2 == 0

    def test_multiple_concepts_scored_independently(self):
        scenario = self._scenario_with_concepts(
            [
                ["account registry", "unregistered"],
                ["not found in the database", "could not be retrieved"],
            ]
        )
        findings = {
            "summary": "ok",
            "confirmed_facts": [],
            "uncertainties": ["The referenced transaction could not be retrieved."],
            "recommended_checks": [],
            "cited_transaction_refs": [],
            "cited_accounts": [],
        }
        result = score_result(
            scenario, actual_status="PENDING_REVIEW", duration_seconds=1.0, error=None, findings=findings
        )
        assert result.uncertainty_hit_v2 == 1
        assert result.uncertainty_total_v2 == 2


class TestAggregate:
    def test_hallucination_failure_lowers_grounding_rate(self):
        scenario = _scenario(category="high_value_transfer")
        good = score_result(
            scenario,
            actual_status="PENDING_REVIEW",
            duration_seconds=1.0,
            error=None,
            findings={
                "summary": "ok",
                "confirmed_facts": [],
                "uncertainties": [],
                "cited_transaction_refs": ["TXN-1"],
                "cited_accounts": [],
            },
        )
        bad = score_result(
            scenario,
            actual_status="FAILED",
            duration_seconds=1.0,
            error="Model cited evidence not actually retrieved (possible hallucination)",
            findings=None,
        )
        metrics = aggregate([good, bad], [scenario])
        assert metrics["evidence_grounding"]["grounding_rate"] == 0.5
        assert metrics["evidence_grounding"]["unsupported_claim_scenarios"] == [scenario.id]

    def test_citation_outside_allowed_set_is_caught(self):
        scenario = _scenario()
        result = score_result(
            scenario,
            actual_status="PENDING_REVIEW",
            duration_seconds=1.0,
            error=None,
            findings={
                "summary": "ok",
                "confirmed_facts": [],
                "uncertainties": [],
                "cited_transaction_refs": ["TXN-1", "TXN-NOT-ALLOWED"],
                "cited_accounts": [],
            },
        )
        metrics = aggregate([result], [scenario])
        assert metrics["citation_validity"]["citation_validity_rate"] == 0.5
        assert metrics["acceptance_criteria"]["zero_invalid_citations_in_successful_reports"] is False

    def test_invalid_citation_category_measures_catch_rate(self):
        scenario = _scenario(category="invalid_citation", expected_status="FAILED")
        caught = score_result(
            scenario, actual_status="FAILED", duration_seconds=0.1, error="hallucination", findings=None
        )
        metrics = aggregate([caught], [scenario])
        assert metrics["citation_validity"]["hallucination_catch_rate"] == 1.0

    def test_perfect_run_passes_acceptance_criteria(self):
        scenario = _scenario()
        result = score_result(
            scenario,
            actual_status="PENDING_REVIEW",
            duration_seconds=1.0,
            error=None,
            findings={
                "summary": "ok",
                "confirmed_facts": [],
                "uncertainties": [],
                "cited_transaction_refs": ["TXN-1"],
                "cited_accounts": [],
            },
        )
        metrics = aggregate([result], [scenario])
        assert metrics["acceptance_criteria"]["zero_unsupported_citations"] is True
        assert metrics["acceptance_criteria"]["zero_invalid_citations_in_successful_reports"] is True


# --- end-to-end runner ---


def _grounded_fake_llm(prompt: str) -> dict:
    refs = re.findall(r'"transaction_ref":\s*"([^"]+)"', prompt)
    accounts = sorted(
        set(re.findall(r'"from_account":\s*"([^"]+)"', prompt))
        | set(re.findall(r'"to_account":\s*"([^"]+)"', prompt))
    )
    return {
        "summary": "Fake grounded summary.",
        "confirmed_facts": [],
        "hypotheses": [],
        "uncertainties": [],
        "recommended_checks": [],
        "cited_transaction_refs": refs,
        "cited_accounts": accounts,
    }


class TestRunEvaluationEndToEnd:
    def test_sampled_run_across_full_dataset_matches_expectations(self):
        scenarios = build_dataset()
        results, metrics = run_evaluation(
            scenarios,
            sample_per_category=1,
            real_generate=_grounded_fake_llm,
            run_config={"model_name": "fake"},
        )
        # 6 quality categories x 1 + 2 resilience categories x 40 (always full)
        assert len(results) == 6 * 1 + 2 * 40

        assert metrics["acceptance_criteria"]["zero_unsupported_citations"] is True
        assert metrics["acceptance_criteria"]["zero_invalid_citations_in_successful_reports"] is True
        assert metrics["citation_validity"]["hallucination_catch_rate"] == 1.0
        assert metrics["system_resilience"]["adversarial_rejection_rate"] == 1.0
        assert metrics["latency_and_reliability"]["unexpected_status_mismatches"] == []
        assert metrics["run_config"]["model_name"] == "fake"


class TestBenchmarkTable:
    def test_format_benchmark_table_renders_all_rows_for_each_model(self):
        scenarios = build_dataset()
        _, metrics_a = run_evaluation(
            scenarios,
            sample_per_category=1,
            real_generate=_grounded_fake_llm,
            run_config={"model_name": "fake-a"},
        )
        _, metrics_b = run_evaluation(
            scenarios,
            sample_per_category=1,
            real_generate=_grounded_fake_llm,
            run_config={"model_name": "fake-b"},
        )
        table = format_benchmark_table({"fake-a": metrics_a, "fake-b": metrics_b})
        for row_label in (
            "Scenarios completed",
            "Valid report rate",
            "Facts hit rate",
            "Uncertainty hit rate",
            "Unsupported citation rate",
            "Median latency",
            "P95 latency",
            "Adversarial rejection rate",
            "Operational timeout rate",
        ):
            assert row_label in table
        assert "fake-a" in table and "fake-b" in table
