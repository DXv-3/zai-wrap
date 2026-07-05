"""
providers/deepseek_provider.py
--------------------------------
DeepSeek provider for ModelRouter (OpenAI-compatible API).

Models used by ROUTE_TABLE:
    deepseek-chat    — fast / creative tier
    deepseek-coder   — code tier (primary)
    deepseek-r1      — reasoning / audit / forensics tier (thinking model)

Env var: DEEPSEEK_API_KEY
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

DEEPSEEK_BASE = "https://api.deepseek.com/v1"


class DeepSeekProvider:

    def available(self) -> bool:
        return bool(os.getenv("DEEPSEEK_API_KEY", ""))

    def complete(
        self,
        prompt: str,
        model: str = "deepseek-chat",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Tuple[str, int]:
        import openai
        client = openai.OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=DEEPSEEK_BASE,
        )

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # deepseek-r1 is a reasoning/thinking model — temperature must be 1
        if "r1" in model.lower():
            temperature = 1.0

        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        content = resp.choices[0].message.content or ""
        tokens = (resp.usage.total_tokens or 0) if resp.usage else 0
        return content, tokens
