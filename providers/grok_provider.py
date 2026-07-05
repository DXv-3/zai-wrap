"""
providers/grok_provider.py
----------------------------
Grok (X.AI) provider for ModelRouter.

Two call paths, in priority order:
  1. Direct X.AI SDK (xai-sdk or openai-compatible base_url)  — if XAI_API_KEY set
  2. build-watch HTTP bridge at localhost:BUILD_WATCH_PORT      — if no XAI_API_KEY
     (uses the existing grok_bridge.py / build-watch session flow)

Models used by ROUTE_TABLE:
    grok-3   — vision / web_search tier

Env vars:
    XAI_API_KEY        (preferred — direct SDK)
    BUILD_WATCH_PORT   (fallback bridge, default 8790)
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

XAI_BASE = "https://api.x.ai/v1"


class GrokProvider:

    def available(self) -> bool:
        # Available if either the direct key or the build-watch bridge is reachable
        if os.getenv("XAI_API_KEY", ""):
            return True
        return self._bridge_alive()

    def complete(
        self,
        prompt: str,
        model: str = "grok-3",
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> Tuple[str, int]:
        if os.getenv("XAI_API_KEY", ""):
            return self._sdk_complete(prompt, model, system, max_tokens, temperature)
        return self._bridge_complete(prompt, model, system, max_tokens, temperature)

    # ------------------------------------------------------------------
    # Path 1: Direct X.AI API via OpenAI-compatible SDK
    # ------------------------------------------------------------------

    def _sdk_complete(
        self,
        prompt: str,
        model: str,
        system: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, int]:
        import openai
        client = openai.OpenAI(
            api_key=os.environ["XAI_API_KEY"],
            base_url=XAI_BASE,
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

    # ------------------------------------------------------------------
    # Path 2: build-watch HTTP bridge (existing zai-wrap Grok integration)
    # ------------------------------------------------------------------

    def _bridge_alive(self) -> bool:
        port = int(os.getenv("BUILD_WATCH_PORT", "8790"))
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    def _get_active_session(self) -> Optional[str]:
        """Read the most recent Grok session ID from ~/.grok/active_sessions.json."""
        import pathlib
        active = pathlib.Path.home() / ".grok" / "active_sessions.json"
        if not active.is_file():
            return None
        try:
            sessions = json.loads(active.read_text(encoding="utf-8"))
            return sessions[0].get("session_id") if sessions else None
        except Exception:
            return None

    def _bridge_complete(
        self,
        prompt: str,
        model: str,
        system: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, int]:
        port = int(os.getenv("BUILD_WATCH_PORT", "8790"))
        session_id = self._get_active_session()
        if not session_id:
            raise RuntimeError(
                "GrokProvider: no active Grok session. "
                "Open build-watch in the browser and start a Grok session first."
            )

        # POST prompt through build-watch relay
        payload = json.dumps({
            "session_id": session_id,
            "prompt": prompt,
            "system": system or "",
            "model": model,
            "max_tokens": max_tokens,
        }).encode()

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/grok/complete",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        content = data.get("content", data.get("text", ""))
        tokens = data.get("tokens_used", 0)
        return content, tokens
