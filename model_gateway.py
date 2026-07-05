"""
model_gateway.py  —  zai-wrap ModelRouter
==========================================
The canonical multi-model gateway for the entire DXv-3 stack.

Used by:
  - conductor-protocol-v2  (via ConductorModelGateway)
  - self-improving-system-builder  (via skill_brain_sync fallback)
  - safari-agent-stack  (importable on macOS via ZAI_WRAP_PATH)
  - vinny-stack dashboard  (usage_summary for live metrics)
  - any future repo that needs a model call

Design principles:
  1. Single import, single call site  — `from model_gateway import ModelRouter`
  2. Provider-agnostic routing         — callers specify task_type, not model
  3. Automatic fallback chain          — primary fails → fallback → next provider
  4. No credentials in code            — all keys read from env vars
  5. Every call is tracked             — latency, tokens, success logged locally
  6. Harmony bus publish               — optional, fire-and-forget

Quick start:
    from model_gateway import ModelRouter
    r = ModelRouter()
    # Route by task type (recommended)
    resp = r.route("Explain RLHF in one paragraph", task_type="reasoning")
    print(resp.content)
    # Call a specific model directly
    resp = r.call("Write a bubble sort in Python", model="deepseek/deepseek-coder")
    print(resp.content, resp.model, resp.latency_ms)
    # One-liner
    from model_gateway import quick_call
    text = quick_call("Summarise this text", task_type="fast")

Environment variables (set in ~/.zshrc or .env):
    ANTHROPIC_API_KEY       Claude models
    DEEPSEEK_API_KEY        DeepSeek models
    OPENAI_API_KEY          GPT-4o / o3
    XAI_API_KEY             Grok (X.AI SDK path)
    KIMI_API_KEY            Moonshot / Kimi models
    BUILD_WATCH_PORT        Port for Grok build-watch bridge (default: 8790)
    ZAI_WRAP_PATH           Path to this repo (for external importers)
    HARMONY_POLL_FILE       JSONL file for harmony bus fallback
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from providers.anthropic_provider  import AnthropicProvider
from providers.deepseek_provider   import DeepSeekProvider
from providers.grok_provider       import GrokProvider
from providers.kimi_provider       import KimiProvider
from providers.openai_provider     import OpenAIProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response dataclass  (same shape as ConductorModelResponse for drop-in compat)
# ---------------------------------------------------------------------------

@dataclass
class ModelResponse:
    content: str
    model: str
    provider: str
    task_type: str
    latency_ms: float
    success: bool
    call_id: str           = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str         = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tokens_used: int       = 0
    error: Optional[str]   = None
    fallback_used: bool    = False


# ---------------------------------------------------------------------------
# Routing table
# ---------------------------------------------------------------------------

# task_type → [(provider_key, model_id), ...]   ordered: primary first, fallbacks after
ROUTE_TABLE: Dict[str, List[Tuple[str, str]]] = {
    "code": [
        ("deepseek",  "deepseek-coder"),
        ("anthropic", "claude-sonnet-4-5"),
        ("openai",    "gpt-4o"),
    ],
    "reasoning": [
        ("anthropic", "claude-opus-4-5"),
        ("deepseek",  "deepseek-r1"),
        ("openai",    "o3-mini"),
    ],
    "fast": [
        ("deepseek",  "deepseek-chat"),
        ("anthropic", "claude-haiku-4-5"),
        ("openai",    "gpt-4o-mini"),
    ],
    "creative": [
        ("anthropic", "claude-sonnet-4-5"),
        ("deepseek",  "deepseek-chat"),
        ("kimi",      "moonshot-v1-8k"),
    ],
    "vision": [
        ("anthropic", "claude-opus-4-5"),
        ("openai",    "gpt-4o"),
        ("grok",      "grok-3"),
    ],
    "routing": [
        ("anthropic", "claude-haiku-4-5"),
        ("deepseek",  "deepseek-chat"),
    ],
    "audit": [
        ("anthropic", "claude-sonnet-4-5"),
        ("deepseek",  "deepseek-r1"),
    ],
    "forensics": [
        ("anthropic", "claude-opus-4-5"),
        ("deepseek",  "deepseek-r1"),
    ],
    "long_context": [
        ("kimi",      "moonshot-v1-128k"),
        ("anthropic", "claude-opus-4-5"),
        ("openai",    "gpt-4o"),
    ],
    "web_search": [
        ("grok",      "grok-3"),
        ("openai",    "gpt-4o"),
    ],
}

# provider_key → class
PROVIDER_REGISTRY = {
    "anthropic": AnthropicProvider,
    "deepseek":  DeepSeekProvider,
    "grok":      GrokProvider,
    "kimi":      KimiProvider,
    "openai":    OpenAIProvider,
}


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """
    Multi-model gateway with automatic fallback, usage tracking,
    and harmony bus publish.

    Thread-safe: providers are stateless; usage dict uses a lock.
    """

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._providers: Dict[str, Any] = {}
        self._usage: Dict[str, Dict] = {}
        self._harmony_pub = None
        self._init_providers()
        self._init_harmony()

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def _init_providers(self):
        for key, cls in PROVIDER_REGISTRY.items():
            try:
                p = cls()
                if p.available():
                    self._providers[key] = p
                    logger.info("ModelRouter: provider '%s' ready", key)
                else:
                    logger.debug("ModelRouter: provider '%s' skipped (no API key)", key)
            except Exception as exc:
                logger.warning("ModelRouter: provider '%s' init failed: %s", key, exc)

    def _init_harmony(self):
        try:
            import sys
            matrix_path = os.getenv("MATRIX_PATH", "../MATRIX")
            sys.path.insert(0, matrix_path)
            from harmony_publisher_base import HarmonyPublisher  # type: ignore
            self._harmony_pub = HarmonyPublisher()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        prompt: str,
        task_type: str = "reasoning",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ModelResponse:
        """
        Route a prompt to the best available provider for the task type.
        Tries providers in ROUTE_TABLE order; returns the first success.
        """
        chain = ROUTE_TABLE.get(task_type, ROUTE_TABLE["reasoning"])
        last_error: Optional[str] = None
        fallback_used = False

        for idx, (provider_key, model_id) in enumerate(chain):
            provider = self._providers.get(provider_key)
            if provider is None:
                logger.debug("ModelRouter: provider '%s' not available, skipping", provider_key)
                continue

            start = time.perf_counter()
            try:
                content, tokens = provider.complete(
                    prompt=prompt,
                    model=model_id,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                latency_ms = (time.perf_counter() - start) * 1000
                resp = ModelResponse(
                    content=content,
                    model=f"{provider_key}/{model_id}",
                    provider=provider_key,
                    task_type=task_type,
                    latency_ms=latency_ms,
                    success=True,
                    tokens_used=tokens,
                    fallback_used=(idx > 0),
                )
                self._record(resp)
                return resp

            except Exception as exc:
                last_error = str(exc)
                latency_ms = (time.perf_counter() - start) * 1000
                logger.warning(
                    "ModelRouter: %s/%s failed (%.0fms): %s — trying next",
                    provider_key, model_id, latency_ms, exc
                )
                fallback_used = True

        # All providers failed
        resp = ModelResponse(
            content=f"[ModelRouter: all providers failed for task_type='{task_type}'. Last error: {last_error}]",
            model="none",
            provider="none",
            task_type=task_type,
            latency_ms=0.0,
            success=False,
            error=last_error,
            fallback_used=fallback_used,
        )
        self._record(resp)
        return resp

    def call(
        self,
        prompt: str,
        model: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ModelResponse:
        """
        Call a specific model directly by "provider/model_id" string.
        Falls back to route(task_type='reasoning') if provider not available.
        """
        if "/" not in model:
            logger.warning("ModelRouter.call: model '%s' has no provider prefix; routing as 'reasoning'", model)
            return self.route(prompt, task_type="reasoning", system=system,
                              max_tokens=max_tokens, temperature=temperature)

        provider_key, model_id = model.split("/", 1)
        provider = self._providers.get(provider_key)

        if provider is None:
            logger.warning(
                "ModelRouter.call: provider '%s' not available; routing as 'reasoning'", provider_key
            )
            return self.route(prompt, task_type="reasoning", system=system,
                              max_tokens=max_tokens, temperature=temperature)

        start = time.perf_counter()
        try:
            content, tokens = provider.complete(
                prompt=prompt, model=model_id, system=system,
                max_tokens=max_tokens, temperature=temperature,
            )
            latency_ms = (time.perf_counter() - start) * 1000
            resp = ModelResponse(
                content=content,
                model=model,
                provider=provider_key,
                task_type="direct",
                latency_ms=latency_ms,
                success=True,
                tokens_used=tokens,
            )
            self._record(resp)
            return resp
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            logger.warning("ModelRouter.call: %s failed: %s", model, exc)
            resp = ModelResponse(
                content=f"[ModelRouter: {model} failed: {exc}]",
                model=model,
                provider=provider_key,
                task_type="direct",
                latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )
            self._record(resp)
            return resp

    def available_providers(self) -> List[str]:
        return list(self._providers.keys())

    def usage_summary(self) -> Dict[str, Any]:
        with self._lock:
            out = {}
            for model, stats in self._usage.items():
                calls = stats.get("calls", 0)
                out[model] = {
                    "calls": calls,
                    "failures": stats.get("failures", 0),
                    "avg_latency_ms": round(stats.get("total_latency_ms", 0) / max(calls, 1), 1),
                    "success_rate": round((calls - stats.get("failures", 0)) / max(calls, 1) * 100, 1),
                    "total_tokens": stats.get("total_tokens", 0),
                }
            return out

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _record(self, resp: ModelResponse):
        with self._lock:
            stats = self._usage.setdefault(resp.model, {
                "calls": 0, "failures": 0, "total_latency_ms": 0.0, "total_tokens": 0
            })
            stats["calls"] += 1
            stats["total_latency_ms"] += resp.latency_ms
            stats["total_tokens"] += resp.tokens_used
            if not resp.success:
                stats["failures"] += 1
        self._publish(resp)

    def _publish(self, resp: ModelResponse):
        if not self._harmony_pub:
            return
        try:
            self._harmony_pub.publish("model_call", {
                "call_id": resp.call_id,
                "model": resp.model,
                "provider": resp.provider,
                "task_type": resp.task_type,
                "latency_ms": resp.latency_ms,
                "success": resp.success,
                "tokens_used": resp.tokens_used,
                "fallback_used": resp.fallback_used,
                "timestamp": resp.timestamp,
                "source_repo": "zai-wrap",
            })
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton + one-liner
# ---------------------------------------------------------------------------

_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def quick_call(
    prompt: str,
    task_type: str = "reasoning",
    system: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> str:
    """Minimal one-liner: returns content string only."""
    return get_router().route(
        prompt=prompt, task_type=task_type, system=system,
        max_tokens=max_tokens, temperature=temperature,
    ).content
