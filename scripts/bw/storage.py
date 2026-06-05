"""JSONL and settings persistence."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bw.constants import (
    DEFAULT_SETTINGS,
    MAX_EVENT_MSG,
    MAX_JSONL_TAIL_BYTES,
)
from bw.paths import PathPolicy
from bw.security import (
    STT_LANG_RE,
    clamp_int,
    sanitize_event_kind,
    sanitize_voice_name,
)


def tail_jsonl(path: Path, limit: int, max_bytes: int = MAX_JSONL_TAIL_BYTES) -> list[dict[str, Any]]:
    if not path.is_file() or limit <= 0:
        return []
    size = path.stat().st_size
    read_from = max(0, size - max_bytes)
    with path.open("rb") as f:
        if read_from:
            f.seek(read_from)
            f.readline()
        raw = f.read().decode("utf-8", errors="replace")
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-limit:]


class WatchStore:
    def __init__(self, policy: PathPolicy) -> None:
        self.policy = policy
        self.watch = policy.watch
        self._io_lock = threading.Lock()

    def ensure(self) -> None:
        self.watch.mkdir(parents=True, exist_ok=True)
        self.events_path().touch(exist_ok=True)

    def events_path(self) -> Path:
        return self.watch / "events.jsonl"

    def settings_path(self) -> Path:
        return self.watch / "settings.json"

    def _merge_settings(self, base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
        current = dict(base)
        for key in DEFAULT_SETTINGS:
            if key not in patch:
                continue
            val = patch[key]
            if key == "tts_rate":
                current[key] = clamp_int(val, 190, 80, 400)
            elif key in ("tts_read_thinking", "tts_read_tools", "tts_auto_read", "read_show_thinking"):
                current[key] = bool(val)
            elif key == "tts_voice":
                v = sanitize_voice_name(str(val))
                if v:
                    current[key] = v
            elif key == "stt_lang":
                lang = str(val).strip()[:16]
                if STT_LANG_RE.match(lang):
                    current[key] = lang
        return current

    def load_settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        sp = self.settings_path()
        if sp.is_file():
            try:
                data = json.loads(sp.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    patch = {k: data[k] for k in DEFAULT_SETTINGS if k in data}
                    return self._merge_settings(out, patch)
            except json.JSONDecodeError:
                pass
        return out

    def save_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            patch = {}
        whitelist = {k: patch[k] for k in DEFAULT_SETTINGS if k in patch}
        current = self._merge_settings(self.load_settings(), whitelist)
        self.ensure()
        with self._io_lock:
            tmp = self.settings_path().with_suffix(".json.tmp")
            tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
            tmp.replace(self.settings_path())
        return current

    def load_events(self, limit: int = 80) -> list[dict[str, Any]]:
        return tail_jsonl(self.events_path(), limit)

    def append_event(self, kind: str, msg: str, files: list[str] | None = None) -> dict[str, Any]:
        self.ensure()
        safe_files: list[str] = []
        if files:
            for rel in files[:24]:
                sp = self.policy.safe_project_file(str(rel))
                if sp:
                    safe_files.append(str(sp.relative_to(self.policy.project)))
        ev: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": sanitize_event_kind(kind),
            "msg": (msg or "")[:MAX_EVENT_MSG],
        }
        if safe_files:
            ev["files"] = safe_files
        with self._io_lock:
            with self.events_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def append_dictation(self, text: str) -> dict[str, Any]:
        self.ensure()
        row = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "text": (text or "")[:20_000],
        }
        path = self.watch / "dictation.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row