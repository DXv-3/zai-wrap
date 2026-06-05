"""Central limits and defaults."""
from __future__ import annotations

from typing import Any

MAX_POST_BYTES = 4_000_000
MAX_JSONL_TAIL_BYTES = 8_000_000
MAX_EVENT_MSG = 4_000
MAX_TTS_INPUT = 50_000
MAX_FILE_READ = 200_000
MAX_RAW_BYTES = 5_000_000
MAX_SAVE_BYTES = 2_000_000
MAX_TERMINAL_PIN = 2_000_000
MAX_PTY_INPUT = 16_384
PTY_CHUNK_CAP = 200

DEFAULT_SETTINGS: dict[str, Any] = {
    "tts_voice": "Siri Voice 2",
    "tts_rate": 190,
    "tts_read_thinking": False,
    "tts_read_tools": False,
    "tts_auto_read": False,
    "read_show_thinking": False,
    "stt_lang": "en-US",
}

PREVIEW_PORTS: list[tuple[int, str]] = [
    (5173, "Vite"),
    (3000, "Next/React"),
    (4173, "Vite preview"),
    (8080, "Dev server"),
    (8787, "Handoff API"),
    (8790, "Build Watch"),
]

ARTIFACT_GLOBS: list[str] = [
    "handoff-preview.html",
    "static/web/index.html",
    "index.html",
    "handoffs/*.html",
    "handoffs/*.md",
    "handoffs/*.HANDOFF.md",
    "handoffs/*.AGENT.md",
]

ALLOWED_ORIGIN = "http://127.0.0.1"