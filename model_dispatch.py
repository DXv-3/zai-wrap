#!/usr/bin/env python3
"""model_dispatch.py — Universal model dispatch layer for conductor-protocol-v2.

This module makes zai-wrap the typed model gateway that conductor uses
for all LLM calls. Instead of conductor hardcoding API clients, it calls
model_dispatch() with a model name and prompt, and this module routes to
the correct backend.

Supported backends:
    grok / grok-3 / grok-3-mini    → Z.AI / xAI Grok API
    claude-*                         → Anthropic Claude API
    gpt-4* / gpt-4o*                 → OpenAI GPT-4 family
    deepseek-*                       → Deepseek API
    gemini-*                         → Google Gemini API

Usage:
    from model_dispatch import dispatch, ModelRequest, ModelResponse

    result = dispatch(ModelRequest(
        model="claude-3-5-sonnet-20241022",
        prompt="What is 2+2?",
        system="You are a helpful assistant.",
        max_tokens=256,
        run_id="conductor-run-001",
        source="conductor-protocol-v2",
    ))
    if result.success:
        print(result.content)
    else:
        print(f"Error: {result.error}")

All responses are written to brain.db via the brain bus (async)
so conductor has a full record of every model call.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ------------------------------------------------------------------ #
#  Request / Response types                                           #
# ------------------------------------------------------------------ #

@dataclass
class ModelRequest:
    model: str
    prompt: str
    system: str = ""
    max_tokens: int = 1024
    temperature: float = 0.7
    run_id: str = ""
    source: str = "zai-wrap"
    metadata: dict = field(default_factory=dict)
    # Internal: set by dispatch(), do not set manually
    _backend: str = field(default="", repr=False)


@dataclass
class ModelResponse:
    model: str
    content: str
    success: bool
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    backend: str = ""
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw: dict = field(default_factory=dict, repr=False)

    def to_brain_detail(self) -> str:
        """Serialize for brain.db learning_memory.detail field."""
        return json.dumps({
            "model": self.model,
            "backend": self.backend,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "success": self.success,
            "error": self.error[:200] if self.error else "",
        })


# ------------------------------------------------------------------ #
#  Backend routing                                                    #
# ------------------------------------------------------------------ #

def _detect_backend(model: str) -> str:
    m = model.lower()
    if m.startswith("grok"):
        return "grok"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"):
        return "openai"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("gemini"):
        return "gemini"
    # Default to grok (zai-wrap's native backend)
    return "grok"


def _call_grok(req: ModelRequest) -> ModelResponse:
    """Call Z.AI / xAI Grok API."""
    try:
        import openai  # Grok uses OpenAI-compatible API
        api_key = os.environ.get("GROK_API_KEY") or os.environ.get("XAI_API_KEY", "")
        base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")

        client = openai.OpenAI(api_key=api_key, base_url=base_url)
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        t0 = time.time()
        resp = client.chat.completions.create(
            model=req.model,
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        latency = (time.time() - t0) * 1000

        return ModelResponse(
            model=req.model,
            content=resp.choices[0].message.content or "",
            success=True,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            latency_ms=latency,
            backend="grok",
            run_id=req.run_id,
            raw={"id": resp.id},
        )
    except Exception as e:
        return ModelResponse(model=req.model, content="", success=False,
                             error=str(e), backend="grok", run_id=req.run_id)


def _call_anthropic(req: ModelRequest) -> ModelResponse:
    """Call Anthropic Claude API."""
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        client = anthropic.Anthropic(api_key=api_key)

        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            kwargs["system"] = req.system

        t0 = time.time()
        resp = client.messages.create(**kwargs)
        latency = (time.time() - t0) * 1000

        content = ""
        for block in resp.content:
            if hasattr(block, "text"):
                content += block.text

        return ModelResponse(
            model=req.model,
            content=content,
            success=True,
            input_tokens=resp.usage.input_tokens if resp.usage else 0,
            output_tokens=resp.usage.output_tokens if resp.usage else 0,
            latency_ms=latency,
            backend="anthropic",
            run_id=req.run_id,
            raw={"id": resp.id},
        )
    except Exception as e:
        return ModelResponse(model=req.model, content="", success=False,
                             error=str(e), backend="anthropic", run_id=req.run_id)


def _call_openai(req: ModelRequest) -> ModelResponse:
    """Call OpenAI GPT-4 family."""
    try:
        import openai
        api_key = os.environ.get("OPENAI_API_KEY", "")
        client = openai.OpenAI(api_key=api_key)
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        t0 = time.time()
        resp = client.chat.completions.create(
            model=req.model,
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        latency = (time.time() - t0) * 1000

        return ModelResponse(
            model=req.model,
            content=resp.choices[0].message.content or "",
            success=True,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            latency_ms=latency,
            backend="openai",
            run_id=req.run_id,
            raw={"id": resp.id},
        )
    except Exception as e:
        return ModelResponse(model=req.model, content="", success=False,
                             error=str(e), backend="openai", run_id=req.run_id)


def _call_deepseek(req: ModelRequest) -> ModelResponse:
    """Call Deepseek API (OpenAI-compatible)."""
    try:
        import openai
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        t0 = time.time()
        resp = client.chat.completions.create(
            model=req.model,
            messages=messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        latency = (time.time() - t0) * 1000

        return ModelResponse(
            model=req.model,
            content=resp.choices[0].message.content or "",
            success=True,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            latency_ms=latency,
            backend="deepseek",
            run_id=req.run_id,
        )
    except Exception as e:
        return ModelResponse(model=req.model, content="", success=False,
                             error=str(e), backend="deepseek", run_id=req.run_id)


def _call_gemini(req: ModelRequest) -> ModelResponse:
    """Call Google Gemini API."""
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=req.model,
            system_instruction=req.system or None,
        )
        t0 = time.time()
        resp = model.generate_content(req.prompt)
        latency = (time.time() - t0) * 1000

        return ModelResponse(
            model=req.model,
            content=resp.text or "",
            success=True,
            latency_ms=latency,
            backend="gemini",
            run_id=req.run_id,
        )
    except Exception as e:
        return ModelResponse(model=req.model, content="", success=False,
                             error=str(e), backend="gemini", run_id=req.run_id)


_BACKEND_DISPATCH = {
    "grok": _call_grok,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "deepseek": _call_deepseek,
    "gemini": _call_gemini,
}


# ------------------------------------------------------------------ #
#  Brain bus integration (async write after every call)              #
# ------------------------------------------------------------------ #

def _write_to_brain_bus(req: ModelRequest, resp: ModelResponse) -> None:
    """Publish the model call outcome to the brain bus (non-blocking)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "harmony-engine-protocol"))
        from brain_bus import BrainBusPublisher
        pub = BrainBusPublisher(source_repo="zai-wrap")
        pub.publish_learn(
            run_id=req.run_id or f"zai-{resp.model[:8]}",
            source="zai-wrap",
            category="model_call",
            event_type="GATE_PASSED" if resp.success else "GATE_FAILED",
            detail=resp.to_brain_detail(),
            outcome="pass" if resp.success else "fail",
        )
    except Exception:
        pass  # Brain bus failure must never block a model call


