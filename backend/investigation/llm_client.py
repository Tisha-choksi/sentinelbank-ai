"""Thin wrapper around a local Ollama model. Kept separate from the graph
nodes so model failures (connection refused, timeout, malformed JSON) are
easy to simulate in tests by passing a fake `llm_generate` callable, without
needing a real Ollama server running.
"""

from __future__ import annotations

import json
import os
from typing import Callable

import httpx

# Default model frozen to llama3.1:8b per the evaluation/results/*_v2.json
# comparison: with the v2 (strict-citation-rules) prompt, both models hit
# 100% adversarial rejection and 0% operational timeouts, but llama reached
# 100% evidence grounding (vs. qwen's 96.7%) and a higher facts_hit_rate,
# while the earlier latency gap closed to near-zero (~62s median for both).
# Override with the OLLAMA_MODEL env var for local experimentation.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))


class LLMError(RuntimeError):
    """Raised for any model failure: unreachable server, HTTP error, or
    output that isn't valid JSON. Callers only need to handle this one
    exception type.
    """


def generate_json(
    prompt: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
) -> dict:
    target_model = model or OLLAMA_MODEL
    target_temperature = OLLAMA_TEMPERATURE if temperature is None else temperature
    try:
        response = httpx.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": target_model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": target_temperature},
            },
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc

    payload = response.json()
    raw_text = payload.get("response", "")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}") from exc


def make_generate_fn(
    model: str, *, temperature: float = OLLAMA_TEMPERATURE
) -> Callable[[str], dict]:
    """Binds a fixed model + temperature into a callable matching the
    `llm_generate(prompt) -> dict` signature the investigation graph (and
    the evaluation runner) expect. Used to keep every other variable --
    prompt, evidence bundles, evaluation criteria -- identical while
    comparing different models.
    """

    def _generate(prompt: str) -> dict:
        return generate_json(prompt, model=model, temperature=temperature)

    return _generate
