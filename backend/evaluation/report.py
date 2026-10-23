"""Exports evaluation results to JSON/CSV and builds the side-by-side
model-comparison table used to decide whether a different local model is
worth its extra inference cost.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from evaluation.metrics import ScenarioResult

COMPARISON_FIELDS = (
    ("evidence_grounding", "grounding_rate"),
    ("citation_validity", "citation_validity_rate"),
    ("system_resilience", "adversarial_rejection_rate"),
    ("system_resilience", "hallucination_catch_rate"),
    ("factual_accuracy", "facts_hit_rate"),
    ("factual_accuracy", "uncertainty_hit_rate"),
    ("factual_accuracy", "uncertainty_hit_rate_v2"),
    ("factual_accuracy", "forbidden_claim_violation_count"),
    ("latency_and_reliability", "median_duration_seconds"),
    ("latency_and_reliability", "p95_duration_seconds"),
    ("latency_and_reliability", "operational_timeout_rate"),
)


def write_json(metrics: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")


def write_csv(results: list[ScenarioResult], path: Path) -> None:
    """One row per scenario -- the per-scenario detail that the aggregate
    JSON summarizes away, useful for spot-checking exactly which scenarios
    drove a metric down.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario_id",
        "category",
        "expected_status",
        "actual_status",
        "status_matches_expected",
        "duration_seconds",
        "facts_hit",
        "facts_total",
        "uncertainty_hit",
        "uncertainty_total",
        "forbidden_claim_violated",
        "error",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "scenario_id": r.scenario_id,
                    "category": r.category,
                    "expected_status": r.expected_status,
                    "actual_status": r.actual_status,
                    "status_matches_expected": r.status_matches_expected,
                    "duration_seconds": round(r.duration_seconds, 3),
                    "facts_hit": r.facts_hit,
                    "facts_total": r.facts_total,
                    "uncertainty_hit": r.uncertainty_hit,
                    "uncertainty_total": r.uncertainty_total,
                    "forbidden_claim_violated": r.forbidden_claim_violated,
                    "error": r.error or "",
                }
            )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get(metrics: dict[str, Any], section: str, field: str):
    return metrics.get(section, {}).get(field)


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _valid_report_rate(m: dict[str, Any]) -> float | None:
    grounding = m["evidence_grounding"]["grounding_rate"]
    timeout = m["latency_and_reliability"]["operational_timeout_rate"]
    if grounding is None or timeout is None:
        return None
    # A report is "valid" unless it failed -- whether from an ungrounded
    # citation or a genuine operational problem. Both failure types are
    # mutually exclusive subsets of the same quality-category scenarios.
    return 1 - (1 - grounding) - timeout


BENCHMARK_ROWS = (
    ("Scenarios completed", lambda m: m.get("scenario_count")),
    ("Valid report rate", _valid_report_rate),
    ("Facts hit rate", lambda m: m["factual_accuracy"]["facts_hit_rate"]),
    ("Uncertainty hit rate", lambda m: m["factual_accuracy"]["uncertainty_hit_rate"]),
    (
        "Uncertainty hit rate v2",
        lambda m: m["factual_accuracy"].get("uncertainty_hit_rate_v2"),
    ),
    (
        "Unsupported citation rate",
        lambda m: (
            None
            if m["evidence_grounding"]["grounding_rate"] is None
            else 1 - m["evidence_grounding"]["grounding_rate"]
        ),
    ),
    ("Median latency (s)", lambda m: m["latency_and_reliability"]["median_duration_seconds"]),
    ("P95 latency (s)", lambda m: m["latency_and_reliability"]["p95_duration_seconds"]),
    (
        "Adversarial rejection rate",
        lambda m: m["system_resilience"]["adversarial_rejection_rate"],
    ),
    (
        "Operational timeout rate",
        lambda m: m["latency_and_reliability"]["operational_timeout_rate"],
    ),
)


def format_benchmark_table(runs: dict[str, dict[str, Any]]) -> str:
    """Produces the exact "metric x model" comparison table shape used to
    decide whether a model swap is worth its extra inference cost: scenario
    completion, valid-report rate, grounding, unsupported citations, and
    latency/timeout handling -- quality and speed kept as separate rows on
    purpose, never collapsed into one score, so latency alone can't
    accidentally decide the winner.
    """
    labels = list(runs.keys())
    col_width = max(18, *(len(label) for label in labels)) + 2
    header = "Metric".ljust(28) + "".join(label.ljust(col_width) for label in labels)
    lines = [header, "-" * len(header)]
    for row_label, extractor in BENCHMARK_ROWS:
        row = row_label.ljust(28)
        for label in labels:
            try:
                value = extractor(runs[label])
            except (KeyError, ZeroDivisionError):
                value = None
            row += _fmt(value).ljust(col_width)
        lines.append(row)
    return "\n".join(lines)


def compare_runs(runs: dict[str, dict[str, Any]]) -> str:
    """Builds a plain-text side-by-side table across one or more named
    runs (e.g. {"qwen2.5-coder:7b": metrics_a, "llama3.1:8b": metrics_b}).
    """
    labels = list(runs.keys())
    col_width = max(24, *(len(label) for label in labels)) + 2
    label_width = max(len(f"{s}.{f}") for s, f in COMPARISON_FIELDS) + 2

    header = "metric".ljust(label_width) + "".join(label.ljust(col_width) for label in labels)
    lines = [header, "-" * len(header)]

    for section, field in COMPARISON_FIELDS:
        row_label = f"{section}.{field}"
        row = row_label.ljust(label_width)
        for label in labels:
            value = _get(runs[label], section, field)
            row += _fmt(value).ljust(col_width)
        lines.append(row)

    lines.append("")
    lines.append("run_config".ljust(label_width) + "".join(
        _fmt(runs[label].get("run_config", {})).ljust(col_width) for label in labels
    ))
    return "\n".join(lines)
