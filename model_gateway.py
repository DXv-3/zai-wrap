"""
model_gateway.py  —  zai-wrap canonical ModelRouter
----------------------------------------------------
This is the stable public API that conductor-protocol-v2's
ConductorModelGateway imports via:

    from model_gateway import ModelRouter

It wraps every provider available in zai-wrap (Grok/Z.AI, Claude,
Deepseek, OpenAI) behind a single interface with two call patterns:

  router.route(prompt, task_type, ...)   # auto-select model by task
  router.call(prompt, model, ...)        # call a specific model directly

Task-type → provider routing table (matches ConductorModelGateway.TASK_DEFAULTS):
  code       → deepseek/deepseek-coder     (fallback: claude/claude-sonnet-4-5)
  reasoning  → claude/claude-opus-4-5      (fallback: deepseek/deepseek-r1)
  fast       → deepseek/deepseek-chat      (fallback: claude/claude-haiku-4-5)
  creative   → claude/claude-sonnet-4-5    (fallback: deepseek/deepseek-chat)
  vision     → claude/claude-opus-4-5      (fallback: grok_api/grok-3)
  routing    → claude/claude-haiku-4-5     (fallback: deepseek/deepseek-chat)
  audit      → claude/claude-sonnet-4-5    (fallback: deepseek/deepseek-r1)
  forensics  → claude/claude-opus-4-5      (fallback: deepseek/deepseek-r1)
  grok       → grok_api/grok-3             (Z.AI / X.AI native)

All calls publish a model_call event to the harmony bus (fire-and-forget).
All calls are logged to ~/.zai-wrap/model_calls.jsonl for local audit.

Environment variables:
  ANTHROPIC_API_KEY   — Claude provider
  DEEPSEEK_API_KEY    — Deepseek provider
  XAI_API_KEY         — Grok/Z.AI provider  (also read by bw.grok)
  OPENAI_API_KEY      — OpenAI provider (fallback)
  ZAI_WRAP_HARMONY    — "1" to enable harmony bus publish (default: "1")
  HARMONY_POLL_FILE   — path for poll-file fallback (default: /tmp/harmony_events.jsonl)
"""

import json
import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_LOG_DIR = Path(os.getenv("ZAI_WRAP_LOG_DIR", Path.home() / ".zai-wrap"))
_LOG_FILE = _LOG_DIR / "model_calls.jsonl"
_HARMONY_ENABLED = os.getenv("ZAI_WRAP_HARMONY", "1") == "1"


# ---------------------------------------------------------------------------
# Response dataclass  (identical shape to ConductorModelResponse for easy exchange)
# ---------------------------------------------------------------------------

@dataclass
class ModelResponse:
    content: str
    model: str
    task_type: str = ""
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = ""
    tokens_used: int = 0


# ---------------------------------------------------------------------------
# Provider backends
# ---------------------------------------------------------------------------

