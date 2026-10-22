"""Per-scenario scoring and aggregate metrics for the investigation
evaluation harness. Implements the four metric families from the eval
plan: evidence grounding rate, citation validity, factual accuracy /
uncertainty handling, and latency & reliability.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from evaluation.schema import QUALITY_CATEGORIES, RESILIENCE_CATEGORIES, ScenarioSpec

HALLUCINATION_MARKERS = ("hallucination", "not actually retrieved")


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    expected_status: str
    actual_status: str
    duration_seconds: float
    error: str | None
    summary: str
    cited_transaction_refs: list[str] = field(default_factory=list)
    cited_accounts: list[str] = field(default_factory=list)
    facts_hit: int = 0
    facts_total: int = 0
    uncertainty_hit: int = 0
    uncertainty_total: int = 0
    forbidden_claim_violated: bool = False

    @property
    def status_matches_expected(self) -> bool:
        return self.actual_status == self.expected_status

    @property
    def is_hallucination_failure(self) -> bool:
        return self.actual_status == "FAILED" and bool(self.error) and any(
            marker in self.error.lower() for marker in HALLUCINATION_MARKERS
        )


def score_result(
    scenario: ScenarioSpec,
    *,
    actual_status: str,
    duration_seconds: float,
    error: str | None,
    findings: dict[str, Any] | None,
) -> ScenarioResult:
    findings = findings or {}
    summary = str(findings.get("summary", "") or "")
    confirmed_facts = [str(x) for x in findings.get("confirmed_facts", [])]
    uncertainties = [str(x) for x in findings.get("uncertainties", [])]
    cited_refs = [str(x) for x in findings.get("cited_transaction_refs", [])]
    cited_accounts = [str(x) for x in findings.get("cited_accounts", [])]

    confirmed_text = " ".join([summary, *confirmed_facts]).lower()
    uncertainty_text = " ".join(uncertainties).lower()

    facts_hit = sum(1 for f in scenario.expected_facts if f.lower() in confirmed_text)
    uncertainty_hit = sum(
        1 for k in scenario.expected_uncertainty_keywords if k.lower() in uncertainty_text
    )
    forbidden_hit = any(
        k.lower() in confirmed_text for k in scenario.forbidden_claim_keywords
    )

    return ScenarioResult(
        scenario_id=scenario.id,
        category=scenario.category,
        expected_status=scenario.expected_status,
        actual_status=actual_status,
        duration_seconds=duration_seconds,
        error=error,
        summary=summary,
        cited_transaction_refs=cited_refs,
        cited_accounts=cited_accounts,
        facts_hit=facts_hit,
        facts_total=len(scenario.expected_facts),
        uncertainty_hit=uncertainty_hit,
        uncertainty_total=len(scenario.expected_uncertainty_keywords),
        forbidden_claim_violated=forbidden_hit,
    )


def _citation_validity(results: list[ScenarioResult], scenarios_by_id: dict[str, ScenarioSpec]):
    valid = 0
    total = 0
    offenders: list[str] = []
    for r in results:
        if r.actual_status != "PENDING_REVIEW":
            continue
        scenario = scenarios_by_id[r.scenario_id]
        allowed_refs = set(scenario.allowed_transaction_refs)
        allowed_accounts = set(scenario.allowed_accounts)
        attempted = [(ref, True) for ref in r.cited_transaction_refs] + [
            (acc, False) for acc in r.cited_accounts
        ]
        for value, is_ref in attempted:
            total += 1
            ok = value in allowed_refs if is_ref else value in allowed_accounts
            if ok:
                valid += 1
            else:
                offenders.append(f"{r.scenario_id}: cited unknown {'ref' if is_ref else 'account'} {value!r}")
    rate = (valid / total) if total else None
    return rate, offenders


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def aggregate(results: list[ScenarioResult], scenarios: list[ScenarioSpec]) -> dict[str, Any]:
    scenarios_by_id = {s.id: s for s in scenarios}
    by_category: dict[str, list[ScenarioResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    quality_results = [r for r in results if r.category in QUALITY_CATEGORIES]

    # --- 1. Evidence grounding rate ---
    unsupported = [r for r in quality_results if r.is_hallucination_failure]
    grounding_rate = (
        1 - len(unsupported) / len(quality_results) if quality_results else None
    )

    # --- 2. Citation validity ---
    citation_validity_rate, citation_offenders = _citation_validity(results, scenarios_by_id)
    invalid_citation_results = [r for r in results if r.category == "invalid_citation"]
    hallucination_catch_rate = (
        sum(1 for r in invalid_citation_results if r.status_matches_expected)
        / len(invalid_citation_results)
        if invalid_citation_results
        else None
    )

    # --- 3. Factual accuracy / uncertainty handling ---
    facts_scored = [r for r in quality_results if r.facts_total > 0]
    uncertainty_scored = [r for r in quality_results if r.uncertainty_total > 0]
    facts_hit_rate = (
        sum(r.facts_hit / r.facts_total for r in facts_scored) / len(facts_scored)
        if facts_scored
        else None
    )
    uncertainty_hit_rate = (
        sum(r.uncertainty_hit / r.uncertainty_total for r in uncertainty_scored)
        / len(uncertainty_scored)
        if uncertainty_scored
        else None
    )
    forbidden_claim_violations = [r for r in results if r.forbidden_claim_violated]

    # --- 4. Latency & reliability ---
    # These two numbers must never be collapsed into one "failure rate":
    # the 80 resilience-category scenarios are SUPPOSED to fail (that's the
    # grounding check working), while a failure among the 60 live quality
    # calls is a genuine operational problem (timeout, malformed output).
    durations = [r.duration_seconds for r in quality_results]

    adversarial_results = [r for r in results if r.category in RESILIENCE_CATEGORIES]
    adversarial_rejection_rate = (
        sum(1 for r in adversarial_results if r.status_matches_expected)
        / len(adversarial_results)
        if adversarial_results
        else None
    )

    operational_failures = [
        r for r in quality_results if r.actual_status == "FAILED" and not r.is_hallucination_failure
    ]
    operational_timeout_rate = (
        len(operational_failures) / len(quality_results) if quality_results else None
    )

    failure_rate_by_category = {
        cat: sum(1 for r in rs if r.actual_status == "FAILED") / len(rs)
        for cat, rs in by_category.items()
    }
    unexpected_mismatches = [r for r in results if not r.status_matches_expected]

    return {
        "scope_note": (
            "This measures INVESTIGATION quality only: every scenario's "
            "alert is seeded as already-correct ground truth (see "
            "evaluation/generate.py). It says nothing about whether "
            "detection would have caught the underlying activity in the "
            "first place -- that is covered separately by "
            "tests/test_rules.py and tests/test_service.py. A clean run "
            "here does not mean detection has no blind spots, and a noisy "
            "detection rule cannot be fixed by a better investigation report."
        ),
        "scenario_count": len(results),
        "category_counts": {cat: len(rs) for cat, rs in by_category.items()},
        "evidence_grounding": {
            "grounding_rate": grounding_rate,
            "unsupported_claim_scenarios": [r.scenario_id for r in unsupported],
        },
        "citation_validity": {
            "citation_validity_rate": citation_validity_rate,
            "invalid_citation_examples": citation_offenders,
            "hallucination_catch_rate": hallucination_catch_rate,
        },
        "factual_accuracy": {
            "facts_hit_rate": facts_hit_rate,
            "uncertainty_hit_rate": uncertainty_hit_rate,
            "forbidden_claim_violation_count": len(forbidden_claim_violations),
            "forbidden_claim_violation_scenarios": [
                r.scenario_id for r in forbidden_claim_violations
            ],
        },
        "latency_and_reliability": {
            "median_duration_seconds": statistics.median(durations) if durations else None,
            "p95_duration_seconds": _percentile(durations, 95),
            "operational_timeout_rate": operational_timeout_rate,
            "operational_timeout_rate_label": (
                f"{len(operational_failures)}/{len(quality_results)} live calls"
                if quality_results
                else "n/a"
            ),
            "failure_rate_by_category": failure_rate_by_category,
            "unexpected_status_mismatches": [r.scenario_id for r in unexpected_mismatches],
        },
        "system_resilience": {
            "adversarial_rejection_rate": adversarial_rejection_rate,
            "hallucination_catch_rate": hallucination_catch_rate,
        },
        "acceptance_criteria": {
            "zero_unsupported_citations": len(unsupported) == 0,
            "zero_invalid_citations_in_successful_reports": len(citation_offenders) == 0,
        },
    }
