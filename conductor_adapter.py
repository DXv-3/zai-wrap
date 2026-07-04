#!/usr/bin/env python3
"""conductor_adapter.py — Drop-in model caller for conductor-protocol-v2.

This is the integration point between conductor-protocol-v2 and zai-wrap.
Conductor imports this module and calls call_model() instead of making
direct API calls. This gives conductor:

    - Multi-backend routing (Grok, Claude, GPT-4, Deepseek, Gemini)
    - Automatic fallback on failure (configured per environment)
    - Brain bus logging of every model call (async, non-blocking)
    - A typed interface with no hardcoded API clients in conductor

Usage in conductor-protocol-v2/operator_router/router.py:

    from conductor_adapter import call_model, ModelCallResult

    result = call_model(
        model=task_config.get("model", "grok-3"),
        prompt=prompt_text,
        system=system_prompt,
        run_id=task_config.get("run_id", ""),
    )
    if not result.success:
        # conductor can decide to retry, hard-block, or escalate
        raise ModelCallError(result.error)
    response_text = result.content
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from model_dispatch import ModelRequest, ModelResponse, dispatch, dispatch_with_fallback


@dataclass
class ModelCallResult:
    """Simplified result type for conductor. Maps from ModelResponse."""
    success: bool
    content: str
    error: str = ""
    model_used: str = ""
    backend: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_response(cls, resp: ModelResponse) -> "ModelCallResult":
        return cls(
            success=resp.success,
            content=resp.content,
            error=resp.error,
            model_used=resp.model,
            backend=resp.backend,
            latency_ms=resp.latency_ms,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )


class ModelCallError(Exception):
    """Raised by conductor when a model call fails and no fallback succeeded."""
    def __init__(self, error: str, model: str = "", backend: str = ""):
        super().__init__(error)
        self.model = model
        self.backend = backend


# Default fallback chain — override via CONDUCTOR_MODEL_FALLBACKS env var
# Format: comma-separated model names
_DEFAULT_FALLBACKS = [
    "gpt-4o",
    "claude-3-5-sonnet-20241022",
    "deepseek-chat",
]


def _get_fallback_chain() -> list[str]:
    env_fallbacks = os.environ.get("CONDUCTOR_MODEL_FALLBACKS", "")
    if env_fallbacks:
        return [m.strip() for m in env_fallbacks.split(",") if m.strip()]
    return _DEFAULT_FALLBACKS


def call_model(
    model: str,
    prompt: str,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    run_id: str = "",
    use_fallback: bool = True,
    metadata: dict | None = None,
) -> ModelCallResult:
    """Call a model via zai-wrap dispatch. Used by conductor-protocol-v2.

    Args:
        model: Model name (e.g. 'grok-3', 'claude-3-5-sonnet-20241022')
        prompt: User prompt text
        system: System prompt (optional)
        max_tokens: Max output tokens
        temperature: Sampling temperature
        run_id: Conductor run ID for brain logging
        use_fallback: If True, tries fallback models on failure
        metadata: Extra metadata passed through to brain logging

    Returns:
        ModelCallResult with success/content/error/latency

    Note:
        This function never raises. Check result.success.
        Brain bus write happens async after the call.
    """
    req = ModelRequest(
        model=model,
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        run_id=run_id,
        source="conductor-protocol-v2",
        metadata=metadata or {},
    )

    if use_fallback:
        resp = dispatch_with_fallback(req, fallback_models=_get_fallback_chain())
    else:
        resp = dispatch(req)

    return ModelCallResult.from_response(resp)


def call_model_strict(
    model: str,
    prompt: str,
    system: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.7,
    run_id: str = "",
) -> ModelCallResult:
    """Like call_model but raises ModelCallError on failure. No fallback.

    Use when conductor needs to know exactly which model was called
    (e.g., for provenance gating where model identity matters).
    """
    result = call_model(model, prompt, system, max_tokens, temperature,
                        run_id, use_fallback=False)
    if not result.success:
        raise ModelCallError(result.error, model=model, backend=result.backend)
    return result