class _GrokProvider:
    """Wraps bw.grok (the existing zai-wrap Grok/Z.AI backend)."""
    name = "grok_api"

    def __init__(self):
        self._available = False
        try:
            # bw/ lives next to model_gateway.py inside the zai-wrap repo
            _scripts = Path(__file__).parent / "scripts"
            sys.path.insert(0, str(_scripts))
            from bw.grok import GrokClient  # type: ignore
            self._client = GrokClient()
            self._available = True
            logger.debug("_GrokProvider: bw.grok.GrokClient loaded")
        except Exception:
            # Try the shim path
            try:
                from bw.grok import chat as _chat  # type: ignore
                self._chat_fn = _chat
                self._available = True
                logger.debug("_GrokProvider: bw.grok.chat loaded")
            except Exception as exc:
                logger.warning("_GrokProvider: bw.grok unavailable (%s) — will use XAI REST directly", exc)

    def call(self, prompt: str, model: str = "grok-3",
             system: Optional[str] = None, max_tokens: int = 4096,
             temperature: float = 0.7) -> str:
        # If bw.grok client available, use it
        if self._available and hasattr(self, "_client"):
            return self._client.chat(
                prompt, model=model.replace("grok_api/", ""),
                system=system, max_tokens=max_tokens, temperature=temperature
            )
        if self._available and hasattr(self, "_chat_fn"):
            kwargs = {"prompt": prompt, "model": model.replace("grok_api/", ""),
                      "max_tokens": max_tokens, "temperature": temperature}
            if system:
                kwargs["system"] = system
            return self._chat_fn(**kwargs)
        # Direct XAI REST fallback
        return self._direct_xai(prompt, model.replace("grok_api/", ""),
                                system, max_tokens, temperature)

    def _direct_xai(self, prompt: str, model: str, system: Optional[str],
                    max_tokens: int, temperature: float) -> str:
        import urllib.request
        api_key = os.getenv("XAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("XAI_API_KEY not set")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


class _ClaudeProvider:
    name = "claude"

    def call(self, prompt: str, model: str = "claude-sonnet-4-5",
             system: Optional[str] = None, max_tokens: int = 4096,
             temperature: float = 0.3) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        clean_model = model.replace("claude/", "")
        # Map short names to full Anthropic model IDs
        MODEL_MAP = {
            "claude-opus-4-5":   "claude-opus-4-5-20251101",
            "claude-sonnet-4-5": "claude-sonnet-4-5-20251101",
            "claude-haiku-4-5":  "claude-haiku-4-5-20251101",
        }
        full_model = MODEL_MAP.get(clean_model, clean_model)
        kwargs: Dict[str, Any] = {
            "model": full_model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        return msg.content[0].text


class _DeepseekProvider:
    name = "deepseek"

    def call(self, prompt: str, model: str = "deepseek-chat",
             system: Optional[str] = None, max_tokens: int = 4096,
             temperature: float = 0.3) -> str:
        # Deepseek uses OpenAI-compatible API
        import urllib.request
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        clean_model = model.replace("deepseek/", "")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({
            "model": clean_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]


class _OpenAIProvider:
    name = "openai"

    def call(self, prompt: str, model: str = "gpt-4o",
             system: Optional[str] = None, max_tokens: int = 4096,
             temperature: float = 0.3) -> str:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        clean_model = model.replace("openai/", "")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=clean_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """
    The single import that conductor-protocol-v2 needs:

        from model_gateway import ModelRouter
        router = ModelRouter()
        resp = router.route(prompt, task_type="code")
        resp = router.call(prompt, model="claude/claude-sonnet-4-5")
    """

    # task_type → (primary_model_string, fallback_model_string)
    TASK_DEFAULTS: Dict[str, Tuple[str, str]] = {
        "code":      ("deepseek/deepseek-coder",    "claude/claude-sonnet-4-5"),
        "reasoning": ("claude/claude-opus-4-5",      "deepseek/deepseek-r1"),
        "fast":      ("deepseek/deepseek-chat",       "claude/claude-haiku-4-5"),
        "creative":  ("claude/claude-sonnet-4-5",     "deepseek/deepseek-chat"),
        "vision":    ("claude/claude-opus-4-5",       "grok_api/grok-3"),
        "routing":   ("claude/claude-haiku-4-5",      "deepseek/deepseek-chat"),
        "audit":     ("claude/claude-sonnet-4-5",     "deepseek/deepseek-r1"),
        "forensics": ("claude/claude-opus-4-5",       "deepseek/deepseek-r1"),
        "grok":      ("grok_api/grok-3",              "claude/claude-sonnet-4-5"),
    }

    # model prefix → provider class
    PROVIDER_MAP = {
        "grok_api":  _GrokProvider,
        "claude":    _ClaudeProvider,
        "deepseek":  _DeepseekProvider,
        "openai":    _OpenAIProvider,
    }

    def __init__(self):
        self._providers: Dict[str, Any] = {}
        self._usage: Dict[str, Dict] = {}
        _LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _get_provider(self, prefix: str) -> Any:
        if prefix not in self._providers:
            cls = self.PROVIDER_MAP.get(prefix)
            if cls is None:
                raise ValueError(f"Unknown provider prefix: '{prefix}'")
            self._providers[prefix] = cls()
        return self._providers[prefix]

    def _parse_model(self, model_str: str) -> Tuple[str, str]:
        """'claude/claude-sonnet-4-5' → ('claude', 'claude-sonnet-4-5')"""
        if "/" in model_str:
            prefix, name = model_str.split("/", 1)
        else:
            # bare name — guess provider from known prefixes
            if model_str.startswith("grok"):
                prefix, name = "grok_api", model_str
            elif model_str.startswith("claude"):
                prefix, name = "claude", model_str
            elif model_str.startswith("deepseek"):
                prefix, name = "deepseek", model_str
            else:
                prefix, name = "openai", model_str
        return prefix, name

    def route(
        self,
        prompt: str,
        task_type: str = "reasoning",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ModelResponse:
        """Auto-select model by task_type and call it, with fallback."""
        primary, fallback = self.TASK_DEFAULTS.get(
            task_type, ("claude/claude-sonnet-4-5", "deepseek/deepseek-chat")
        )
        for model_str in (primary, fallback):
            try:
                return self.call(
                    prompt, model=model_str, task_type=task_type,
                    system=system, max_tokens=max_tokens, temperature=temperature,
                )
            except Exception as exc:
                logger.warning("ModelRouter.route: %s failed (%s), trying fallback", model_str, exc)
        # All failed
        return ModelResponse(
            content=f"[ModelRouter: all providers failed for task_type={task_type}]",
            model=primary, task_type=task_type, success=False,
            error="all providers failed",
        )

    def call(
        self,
        prompt: str,
        model: str = "claude/claude-sonnet-4-5",
        task_type: str = "",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ModelResponse:
        """Call a specific model directly."""
        start = time.perf_counter()
        call_id = str(uuid.uuid4())
        prefix, model_name = self._parse_model(model)
        error = None
        content = ""
        success = False

        try:
            provider = self._get_provider(prefix)
            content = provider.call(
                prompt, model=model_name, system=system,
                max_tokens=max_tokens, temperature=temperature,
            )
            success = True
        except Exception as exc:
            error = str(exc)
            content = f"[ModelRouter error ({model}): {exc}]"
            logger.error("ModelRouter.call failed for model=%s: %s", model, exc)

        latency_ms = (time.perf_counter() - start) * 1000
        resp = ModelResponse(
            content=content, model=model, task_type=task_type,
            latency_ms=latency_ms, success=success, error=error,
            call_id=call_id, provider=prefix,
        )

        self._log_call(resp)
        self._publish_harmony(resp)
        self._update_usage(resp)
        return resp

    def usage_summary(self) -> Dict[str, Dict]:
        """Return per-model usage stats."""
        summary = {}
        for model, stats in self._usage.items():
            calls = stats.get("calls", 0)
            summary[model] = {
                "calls": calls,
                "failures": stats.get("failures", 0),
                "avg_latency_ms": round(stats.get("total_latency_ms", 0) / max(calls, 1), 1),
                "success_rate": round(
                    (calls - stats.get("failures", 0)) / max(calls, 1) * 100, 1
                ),
            }
        return summary

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _log_call(self, resp: ModelResponse):
        try:
            with _LOG_FILE.open("a") as f:
                f.write(json.dumps({
                    "call_id": resp.call_id,
                    "model": resp.model,
                    "provider": resp.provider,
                    "task_type": resp.task_type,
                    "latency_ms": round(resp.latency_ms, 1),
                    "success": resp.success,
                    "error": resp.error,
                    "timestamp": resp.timestamp,
                }) + "\n")
        except Exception as exc:
            logger.debug("ModelRouter._log_call: %s", exc)

    def _publish_harmony(self, resp: ModelResponse):
        if not _HARMONY_ENABLED:
            return
        import threading
        def _pub():
            try:
                poll_file = Path(os.getenv("HARMONY_POLL_FILE", "/tmp/harmony_events.jsonl"))
                event = json.dumps({
                    "event_type": "model_call",
                    "payload": {
                        "call_id": resp.call_id,
                        "model": resp.model,
                        "provider": resp.provider,
                        "task_type": resp.task_type,
                        "latency_ms": round(resp.latency_ms, 1),
                        "success": resp.success,
                        "timestamp": resp.timestamp,
                        "source_repo": "zai-wrap",
                    },
                })
                # Try harmony bus first
                try:
                    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
                    from harmony_publisher_base import HarmonyPublisher  # type: ignore
                    HarmonyPublisher().publish("model_call", json.loads(event)["payload"])
                    return
                except Exception:
                    pass
                # Poll-file fallback
                with poll_file.open("a") as f:
                    f.write(event + "\n")
            except Exception as exc:
                logger.debug("ModelRouter._publish_harmony: %s", exc)
        threading.Thread(target=_pub, daemon=True).start()

    def _update_usage(self, resp: ModelResponse):
        stats = self._usage.setdefault(resp.model, {
            "calls": 0, "failures": 0, "total_latency_ms": 0.0
        })
        stats["calls"] += 1
        stats["total_latency_ms"] += resp.latency_ms
        if not resp.success:
            stats["failures"] += 1


# ---------------------------------------------------------------------------
# Module-level singleton + convenience functions
# ---------------------------------------------------------------------------

_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def route(prompt: str, task_type: str = "reasoning", **kwargs) -> ModelResponse:
    """Module-level shortcut: zai_wrap.model_gateway.route(prompt, task_type)"""
    return get_router().route(prompt, task_type=task_type, **kwargs)


def call(prompt: str, model: str = "claude/claude-sonnet-4-5", **kwargs) -> ModelResponse:
    """Module-level shortcut: zai_wrap.model_gateway.call(prompt, model)"""
    return get_router().call(prompt, model=model, **kwargs)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="ModelRouter CLI smoke test")
    parser.add_argument("--task", default="fast", help="task_type to test")
    parser.add_argument("--prompt", default="Say 'zai-wrap online' in exactly those words.",
                        help="Test prompt")
    parser.add_argument("--model", default="", help="Specific model (optional)")
    parser.add_argument("--list", action="store_true", help="List all task types and models")
    args = parser.parse_args()

    router = ModelRouter()

    if args.list:
        print("Task type → primary model mapping:")
        for task, (primary, fallback) in router.TASK_DEFAULTS.items():
            print(f"  {task:12s} → {primary:35s} (fallback: {fallback})")
        import sys; sys.exit(0)

    print(f"Testing ModelRouter — task={args.task}")
    if args.model:
        resp = router.call(args.prompt, model=args.model)
    else:
        resp = router.route(args.prompt, task_type=args.task)

    print(f"Model:      {resp.model}")
    print(f"Provider:   {resp.provider}")
    print(f"Latency:    {resp.latency_ms:.0f}ms")
    print(f"Success:    {resp.success}")
    print(f"Response:   {resp.content[:200]}")
    print(f"Call log:   {_LOG_FILE}")
