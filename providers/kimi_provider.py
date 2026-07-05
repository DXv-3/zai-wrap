"""
providers/kimi_provider.py
----------------------------
Kimi (Moonshot) provider for ModelRouter (OpenAI-compatible API).

Models used by ROUTE_TABLE:
    moonshot-v1-8k     — creative tier fallback
    moonshot-v1-128k   — long_context tier (primary — 128K context window)

Env var: KIMI_API_KEY
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

KIMI_BASE = "https://api.moonshot.cn/v1"


class KimiProvider:

    def available(self) -> bool:
        return bool(os.getenv("KIMI_API_KEY", ""))

    def complete(
        self,
        prompt: str,
        model: str = "moonshot-v1-8k",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Tuple[str, int]:
        import openai
        client = openai.OpenAI(
            api_key=os.environ["KIMI_API_KEY"],
            base_url=KIMI_BASE,
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = resp.choices[0].message.content or ""
        tokens = (resp.usage.total_tokens or 0) if resp.usage else 0
        return content, tokens
