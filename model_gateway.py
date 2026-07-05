"""
model_gateway.py — Unified model calling layer for the DXv-3 stack.

This is GATEWAY-01: the single entry point for all LLM calls across the
entire repo ecosystem. conductor-protocol-v2 calls ModelGateway.call().
zai-wrap build-watch logs every routing decision. the-brain records every
call as a provenance event via the harmony bus.

Supported backends:
  z_ai        Z.AI / GLM-5.1 (primary for code tasks)
  claude      Anthropic Claude (primary for reasoning + creative)
  grok_api    xAI Grok API (primary for fast tasks — distinct from Grok Build)
  deepseek    Deepseek (code fallback + reasoning fallback)
  kimi        Moonshot AI / Kimi (fast + long-context fallback)
  ollama      Local Ollama (zero-cost, offline fallback)

Architecture:
  conductor-protocol-v2
       ↓ ModelGateway.call(prompt, model, task_type)
  model_gateway.py (this file)
       ↓ per-backend _call_<provider>() method
  external model API
       ↓ ModelResponse(text, model, usage, latency_ms, trace_id)
  conductor-protocol-v2 (provenance-gated response)
       ↓ build-watch event (dashboard)
       ↓ harmony bus publish (the-brain)

Environment variables:
  Z_AI_API_KEY            Z.AI API key
  Z_AI_BASE_URL           Z.AI API base (default: https://api.z.ai/api/paas/v4)
  ANTHROPIC_API_KEY       Anthropic API key
  XAI_API_KEY             xAI Grok API key
  DEEPSEEK_API_KEY        Deepseek API key
  KIMI_API_KEY            Moonshot AI (Kimi) API key
  OLLAMA_BASE_URL         Local Ollama base (default: http://localhost:11434)
  GATEWAY_DEFAULT_MODEL   Default model spec (e.g. 'claude/claude-sonnet-4-5')
  GATEWAY_MAX_RETRIES     Per-backend retries (default: 2)
  GATEWAY_TIMEOUT_S       HTTP timeout in seconds (default: 60)
  GATEWAY_EMIT_EVENTS     1 = emit build-watch events (default: 1)
  MATRIX_PATH             For harmony bus publish (optional)
  BUILD_WATCH_DIR         .build-watch dir for event emission (default: .build-watch)

Quick usage:
  from model_gateway import ModelGateway, ModelRouter

  # Simple call
  gw = ModelGateway()
  resp = gw.call("Explain async/await in Python", model="claude/claude-sonnet-4-5")
  print(resp.text)

  # Task-routed call (conductor pattern)
  router = ModelRouter()
  resp = router.route("Write a merge sort in Python", task_type="code")
  print(resp.text, resp.model, resp.latency_ms)

  # Usage summary for dashboard
  print(gw.usage_summary())
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_RETRIES = int(os.environ.get("GATEWAY_MAX_RETRIES", "2"))
TIMEOUT_S = float(os.environ.get("GATEWAY_TIMEOUT_S", "60"))
EMIT_EVENTS = os.environ.get("GATEWAY_EMIT_EVENTS", "1") != "0"
BUILD_WATCH_DIR = Path(os.environ.get("BUILD_WATCH_DIR", ".build-watch"))

# Backend API keys and URLs
_BACKENDS: dict[str, dict] = {
    "z_ai": {
        "key_env": "Z_AI_API_KEY",
        "base_url": os.environ.get("Z_AI_BASE_URL", "https://api.z.ai/api/paas/v4"),
        "default_model": "glm-5.1",
    },
    "claude": {
        "key_env": "ANTHROPIC_API_KEY",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-5",
    },
    "grok_api": {
        "key_env": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-mini-fast",
    },
    "deepseek": {
        "key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "kimi": {
        "key_env": "KIMI_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    "ollama": {
        "key_env": None,  # no key needed
        "base_url": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        "default_model": "llama3.2",
    },
}

# Task-type → ordered fallback chain: [(provider, model), ...]
_ROUTES: dict[str, list[tuple[str, str]]] = {
    "code": [
        ("z_ai", "glm-5.1"),
        ("deepseek", "deepseek-coder"),
        ("claude", "claude-sonnet-4-5"),
    ],
    "reasoning": [
        ("claude", "claude-opus-4-5"),
        ("deepseek", "deepseek-r1"),
        ("z_ai", "glm-5.1"),
    ],
    "fast": [
        ("grok_api", "grok-3-mini-fast"),
        ("kimi", "moonshot-v1-8k"),
        ("deepseek", "deepseek-chat"),
    ],
    "creative": [
        ("claude", "claude-sonnet-4-5"),
        ("grok_api", "grok-3"),
        ("deepseek", "deepseek-chat"),
    ],
    "vision": [
        ("claude", "claude-opus-4-5"),
        ("kimi", "moonshot-v1-128k"),
        ("grok_api", "grok-3"),
    ],
    "default": [
        ("claude", "claude-sonnet-4-5"),
        ("z_ai", "glm-5.1"),
        ("deepseek", "deepseek-chat"),
    ],
}


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class ModelResponse:
    """
    Canonical response object returned by ModelGateway.call().
    conductor-protocol-v2 uses this for provenance gating.
    """
    text: str
    model: str                          # e.g. 'claude/claude-sonnet-4-5'
    provider: str                       # e.g. 'claude'
    usage: dict[str, int] = field(default_factory=dict)   # prompt/completion tokens
    latency_ms: float = 0.0
    trace_id: str = ""
    fallback_used: bool = False         # True if primary provider failed
    error: str = ""                     # set if all providers failed

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


# ---------------------------------------------------------------------------
# Usage tracker (singleton per gateway instance)
# ---------------------------------------------------------------------------

class _UsageTracker:
    def __init__(self):
        self._data: dict[str, dict] = {}

    def record(self, provider: str, model: str, success: bool,
               prompt_tokens: int = 0, completion_tokens: int = 0,
               latency_ms: float = 0.0) -> None:
        key = f"{provider}/{model}"
        if key not in self._data:
            self._data[key] = {"calls": 0, "failures": 0,
                                "prompt_tokens": 0, "completion_tokens": 0,
                                "total_latency_ms": 0.0}
        d = self._data[key]
        d["calls"] += 1
        if not success:
            d["failures"] += 1
        d["prompt_tokens"] += prompt_tokens
        d["completion_tokens"] += completion_tokens
        d["total_latency_ms"] += latency_ms

    def summary(self) -> dict:
        out = {}
        for key, d in self._data.items():
            calls = d["calls"]
            out[key] = {
                "calls": calls,
                "failures": d["failures"],
                "success_rate": round((calls - d["failures"]) / max(calls, 1), 3),
                "prompt_tokens": d["prompt_tokens"],
                "completion_tokens": d["completion_tokens"],
                "avg_latency_ms": round(d["total_latency_ms"] / max(calls, 1), 1),
            }
        return out


# ---------------------------------------------------------------------------
# Build-watch event emitter
# ---------------------------------------------------------------------------

def _emit_build_event(msg: str, kind: str = "note", files: list[str] | None = None) -> None:
    """Append one JSON line to .build-watch/events.jsonl (same format build-watch expects)."""
    if not EMIT_EVENTS:
        return
    events_file = BUILD_WATCH_DIR / "events.jsonl"
    if not events_file.parent.exists():
        return  # build-watch not initialised — skip silently
    from datetime import datetime, timezone
    entry = {"ts": datetime.now(timezone.utc).isoformat(),
             "kind": kind, "msg": msg, "files": files or []}
    try:
        with events_file.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Harmony bus publisher (optional — integrates with the-brain)
# ---------------------------------------------------------------------------

def _try_publish_harmony(event_type: str, payload: dict, source: str = "ModelGateway") -> None:
    """Fire-and-forget: publish to harmony bus if MATRIX is on the path."""
    try:
        matrix_path = os.environ.get("MATRIX_PATH", "")
        if matrix_path and matrix_path not in sys.path:
            sys.path.insert(0, matrix_path)
        from harmony_publisher_base import sync_publish  # type: ignore
        sync_publish(event_type, payload, source=source)
    except (ImportError, Exception):
        pass  # harmony unavailable — not fatal


# ---------------------------------------------------------------------------
# Per-backend HTTP call helpers
# ---------------------------------------------------------------------------

def _openai_compat_call(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float = TIMEOUT_S,
    extra_headers: dict | None = None,
) -> tuple[str, dict]:
    """
    OpenAI-compatible chat completion call.
    Used by: Z.AI, Grok API, Deepseek, Kimi, Ollama (via /v1/chat/completions)
    Returns: (text, usage_dict)
    Raises: Exception on failure
    """
    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)

    body = {"model": model, "messages": messages}

    resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return text, usage


def _claude_call(
    api_key: str,
    model: str,
    messages: list[dict],
    system: str = "",
    timeout: float = TIMEOUT_S,
) -> tuple[str, dict]:
    """
    Anthropic Messages API call.
    Claude’s API is not OpenAI-compatible — it uses /messages, not /chat/completions.
    Returns: (text, usage_dict)
    Raises: Exception on failure
    """
    import httpx

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": 8192,
        "messages": messages,
    }
    if system:
        body["system"] = system

    resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    text = data["content"][0]["text"]
    usage = data.get("usage", {})
    return text, usage


# ---------------------------------------------------------------------------
# ModelGateway
# ---------------------------------------------------------------------------

class ModelGateway:
    """
    Unified model calling layer.

    Call any backend through a single interface:
      resp = gw.call(prompt, model="claude/claude-sonnet-4-5")
      resp = gw.call(prompt, model="z_ai/glm-5.1")
      resp = gw.call(prompt, model="deepseek/deepseek-r1")

    model format:  '<provider>/<model_name>'
    If provider is omitted, GATEWAY_DEFAULT_MODEL env var is used,
    falling back to 'claude/claude-sonnet-4-5'.
    """

    def __init__(self, default_model: str | None = None):
        self._default_model = (
            default_model
            or os.environ.get("GATEWAY_DEFAULT_MODEL", "claude/claude-sonnet-4-5")
        )
        self._tracker = _UsageTracker()

    @classmethod
    def from_env(cls) -> "ModelGateway":
        """Factory: reads GATEWAY_DEFAULT_MODEL from env."""
        return cls()

    def call(
        self,
        prompt: str,
        model: str | None = None,
        system: str = "",
        messages: list[dict] | None = None,
        trace_id: str | None = None,
        task_type: str | None = None,
    ) -> ModelResponse:
        """
        Call a model and return a ModelResponse.

        Args:
            prompt:     User message (string). Ignored if messages is provided.
            model:      '<provider>/<model_name>' or just '<provider>'.
                        If omitted, uses self._default_model.
            system:     System prompt (Claude only; for others prepended as system message).
            messages:   Raw messages list (OpenAI format). Overrides prompt if provided.
            trace_id:   Provenance trace ID (auto-generated if omitted).
            task_type:  If provided, delegates to ModelRouter.route() instead.
        """
        if task_type is not None:
            router = ModelRouter(gateway=self)
            return router.route(prompt, task_type=task_type, system=system,
                                messages=messages, trace_id=trace_id)

        tid = trace_id or f"gw-{uuid.uuid4().hex[:10]}"
        model_spec = model or self._default_model
        provider, model_name = self._parse_model_spec(model_spec)

        _emit_build_event(
            f"[gateway] Calling {provider}/{model_name} — trace={tid}",
            kind="note",
        )

        resp = self._call_with_retry(provider, model_name, prompt, system,
                                      messages, tid)

        # Harmony bus — fire and forget
        _try_publish_harmony("model_call", {
            "provider": provider,
            "model": model_name,
            "trace_id": tid,
            "success": resp.ok,
            "latency_ms": resp.latency_ms,
            "prompt_tokens": resp.usage.get("input_tokens",
                             resp.usage.get("prompt_tokens", 0)),
        })
        return resp

    def _parse_model_spec(self, spec: str) -> tuple[str, str]:
        """Parse 'claude/claude-sonnet-4-5' → ('claude', 'claude-sonnet-4-5')."""
        if "/" in spec:
            parts = spec.split("/", 1)
            return parts[0], parts[1]
        # spec is just a provider name — use its default model
        if spec in _BACKENDS:
            return spec, _BACKENDS[spec]["default_model"]
        # Treat as a model name for the default provider
        default_provider = self._default_model.split("/")[0]
        return default_provider, spec

    def _call_with_retry(
        self,
        provider: str,
        model_name: str,
        prompt: str,
        system: str,
        messages: list[dict] | None,
        trace_id: str,
    ) -> ModelResponse:
        """Call provider with MAX_RETRIES attempts and exponential backoff."""
        msgs = messages or [{"role": "user", "content": prompt}]
        delay = 1.0
        last_exc: Exception | None = None

        for attempt in range(max(MAX_RETRIES, 1)):
            start = time.monotonic()
            try:
                text, usage = self._dispatch(provider, model_name, msgs, system)
                latency = (time.monotonic() - start) * 1000
                self._tracker.record(provider, model_name, True,
                                     usage.get("prompt_tokens",
                                     usage.get("input_tokens", 0)),
                                     usage.get("completion_tokens",
                                     usage.get("output_tokens", 0)),
                                     latency)
                _emit_build_event(
                    f"[gateway] ✓ {provider}/{model_name} in {latency:.0f}ms",
                    kind="note",
                )
                return ModelResponse(
                    text=text,
                    model=f"{provider}/{model_name}",
                    provider=provider,
                    usage=usage,
                    latency_ms=round(latency, 1),
                    trace_id=trace_id,
                )
            except Exception as exc:
                last_exc = exc
                latency = (time.monotonic() - start) * 1000
                self._tracker.record(provider, model_name, False,
                                     latency_ms=latency)
                log.warning("[gateway] %s/%s attempt %d failed: %s",
                             provider, model_name, attempt + 1, exc)
                _emit_build_event(
                    f"[gateway] ✗ {provider}/{model_name} attempt {attempt+1}: {exc}",
                    kind="note",
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay = min(delay * 2, 16.0)

        return ModelResponse(
            text="",
            model=f"{provider}/{model_name}",
            provider=provider,
            latency_ms=0.0,
            trace_id=trace_id,
            error=str(last_exc),
        )

    def _dispatch(self, provider: str, model_name: str,
                  messages: list[dict], system: str) -> tuple[str, dict]:
        """Route to the correct backend call function."""
        cfg = _BACKENDS.get(provider)
        if cfg is None:
            raise ValueError(f"Unknown provider: {provider}")

        key_env = cfg["key_env"]
        api_key = os.environ.get(key_env, "") if key_env else ""

        if provider == "claude":
            return _claude_call(api_key, model_name, messages, system, TIMEOUT_S)

        if provider == "ollama":
            # Ollama uses OpenAI-compat /v1/ endpoint
            return _openai_compat_call(
                cfg["base_url"] + "/v1", api_key, model_name, messages, TIMEOUT_S
            )

        # All other providers: OpenAI-compatible
        extra: dict | None = None
        if provider == "z_ai":
            # Z.AI coding endpoint needs system injected as first message
            if system:
                messages = [{"role": "system", "content": system}] + [
                    m for m in messages if m.get("role") != "system"
                ]
        elif system:
            messages = [{"role": "system", "content": system}] + [
                m for m in messages if m.get("role") != "system"
            ]

        return _openai_compat_call(
            cfg["base_url"], api_key, model_name, messages, TIMEOUT_S, extra
        )

    def usage_summary(self) -> dict:
        """Return per-model call/failure/token/latency stats."""
        return self._tracker.summary()


# ---------------------------------------------------------------------------
# ModelRouter — task-type based routing with fallback chains
# ---------------------------------------------------------------------------

class ModelRouter:
    """
    Routes by task_type to the preferred model, falling through the
    fallback chain if the primary fails.

    Used by conductor-protocol-v2 to pick models based on task semantics
    rather than hardcoding a provider per task.

      router = ModelRouter()
      resp = router.route(prompt, task_type="code")
      resp = router.route(prompt, task_type="reasoning")
    """

    def __init__(self, gateway: ModelGateway | None = None,
                 routes: dict | None = None):
        self._gw = gateway or ModelGateway()
        self._routes = routes or _ROUTES

    def route(
        self,
        prompt: str,
        task_type: str = "default",
        system: str = "",
        messages: list[dict] | None = None,
        trace_id: str | None = None,
    ) -> ModelResponse:
        """
        Try each (provider, model) in the task_type fallback chain.
        Returns the first successful response, or a failed ModelResponse
        if the entire chain is exhausted.
        """
        tid = trace_id or f"rt-{uuid.uuid4().hex[:10]}"
        chain = self._routes.get(task_type, self._routes["default"])

        _emit_build_event(
            f"[router] task_type={task_type} chain={[f'{p}/{m}' for p,m in chain]}",
            kind="plan",
        )

        last_resp: ModelResponse | None = None
        for idx, (provider, model_name) in enumerate(chain):
            resp = self._gw._call_with_retry(
                provider, model_name, prompt, system, messages, tid
            )
            if resp.ok:
                resp.fallback_used = idx > 0
                if idx > 0:
                    _emit_build_event(
                        f"[router] Fallback used: {provider}/{model_name} "
                        f"(primary chain position {idx})",
                        kind="note",
                    )
                return resp
            last_resp = resp
            log.warning("[router] %s/%s failed for task_type=%s, trying next",
                         provider, model_name, task_type)

        # Entire chain exhausted
        _emit_build_event(
            f"[router] All providers failed for task_type={task_type}",
            kind="note",
        )
        return last_resp or ModelResponse(
            text="", model="", provider="", trace_id=tid,
            error=f"All providers failed for task_type={task_type}",
        )

    def available_providers(self) -> list[str]:
        """Return list of providers that have API keys configured."""
        available = []
        for provider, cfg in _BACKENDS.items():
            key_env = cfg.get("key_env")
            if key_env is None or os.environ.get(key_env):
                available.append(provider)
        return available


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ModelGateway quick test")
    parser.add_argument("prompt", nargs="?", default="Say hello in one sentence.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--task-type", default=None)
    parser.add_argument("--usage", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    gw = ModelGateway()
    router = ModelRouter(gateway=gw)

    if args.task_type:
        resp = router.route(args.prompt, task_type=args.task_type)
    else:
        resp = gw.call(args.prompt, model=args.model)

    print(f"\n=== ModelResponse ===")
    print(f"Model:      {resp.model}")
    print(f"Latency:    {resp.latency_ms:.1f}ms")
    print(f"Fallback:   {resp.fallback_used}")
    print(f"Text:\n{resp.text}")
    if args.usage:
        print(f"\n=== Usage ===")
        import pprint; pprint.pprint(gw.usage_summary())
