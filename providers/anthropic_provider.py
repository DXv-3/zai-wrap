"""
providers/anthropic_provider.py
---------------------------------
Claude (Anthropic) provider for ModelRouter.

Models used by ROUTE_TABLE:
    claude-haiku-4-5   — fast / routing tier
    claude-sonnet-4-5  — code / creative / audit tier
    claude-opus-4-5    — reasoning / vision / forensics tier

Env var: ANTHROPIC_API_KEY
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


class AnthropicProvider:

    def available(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY", ""))

    def complete(
        self,
        prompt: str,
        model: str = "claude-sonnet-4-5",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Tuple[str, int]:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        # anthropic SDK >= 0.20 supports temperature via model params
        # Keep it out for reasoning models that don't accept it
        non_temp_models = {"claude-opus-4-5"}
        if model not in non_temp_models:
            kwargs["temperature"] = temperature

        msg = client.messages.create(**kwargs)
        content = msg.content[0].text if msg.content else ""
        tokens = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return content, tokens