# ------------------------------------------------------------------ #
#  Main dispatch function                                             #
# ------------------------------------------------------------------ #

def dispatch(req: ModelRequest) -> ModelResponse:
    """Route a ModelRequest to the correct backend and return a ModelResponse.

    Always returns a ModelResponse, even on error (success=False).
    Never raises. Brain bus write happens async after the call.
    """
    backend = _detect_backend(req.model)
    req._backend = backend
    caller = _BACKEND_DISPATCH.get(backend, _call_grok)

    resp = caller(req)

    # Async brain write — non-blocking, failure is silently ignored
    _write_to_brain_bus(req, resp)

    return resp


def dispatch_with_fallback(
    req: ModelRequest,
    fallback_models: list[str] | None = None,
) -> ModelResponse:
    """Dispatch with automatic fallback on failure.

    Tries req.model first. On failure, tries each model in fallback_models.
    Returns the first successful response, or the last failure.
    """
    resp = dispatch(req)
    if resp.success:
        return resp

    fallbacks = fallback_models or ["gpt-4o", "claude-3-5-sonnet-20241022", "deepseek-chat"]
    for fallback_model in fallbacks:
        if fallback_model == req.model:
            continue
        fallback_req = ModelRequest(
            model=fallback_model,
            prompt=req.prompt,
            system=req.system,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            run_id=req.run_id,
            source=req.source,
            metadata={**req.metadata, "_fallback_from": req.model},
        )
        fallback_resp = dispatch(fallback_req)
        if fallback_resp.success:
            return fallback_resp

    return resp  # Return last failure


# ------------------------------------------------------------------ #
#  CLI for manual testing                                            #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="zai-wrap model dispatch")
    parser.add_argument("--model", default="grok-3-mini", help="Model to call")
    parser.add_argument("--prompt", default="Say hello in one sentence.")
    parser.add_argument("--system", default="")
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()

    req = ModelRequest(
        model=args.model,
        prompt=args.prompt,
        system=args.system,
        max_tokens=args.max_tokens,
        run_id="cli-test",
        source="cli",
    )
    print(f"Dispatching to: {_detect_backend(req.model)} ({req.model})")
    resp = dispatch(req)
    if resp.success:
        print(f"Response ({resp.latency_ms:.0f}ms, {resp.output_tokens} tokens):")
        print(resp.content)
    else:
        print(f"Error: {resp.error}")
