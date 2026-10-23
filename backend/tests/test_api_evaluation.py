"""Tests for the read-only evaluation API (api/evaluation.py). These never
touch the real evaluation/results/*.json artifacts -- KNOWN_RUNS and
RESULTS_DIR are monkeypatched to point at hermetic fixture files per test,
so the real benchmark history can't be read, mutated, or depended on here.
"""

import json

import pytest
from fastapi.testclient import TestClient

import api.evaluation as evaluation_api
from main import app

client = TestClient(app)

VALID_RESULT = {
    "scope_note": "test scope note",
    "scenario_count": 10,
    "category_counts": {"high_value_transfer": 10},
    "evidence_grounding": {"grounding_rate": 0.9, "unsupported_claim_scenarios": []},
    "citation_validity": {
        "citation_validity_rate": 1.0,
        "invalid_citation_examples": [],
        "hallucination_catch_rate": 1.0,
    },
    "factual_accuracy": {
        "facts_hit_rate": 0.8,
        "uncertainty_hit_rate": 0.5,
        "forbidden_claim_violation_count": 0,
        "forbidden_claim_violation_scenarios": [],
    },
    "latency_and_reliability": {
        "median_duration_seconds": 10.0,
        "p95_duration_seconds": 20.0,
        "operational_timeout_rate": 0.0,
        "operational_timeout_rate_label": "0/10 live calls",
        "failure_rate_by_category": {},
        "unexpected_status_mismatches": [],
    },
    "system_resilience": {
        "adversarial_rejection_rate": 1.0,
        "hallucination_catch_rate": 1.0,
    },
    "acceptance_criteria": {
        "zero_unsupported_citations": True,
        "zero_invalid_citations_in_successful_reports": True,
    },
    "run_config": {
        "model_name": "test-model",
        "temperature": 0.2,
        "sample_per_category": 10,
        "prompt_version": "v2-strict-citation-rules",
    },
}


@pytest.fixture()
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation_api, "RESULTS_DIR", tmp_path)
    return tmp_path


def _write(dir_, name: str, content: str) -> None:
    (dir_ / name).write_text(content, encoding="utf-8")


def _set_known_runs(monkeypatch, runs: dict):
    monkeypatch.setattr(evaluation_api, "KNOWN_RUNS", runs)


class TestValidResult:
    def test_list_runs_returns_available_entry(self, results_dir, monkeypatch):
        _write(results_dir, "good.json", json.dumps(VALID_RESULT))
        _set_known_runs(
            monkeypatch, {"good": {"file": "good.json", "label": "Good Run"}}
        )

        res = client.get("/api/v1/evaluation/runs")
        assert res.status_code == 200
        [entry] = res.json()
        assert entry["available"] is True
        assert entry["error"] is None
        assert entry["model_name"] == "test-model"
        assert entry["prompt_version"] == "v2-strict-citation-rules"
        assert entry["scenario_count"] == 10
        assert entry["generated_at"] is not None

    def test_get_run_returns_full_validated_summary(self, results_dir, monkeypatch):
        _write(results_dir, "good.json", json.dumps(VALID_RESULT))
        _set_known_runs(
            monkeypatch, {"good": {"file": "good.json", "label": "Good Run"}}
        )

        res = client.get("/api/v1/evaluation/runs/good")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == "good"
        assert body["scope_note"] == "test scope note"
        assert body["evidence_grounding"]["grounding_rate"] == 0.9
        assert body["run_config"]["model_name"] == "test-model"

    def test_server_derived_fields_win_over_file_contents(self, results_dir, monkeypatch):
        poisoned = dict(VALID_RESULT)
        poisoned["id"] = "not-the-real-id"
        poisoned["label"] = "not the real label"
        _write(results_dir, "good.json", json.dumps(poisoned))
        _set_known_runs(
            monkeypatch, {"good": {"file": "good.json", "label": "Good Run"}}
        )

        res = client.get("/api/v1/evaluation/runs/good")
        assert res.status_code == 200
        assert res.json()["id"] == "good"
        assert res.json()["label"] == "Good Run"


