"""
providers/openai_provider.py
------------------------------
OpenAI (GPT-4o / o3) provider for ModelRouter.

Models used by ROUTE_TABLE:
    gpt-4o       — code / vision / long_context / web_search tier
    gpt-4o-mini  — fast tier fallback
    o3-mini      — reasoning tier fallback

Env var: OPENAI_API_KEY
"""

from __future__ import annotations

import os
from typing import Optional, Tuple


class OpenAIProvider:

    def available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", ""))

    def complete(
        self,
        prompt: str,
        model: str = "gpt-4o",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Tuple[str, int]:
        import openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # o3-mini uses max_completion_tokens and no temperature
        if model.startswith("o3") or model.startswith("o1"):
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=max_tokens,
            )
        else:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        content = resp.choices[0].message.content or ""
        tokens = (resp.usage.total_tokens or 0) if resp.usage else 0
        return content, tokens
