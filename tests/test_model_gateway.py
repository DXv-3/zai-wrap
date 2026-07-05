"""
tests/test_model_gateway.py — 12 tests for the unified model gateway.

All tests use mocked httpx — no real API calls.
"""
from __future__ import annotations
import json
import sys
import types as _types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub httpx before import (so tests don’t need it installed)
httpx_stub = _types.ModuleType("httpx")

class _FakeResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")
    def json(self):
        return self._body

httpx_stub.post = lambda *a, **kw: _FakeResponse({})
sys.modules.setdefault("httpx", httpx_stub)

from model_gateway import (
    ModelGateway, ModelResponse, ModelRouter, _UsageTracker, build_event
)
from model_gateway import build_event as _build_event_unused  # noqa

# Re-import build_event from harmony (not available in gateway) — use gateway’s
# internal one via checking the module directly
import model_gateway as mgw


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok_response(text="Hello", model="gpt"):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

def _claude_ok_response(text="Hello"):
    return {
        "content": [{"text": text}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


# ---------------------------------------------------------------------------
# ModelResponse
# ---------------------------------------------------------------------------

def test_model_response_ok_true():
    r = ModelResponse(text="hi", model="claude/claude-sonnet-4-5", provider="claude")
    assert r.ok is True

def test_model_response_ok_false_on_error():
    r = ModelResponse(text="", model="", provider="", error="timeout")
    assert r.ok is False

def test_model_response_to_dict():
    r = ModelResponse(text="hi", model="z_ai/glm-5.1", provider="z_ai",
                      trace_id="tr-1", latency_ms=120.5)
    d = r.to_dict()
    assert d["text"] == "hi"
    assert d["trace_id"] == "tr-1"
    assert d["latency_ms"] == 120.5


# ---------------------------------------------------------------------------
# ModelGateway._parse_model_spec
# ---------------------------------------------------------------------------

def test_parse_model_spec_full():
    gw = ModelGateway()
    provider, model = gw._parse_model_spec("claude/claude-sonnet-4-5")
    assert provider == "claude"
    assert model == "claude-sonnet-4-5"

def test_parse_model_spec_provider_only():
    gw = ModelGateway()
    provider, model = gw._parse_model_spec("z_ai")
    assert provider == "z_ai"
    assert model == "glm-5.1"


# ---------------------------------------------------------------------------
# ModelGateway.call — success paths
# ---------------------------------------------------------------------------

def test_call_claude_success(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fake_post = MagicMock(return_value=_FakeResponse(_claude_ok_response("Bonjour")))
    with patch.object(httpx_stub, "post", fake_post):
        gw = ModelGateway()
        resp = gw.call("Say hello", model="claude/claude-sonnet-4-5")

    assert resp.ok
    assert resp.text == "Bonjour"
    assert resp.provider == "claude"
    assert resp.latency_ms >= 0

def test_call_z_ai_success(monkeypatch):
    monkeypatch.setenv("Z_AI_API_KEY", "test-key")

    fake_post = MagicMock(return_value=_FakeResponse(_ok_response("Code generated")))
    with patch.object(httpx_stub, "post", fake_post):
        gw = ModelGateway()
        resp = gw.call("Write hello world", model="z_ai/glm-5.1")

    assert resp.ok
    assert resp.text == "Code generated"
    assert resp.provider == "z_ai"


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------

def test_router_falls_back_to_second_in_chain(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    call_count = [0]

    def fake_post(url, **kwargs):
        call_count[0] += 1
        if "z.ai" in url:
            class _Err:
                def raise_for_status(self): raise Exception("Z.AI down")
                def json(self): return {}
            return _Err()
        # deepseek fallback
        return _FakeResponse(_ok_response("deepseek answer"))

    with patch.object(httpx_stub, "post", fake_post):
        router = ModelRouter()
        with patch.dict("os.environ", {"GATEWAY_MAX_RETRIES": "1"}):
            mgw.MAX_RETRIES = 1
            resp = router.route("code task", task_type="code")
            mgw.MAX_RETRIES = 2  # reset

    assert resp.fallback_used is True
    assert resp.provider == "deepseek"


# ---------------------------------------------------------------------------
# Usage tracker
# ---------------------------------------------------------------------------

def test_usage_tracker_accumulates():
    t = _UsageTracker()
    t.record("claude", "claude-sonnet-4-5", True, 100, 50, 800.0)
    t.record("claude", "claude-sonnet-4-5", True, 200, 80, 600.0)
    t.record("claude", "claude-sonnet-4-5", False, 0, 0, 100.0)
    s = t.summary()
    key = "claude/claude-sonnet-4-5"
    assert s[key]["calls"] == 3
    assert s[key]["failures"] == 1
    assert s[key]["prompt_tokens"] == 300
    assert s[key]["success_rate"] == round(2/3, 3)


# ---------------------------------------------------------------------------
# ModelRouter task-type routing
# ---------------------------------------------------------------------------

def test_router_routes_code_to_z_ai():
    router = ModelRouter()
    chain = router._routes["code"]
    assert chain[0][0] == "z_ai"

def test_router_routes_reasoning_to_claude():
    router = ModelRouter()
    chain = router._routes["reasoning"]
    assert chain[0][0] == "claude"

def test_router_routes_fast_to_grok():
    router = ModelRouter()
    chain = router._routes["fast"]
    assert chain[0][0] == "grok_api"


# ---------------------------------------------------------------------------
# Build-watch event emission
# ---------------------------------------------------------------------------

def test_build_watch_event_emitted(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    events_file = tmp_path / "events.jsonl"
    events_file.touch()
    monkeypatch.setattr(mgw, "BUILD_WATCH_DIR", tmp_path)
    monkeypatch.setattr(mgw, "EMIT_EVENTS", True)

    fake_post = MagicMock(return_value=_FakeResponse(_claude_ok_response("hi")))
    with patch.object(httpx_stub, "post", fake_post):
        gw = ModelGateway()
        gw.call("hello", model="claude/claude-sonnet-4-5")

    lines = events_file.read_text().strip().split("\n")
    assert len(lines) >= 2  # one plan + one result
    first = json.loads(lines[0])
    assert first["kind"] == "note"
    assert "gateway" in first["msg"]