class TestMissingFile:
    def test_unlisted_file_marks_run_unavailable_in_index(self, results_dir, monkeypatch):
        _set_known_runs(
            monkeypatch,
            {"ghost": {"file": "does-not-exist.json", "label": "Ghost Run"}},
        )

        res = client.get("/api/v1/evaluation/runs")
        assert res.status_code == 200
        [entry] = res.json()
        assert entry["available"] is False
        assert "not available" in entry["error"].lower()

    def test_missing_file_detail_returns_404(self, results_dir, monkeypatch):
        _set_known_runs(
            monkeypatch,
            {"ghost": {"file": "does-not-exist.json", "label": "Ghost Run"}},
        )

        res = client.get("/api/v1/evaluation/runs/ghost")
        assert res.status_code == 404

    def test_unknown_run_id_returns_404(self, results_dir, monkeypatch):
        _set_known_runs(monkeypatch, {})
        res = client.get("/api/v1/evaluation/runs/totally-made-up")
        assert res.status_code == 404


class TestMalformedJson:
    def test_malformed_json_marked_unavailable_in_index(self, results_dir, monkeypatch):
        _write(results_dir, "bad.json", "{not valid json,,,")
        _set_known_runs(
            monkeypatch, {"bad": {"file": "bad.json", "label": "Bad Run"}}
        )

        res = client.get("/api/v1/evaluation/runs")
        [entry] = res.json()
        assert entry["available"] is False
        assert "json" in entry["error"].lower()

    def test_malformed_json_detail_returns_422(self, results_dir, monkeypatch):
        _write(results_dir, "bad.json", "{not valid json,,,")
        _set_known_runs(
            monkeypatch, {"bad": {"file": "bad.json", "label": "Bad Run"}}
        )

        res = client.get("/api/v1/evaluation/runs/bad")
        assert res.status_code == 422


class TestMetricValidation:
    def test_out_of_range_rate_is_rejected(self, results_dir, monkeypatch):
        invalid = json.loads(json.dumps(VALID_RESULT))
        invalid["evidence_grounding"]["grounding_rate"] = 1.5  # out of [0, 1]
        _write(results_dir, "bad_metric.json", json.dumps(invalid))
        _set_known_runs(
            monkeypatch,
            {"bad_metric": {"file": "bad_metric.json", "label": "Bad Metric Run"}},
        )

        res = client.get("/api/v1/evaluation/runs/bad_metric")
        assert res.status_code == 422
        assert "expected evaluation summary shape" in res.json()["detail"].lower()

    def test_missing_required_field_is_rejected(self, results_dir, monkeypatch):
        invalid = json.loads(json.dumps(VALID_RESULT))
        del invalid["evidence_grounding"]  # required field
        _write(results_dir, "missing_field.json", json.dumps(invalid))
        _set_known_runs(
            monkeypatch,
            {"missing_field": {"file": "missing_field.json", "label": "Missing Field Run"}},
        )

        res = client.get("/api/v1/evaluation/runs/missing_field")
        assert res.status_code == 422

    def test_negative_scenario_count_is_rejected(self, results_dir, monkeypatch):
        invalid = json.loads(json.dumps(VALID_RESULT))
        invalid["scenario_count"] = -5
        _write(results_dir, "negative.json", json.dumps(invalid))
        _set_known_runs(
            monkeypatch, {"negative": {"file": "negative.json", "label": "Negative Run"}}
        )

        res = client.get("/api/v1/evaluation/runs/negative")
        assert res.status_code == 422


class TestMixedAvailability:
    def test_index_lists_every_known_run_even_when_some_fail(self, results_dir, monkeypatch):
        _write(results_dir, "good.json", json.dumps(VALID_RESULT))
        _set_known_runs(
            monkeypatch,
            {
                "good": {"file": "good.json", "label": "Good Run"},
                "missing": {"file": "nope.json", "label": "Missing Run"},
                "corrupt": {"file": "corrupt.json", "label": "Corrupt Run"},
            },
        )
        _write(results_dir, "corrupt.json", "not json at all")

        res = client.get("/api/v1/evaluation/runs")
        assert res.status_code == 200
        by_id = {e["id"]: e for e in res.json()}
        assert set(by_id) == {"good", "missing", "corrupt"}
        assert by_id["good"]["available"] is True
        assert by_id["missing"]["available"] is False
        assert by_id["corrupt"]["available"] is False
