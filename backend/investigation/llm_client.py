"""Thin wrapper around a local Ollama model. Kept separate from the graph
nodes so model failures (connection refused, timeout, malformed JSON) are
easy to simulate in tests by passing a fake `llm_generate` callable, without
needing a real Ollama server running.
"""

from __future__ import annotations

import json
import os

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))


class LLMError(RuntimeError):
    """Raised for any model failure: unreachable server, HTTP error, or
    output that isn't valid JSON. Callers only need to handle this one
    exception type.
    """


def generate_json(prompt: str, *, model: str | None = None) -> dict:
    target_model = model or OLLAMA_MODEL
    try:
        response = httpx.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": target_model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
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
