"""Read-only API over the saved investigation-evaluation benchmark results
in evaluation/results/. These are NOT live production metrics -- they are
timestamped snapshots of offline benchmark runs (see evaluation/run_eval.py)
kept as frozen artifacts for comparison and history.

Safety: the frontend never supplies a file path. Every result this API can
serve is named in KNOWN_RUNS, a fixed allow-list baked into this module --
there is no endpoint that reads an arbitrary path, uploads a file, or
executes anything. Every file is parsed and validated against
EvaluationRunSummary before being returned; a missing, unreadable, or
malformed file produces a clear per-run error rather than a raw stack trace
or silently wrong data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from auth.dependencies import CurrentUser

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])

RESULTS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "results"

# Fixed allow-list: the only files this API will ever read. Adding a new
# benchmark run means adding an entry here, not accepting a path from a
# request.
KNOWN_RUNS: dict[str, dict[str, str]] = {
    "qwen2.5-coder_7b": {
        "file": "qwen2.5-coder_7b.json",
        "label": "Qwen 2.5 Coder 7B -- v1 prompt (baseline)",
    },
    "qwen2.5-coder_7b_v2": {
        "file": "qwen2.5-coder_7b_v2.json",
        "label": "Qwen 2.5 Coder 7B -- v2 strict-citation-rules prompt",
    },
    "llama3.1_8b": {
        "file": "llama3.1_8b.json",
        "label": "Llama 3.1 8B -- v1 prompt (baseline)",
    },
    "llama3.1_8b_v2": {
        "file": "llama3.1_8b_v2.json",
        "label": "Llama 3.1 8B -- v2 strict-citation-rules prompt (frozen default)",
    },
}

Rate = Field(default=None, ge=0, le=1)


class RunConfig(BaseModel):
    model_name: str | None = None
    temperature: float | None = None
    sample_per_category: int | None = None
    prompt_version: str | None = None


class EvidenceGrounding(BaseModel):
    grounding_rate: float | None = Rate
    unsupported_claim_scenarios: list[str] = Field(default_factory=list)


class CitationValidity(BaseModel):
    citation_validity_rate: float | None = Rate
    invalid_citation_examples: list[str] = Field(default_factory=list)
    hallucination_catch_rate: float | None = Rate


class FactualAccuracy(BaseModel):
    facts_hit_rate: float | None = Rate
    uncertainty_hit_rate: float | None = Rate
    uncertainty_hit_rate_v2: float | None = Rate
    forbidden_claim_violation_count: int = Field(default=0, ge=0)
    forbidden_claim_violation_scenarios: list[str] = Field(default_factory=list)


class LatencyAndReliability(BaseModel):
    median_duration_seconds: float | None = Field(default=None, ge=0)
    p95_duration_seconds: float | None = Field(default=None, ge=0)
    operational_timeout_rate: float | None = Rate
    operational_timeout_rate_label: str | None = None
    failure_rate_by_category: dict[str, float] = Field(default_factory=dict)
    unexpected_status_mismatches: list[str] = Field(default_factory=list)
    # Only present in v1-era result files, kept for backward compatibility
    # when rendering older artifacts -- see metrics.py's history.
    timeout_handling_rate: float | None = Rate


class SystemResilience(BaseModel):
    adversarial_rejection_rate: float | None = Rate
    hallucination_catch_rate: float | None = Rate


class AcceptanceCriteria(BaseModel):
    zero_unsupported_citations: bool | None = None
    zero_invalid_citations_in_successful_reports: bool | None = None


class EvaluationRunSummary(BaseModel):
    """Validated shape of one evaluation/results/*.json file. Required
    fields missing, or any rate outside [0, 1], fails validation here --
    the API returns a clear error rather than passing through a malformed
    artifact.
    """

    id: str
    label: str
    file_name: str
    generated_at: datetime
    scope_note: str | None = None
    scenario_count: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    evidence_grounding: EvidenceGrounding
    citation_validity: CitationValidity
    factual_accuracy: FactualAccuracy
    latency_and_reliability: LatencyAndReliability
    system_resilience: SystemResilience | None = None
    acceptance_criteria: AcceptanceCriteria | None = None
    run_config: RunConfig = Field(default_factory=RunConfig)


class EvaluationRunIndexEntry(BaseModel):
    """Lightweight index row -- always returned for every known run, even
    an unavailable one, so the frontend can show the full history with a
    per-row reason rather than a blank list.
    """

    id: str
    label: str
    available: bool
    error: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    scenario_count: int | None = None
    generated_at: datetime | None = None


def _load_run(run_id: str) -> EvaluationRunSummary:
    entry = KNOWN_RUNS.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown evaluation run '{run_id}'")

    path = RESULTS_DIR / entry["file"]
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Result artifact for '{run_id}' is not available on this server.",
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail=f"Could not read result artifact for '{run_id}': {exc}"
        ) from exc

    try:
        raw: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Result artifact for '{run_id}' is not valid JSON: {exc}",
        ) from exc

    generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    # Guard against the on-disk artifact happening to contain any of these
    # keys itself -- the server-derived values always win.
    for reserved in ("id", "label", "file_name", "generated_at"):
        raw.pop(reserved, None)

    try:
        return EvaluationRunSummary(
            id=run_id,
            label=entry["label"],
            file_name=entry["file"],
            generated_at=generated_at,
            **raw,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Result artifact for '{run_id}' does not match the expected "
            f"evaluation summary shape: {exc.error_count()} field error(s).",
        ) from exc


@router.get("/runs", response_model=list[EvaluationRunIndexEntry])
def list_runs(_user: CurrentUser):
    """Every known benchmark run, available or not, so the UI can render
    full history with a clear reason for anything missing/malformed.
    """
    entries: list[EvaluationRunIndexEntry] = []
    for run_id, meta in KNOWN_RUNS.items():
        try:
            summary = _load_run(run_id)
        except HTTPException as exc:
            entries.append(
                EvaluationRunIndexEntry(
                    id=run_id,
                    label=meta["label"],
                    available=False,
                    error=str(exc.detail),
                )
            )
            continue
        entries.append(
            EvaluationRunIndexEntry(
                id=run_id,
                label=summary.label,
                available=True,
                model_name=summary.run_config.model_name,
                prompt_version=summary.run_config.prompt_version,
                scenario_count=summary.scenario_count,
                generated_at=summary.generated_at,
            )
        )
    return entries


@router.get("/runs/{run_id}", response_model=EvaluationRunSummary)
def get_run(run_id: str, _user: CurrentUser):
    return _load_run(run_id)
