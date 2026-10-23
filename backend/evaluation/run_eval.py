"""CLI entry point for the investigation evaluation runner.

The two system-resilience categories (invalid_citation, model_failure)
always run in full -- they're deterministic and fast. The six model-quality
categories call a real local model, so use --sample-per-category to bound
runtime (omit it to run the entire dataset, which is slow by design).

Usage:
    python -m evaluation.run_eval --model qwen2.5-coder:7b --sample-per-category 5
    python -m evaluation.run_eval --model llama3.1:8b --sample-per-category 5 --out evaluation/results/llama3_1_8b.json
    python -m evaluation.run_eval --compare evaluation/results/qwen2.5-coder_7b.json evaluation/results/llama3.1_8b.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.generate import build_dataset
from evaluation.report import compare_runs, format_benchmark_table, load_json, write_csv, write_json
from evaluation.runner import run_evaluation
from investigation.llm_client import OLLAMA_MODEL, OLLAMA_TEMPERATURE, make_generate_fn
from investigation.nodes import PROMPT_VERSION

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _default_out_path(model: str) -> Path:
    safe_model = model.replace(":", "_").replace("/", "_")
    return RESULTS_DIR / f"{safe_model}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the investigation evaluation runner")
    parser.add_argument("--model", type=str, default=OLLAMA_MODEL)
    parser.add_argument("--temperature", type=float, default=OLLAMA_TEMPERATURE)
    parser.add_argument(
        "--sample-per-category",
        type=int,
        default=None,
        help="Cap each model-quality category to N scenarios (resilience categories always run in full)",
    )
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument(
        "--compare",
        nargs="+",
        default=None,
        metavar="RESULTS_JSON",
        help="Skip running anything; print a comparison table across these previously saved result files",
    )
    args = parser.parse_args()

    if args.compare:
        runs = {}
        for path_str in args.compare:
            path = Path(path_str)
            metrics = load_json(path)
            run_config = metrics.get("run_config", {})
            model_name = run_config.get("model_name", path.stem)
            prompt_version = run_config.get("prompt_version")
            # Disambiguate same-model runs (e.g. before/after a prompt
            # change) rather than silently collapsing them under one key.
            label = f"{model_name} [{prompt_version}]" if prompt_version else model_name
            if label in runs:
                label = f"{label} ({path.stem})"
            runs[label] = metrics
        print(format_benchmark_table(runs))
        print()
        print(compare_runs(runs))
        return

    scenarios = build_dataset()

    def _progress(result):
        marker = "OK" if result.status_matches_expected else "MISMATCH"
        print(
            f"[{marker}] {result.category}/{result.scenario_id}: "
            f"{result.actual_status} (expected {result.expected_status}) "
            f"in {result.duration_seconds:.1f}s",
            flush=True,
        )

    generate_fn = make_generate_fn(args.model, temperature=args.temperature)

    results, metrics = run_evaluation(
        scenarios,
        sample_per_category=args.sample_per_category,
        real_generate=generate_fn,
        on_result=_progress,
        run_config={
            "model_name": args.model,
            "temperature": args.temperature,
            "sample_per_category": args.sample_per_category,
            "prompt_version": PROMPT_VERSION,
        },
    )

    out_path = Path(args.out) if args.out else _default_out_path(args.model)
    write_json(metrics, out_path)
    write_csv(results, out_path.with_suffix(".csv"))

    print(f"\nRan {len(results)} scenarios with model={args.model!r}.")
    print(f"Wrote {out_path} and {out_path.with_suffix('.csv')}\n")
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
