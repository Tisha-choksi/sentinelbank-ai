"""Runs evaluation scenarios through the real investigation pipeline and
scores the results.

For `invalid_citation` and `model_failure`, no real model is called -- the
scenario carries a canned response or a failure mode to inject, so those
two categories are fast, deterministic, and always run in full. For the
other six "quality" categories, the real Ollama model is called (unless a
fake `llm_generate` is passed in, e.g. from tests), so running the full
dataset is slow by design -- use `sample_per_category` to bound it.
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from db import Base
from evaluation.metrics import ScenarioResult, aggregate, score_result
from evaluation.schema import QUALITY_CATEGORIES, ScenarioSpec
from investigation.graph import run_investigation
from investigation.llm_client import LLMError
from investigation.llm_client import generate_json as real_generate_json


def _resolve_llm_fn(
    scenario: ScenarioSpec, real_generate: Callable[[str], dict]
) -> Callable[[str], dict]:
    if scenario.simulated_llm_response is not None:
        response = scenario.simulated_llm_response
        return lambda _prompt: response

    if scenario.simulated_llm_failure is not None:
        failure = scenario.simulated_llm_failure

        if failure == "wrong_shape":
            return lambda _prompt: {"unexpected_field": "not a valid report shape"}

        message = {
            "timeout": "simulated timeout",
            "malformed_json": "simulated malformed JSON",
        }[failure]

        def _raise(_prompt: str) -> dict:
            raise LLMError(message)

        return _raise

    return real_generate


def _build_fresh_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)(), engine


def run_scenario(
    scenario: ScenarioSpec, *, real_generate: Callable[[str], dict] = real_generate_json
) -> ScenarioResult:
    """Recreates the scenario's DB state, inserts its alert directly from
    the recorded ground truth (not re-derived via detection -- some
    categories, like conflicting_incomplete_evidence, store deliberately
    incomplete fixtures that wouldn't re-trigger the rule), then runs the
    real investigation graph against it.
    """
    db, engine = _build_fresh_db()
    try:
        for acc in scenario.accounts:
            db.add(models.Account(**acc.model_dump()))
        db.commit()

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
            db.add(row)
            db.commit()
            db.refresh(row)
            rows[t.transaction_ref] = row

        primary = rows[scenario.primary_transaction_ref]
        alert = models.Alert(
            transaction_id=primary.id,
            rule_code=scenario.rule_code,
            severity=scenario.severity,
            status="OPEN",
            description=scenario.alert_description,
            evidence=scenario.alert_evidence,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        llm_fn = _resolve_llm_fn(scenario, real_generate)

        start = time.monotonic()
        error: str | None = None
        actual_status = "FAILED"
        findings: dict | None = None
        try:
            report = run_investigation(db, alert.id, llm_generate=llm_fn)
            actual_status = report.status
            findings = report.findings if report.status != "FAILED" else None
            if report.status == "FAILED":
                error = report.findings.get("error")
        except Exception as exc:  # noqa: BLE001 - captured as a scenario result, not a test failure
            error = f"{type(exc).__name__}: {exc}"
        duration = time.monotonic() - start

        return score_result(
            scenario,
            actual_status=actual_status,
            duration_seconds=duration,
            error=error,
            findings=findings,
        )
    finally:
        db.close()
        engine.dispose()


def run_evaluation(
    scenarios: list[ScenarioSpec],
    *,
    sample_per_category: int | None = None,
    real_generate: Callable[[str], dict] = real_generate_json,
    on_result: Callable[[ScenarioResult], None] | None = None,
    run_config: dict | None = None,
) -> tuple[list[ScenarioResult], dict]:
    """Runs `scenarios`, optionally capped to `sample_per_category` per
    category (deterministic categories are never capped, since they're
    cheap). Returns (results, aggregate_metrics).

    `run_config` is opaque metadata (e.g. {"model_name": ..., "temperature":
    ...}) recorded on the returned metrics so results from different model
    comparison runs stay self-describing once saved to disk.
    """
    by_category: dict[str, list[ScenarioSpec]] = {}
    for s in scenarios:
        by_category.setdefault(s.category, []).append(s)

    selected: list[ScenarioSpec] = []
    for category, group in by_category.items():
        if sample_per_category is not None and category in QUALITY_CATEGORIES:
            selected.extend(group[:sample_per_category])
        else:
            selected.extend(group)

    results: list[ScenarioResult] = []
    for scenario in selected:
        result = run_scenario(scenario, real_generate=real_generate)
        results.append(result)
        if on_result is not None:
            on_result(result)

    metrics = aggregate(results, scenarios)
    metrics["run_config"] = run_config or {}
    return results, metrics
