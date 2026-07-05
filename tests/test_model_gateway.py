"""
tests/test_model_gateway.py
-----------------------------
Tests for ModelRouter (GATEWAY-01).
All provider SDK calls mocked; no real API calls.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub all provider SDKs before importing model_gateway
# ---------------------------------------------------------------------------

def _make_openai_stub(content="openai response", tokens=50):
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = tokens
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = usage
    client = MagicMock()
    client.chat.completions.create.return_value = resp
    mod = types.ModuleType("openai")
    mod.OpenAI = MagicMock(return_value=client)
    return mod, client

def _make_anthropic_stub(content="anthropic response", tokens=60):
    text_block = MagicMock()
    text_block.text = content
    usage = MagicMock()
    usage.input_tokens = 20
    usage.output_tokens = 40
    msg = MagicMock()
    msg.content = [text_block]
    msg.usage = usage
    client = MagicMock()
    client.messages.create.return_value = msg
    mod = types.ModuleType("anthropic")
    mod.Anthropic = MagicMock(return_value=client)
    return mod, client

_openai_mod, _openai_client   = _make_openai_stub()
_anthropic_mod, _anthropic_client = _make_anthropic_stub()
sys.modules["openai"]     = _openai_mod
sys.modules["anthropic"]  = _anthropic_mod

# Stub harmony
_harmony = types.ModuleType("harmony_publisher_base")
_harmony.HarmonyPublisher = MagicMock()
sys.modules["harmony_publisher_base"] = _harmony

import os
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("DEEPSEEK_API_KEY",  "test-deepseek-key")
os.environ.setdefault("OPENAI_API_KEY",    "test-openai-key")
os.environ.setdefault("KIMI_API_KEY",      "test-kimi-key")
# XAI_API_KEY intentionally NOT set so GrokProvider uses bridge path

from model_gateway import ModelRouter, ModelResponse, ROUTE_TABLE, quick_call, get_router
from providers.anthropic_provider import AnthropicProvider
from providers.deepseek_provider  import DeepSeekProvider
from providers.openai_provider    import OpenAIProvider
from providers.kimi_provider      import KimiProvider


# ---------------------------------------------------------------------------
# ModelRouter tests
# ---------------------------------------------------------------------------

class TestModelRouter(unittest.TestCase):

    def setUp(self):
        self.router = ModelRouter()

    def test_available_providers_nonempty(self):
        providers = self.router.available_providers()
        self.assertIsInstance(providers, list)
        self.assertGreater(len(providers), 0)

    def test_route_returns_model_response(self):
        resp = self.router.route("Hello", task_type="fast")
        self.assertIsInstance(resp, ModelResponse)

    def test_route_success_flag(self):
        resp = self.router.route("Hello", task_type="code")
        self.assertTrue(resp.success)

    def test_route_content_is_string(self):
        resp = self.router.route("Hello", task_type="reasoning")
        self.assertIsInstance(resp.content, str)
        self.assertGreater(len(resp.content), 0)

    def test_route_tracks_task_type(self):
        resp = self.router.route("Hello", task_type="audit")
        self.assertEqual(resp.task_type, "audit")

    def test_call_specific_model_anthropic(self):
        resp = self.router.call("Hello", model="anthropic/claude-sonnet-4-5")
        self.assertEqual(resp.provider, "anthropic")
        self.assertEqual(resp.task_type, "direct")

    def test_call_specific_model_deepseek(self):
        resp = self.router.call("Write a sort function", model="deepseek/deepseek-coder")
        self.assertEqual(resp.provider, "deepseek")

    def test_call_no_prefix_falls_back_to_route(self):
        resp = self.router.call("Hello", model="claude-sonnet")
        self.assertIsInstance(resp, ModelResponse)

    def test_usage_summary_accumulates(self):
        self.router.route("p1", task_type="fast")
        self.router.route("p2", task_type="fast")
        summary = self.router.usage_summary()
        total = sum(v["calls"] for v in summary.values())
        self.assertGreaterEqual(total, 2)

    def test_usage_summary_has_expected_keys(self):
        self.router.route("test", task_type="code")
        summary = self.router.usage_summary()
        for model_stats in summary.values():
            for key in ["calls", "failures", "avg_latency_ms", "success_rate", "total_tokens"]:
                self.assertIn(key, model_stats)

    def test_fallback_on_primary_failure(self):
        """Simulate primary provider failing; router should try next in chain."""
        # Make deepseek (primary for 'code') fail
        orig = self.router._providers.get("deepseek")
        if orig:
            orig.complete = MagicMock(side_effect=Exception("deepseek down"))
        resp = self.router.route("test", task_type="code")
        # Should fall through to anthropic or openai
        self.assertIsInstance(resp, ModelResponse)
        # Reset
        if orig:
            from providers.deepseek_provider import DeepSeekProvider
            self.router._providers["deepseek"] = DeepSeekProvider()

    def test_all_providers_fail_returns_error_response(self):
        router = ModelRouter()
        # Remove all providers
        router._providers.clear()
        resp = router.route("test", task_type="code")
        self.assertFalse(resp.success)
        self.assertEqual(resp.model, "none")

    def test_route_table_covers_all_conductor_task_types(self):
        required = {"code", "reasoning", "fast", "creative", "vision",
                    "routing", "audit", "forensics"}
        self.assertTrue(required.issubset(set(ROUTE_TABLE.keys())))

    def test_quick_call_returns_string(self):
        result = quick_call("test", task_type="fast")
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# Individual provider tests
# ---------------------------------------------------------------------------

class TestAnthropicProvider(unittest.TestCase):

    def test_available_when_key_set(self):
        p = AnthropicProvider()
        self.assertTrue(p.available())

    def test_complete_returns_tuple(self):
        p = AnthropicProvider()
        content, tokens = p.complete("Hello", model="claude-haiku-4-5")
        self.assertIsInstance(content, str)
        self.assertIsInstance(tokens, int)

    def test_complete_calls_anthropic_sdk(self):
        _anthropic_client.messages.create.reset_mock()
        p = AnthropicProvider()
        p.complete("test", model="claude-sonnet-4-5")
        _anthropic_client.messages.create.assert_called_once()


class TestDeepSeekProvider(unittest.TestCase):

    def test_available_when_key_set(self):
        from providers.deepseek_provider import DeepSeekProvider
        p = DeepSeekProvider()
        self.assertTrue(p.available())

    def test_complete_uses_openai_compat(self):
        _openai_client.chat.completions.create.reset_mock()
        from providers.deepseek_provider import DeepSeekProvider
        p = DeepSeekProvider()
        p.complete("test", model="deepseek-chat")
        _openai_client.chat.completions.create.assert_called_once()

    def test_r1_forces_temperature_1(self):
        from providers.deepseek_provider import DeepSeekProvider
        p = DeepSeekProvider()
        p.complete("test", model="deepseek-r1", temperature=0.3)
        call_kwargs = _openai_client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs.get("temperature"), 1.0)


class TestOpenAIProvider(unittest.TestCase):

    def test_available_when_key_set(self):
        p = OpenAIProvider()
        self.assertTrue(p.available())

    def test_complete_gpt4o(self):
        _openai_client.chat.completions.create.reset_mock()
        p = OpenAIProvider()
        p.complete("test", model="gpt-4o")
        _openai_client.chat.completions.create.assert_called_once()

    def test_o3_uses_max_completion_tokens(self):
        from providers.openai_provider import OpenAIProvider
        p = OpenAIProvider()
        p.complete("test", model="o3-mini", max_tokens=1000)
        call_kwargs = _openai_client.chat.completions.create.call_args[1]
        self.assertIn("max_completion_tokens", call_kwargs)
        self.assertNotIn("temperature", call_kwargs)


class TestKimiProvider(unittest.TestCase):

    def test_available_when_key_set(self):
        p = KimiProvider()
        self.assertTrue(p.available())

    def test_complete_moonshot_128k(self):
        _openai_client.chat.completions.create.reset_mock()
        p = KimiProvider()
        p.complete("very long document", model="moonshot-v1-128k")
        _openai_client.chat.completions.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
