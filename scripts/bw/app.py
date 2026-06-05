"""Application core — wires storage, grok, terminal, previews, tts."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bw import grok
from bw.boot import run_preflight
from bw.constants import MAX_RAW_BYTES, MAX_SAVE_BYTES
from bw.paths import PathPolicy, resolve_project, resolve_watch
from bw.previews import cached_git, discover_previews, list_artifacts, pick_primary
from bw.security import resolve_tts_voice, spoken_content_selected_voice
from bw.storage import WatchStore
from bw.terminal import EmbeddedShell
from bw import terminals as term_io
from bw import tts


class App:
    def __init__(self) -> None:
        self.scripts_dir = Path(__file__).resolve().parent.parent
        self.static_dir = self.scripts_dir.parent / "static"
        self.project = resolve_project()
        self.watch = resolve_watch(self.project)
        self.policy = PathPolicy(self.project, self.watch)
        self.store = WatchStore(self.policy)
        self.shell = EmbeddedShell()
        self._grok_lock = threading.Lock()
        self.load_error: str | None = None
        try:
            self.store.ensure()
        except Exception as exc:
            self.load_error = str(exc)

    def preflight(self, *, require_port: bool = True) -> dict[str, Any]:
        port = int(os.environ.get("BUILD_WATCH_PORT", "8790"))
        return run_preflight(
            self.scripts_dir,
            self.static_dir,
            self.watch,
            port,
            require_port=require_port,
            package_ok=self.load_error is None,
            load_error=self.load_error,
        )

    def grok_tick(self) -> None:
        if self.load_error:
            return
        with self._grok_lock:
            n = grok.ingest_updates(self.watch)
            if n and os.environ.get("BUILD_WATCH_GROK_SYNC", "1") == "1":
                grok.sync_to_build_events(self.watch, self.store.append_event)

    def save_file(self, rel: str, content: str) -> dict[str, Any]:
        if len(content) > MAX_SAVE_BYTES:
            return {"ok": False, "error": "too_large"}
        target = self.policy.safe_project_file(rel, must_exist=True) or self.policy.safe_new_file(rel)
        if not target:
            return {"ok": False, "error": "invalid_path"}
        rel_out = str(target.relative_to(self.policy.project))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        self.store.append_event("edit", f"Saved {rel_out} from canvas", [rel_out])
        return {"ok": True, "path": rel_out, "mtime": target.stat().st_mtime}

    def canvas_state(self) -> dict[str, Any]:
        self.grok_tick()
        events = self.store.load_events()
        previews = discover_previews(self.policy, events)
        settings = self.store.load_settings()
        vmeta = resolve_tts_voice(str(settings.get("tts_voice") or "Siri Voice 2"))
        grok_status: dict[str, Any] = {"connected": False, "load_error": self.load_error}
        grok_acts: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        if not self.load_error:
            grok_status = grok.grok_status(self.watch)
            grok_acts = grok.load_activities(self.watch, 80)
            turns = grok.load_turns(self.watch, 80)
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "project": str(self.policy.project),
            "project_name": self.policy.project.name,
            "primary_preview": pick_primary(previews),
            "previews": previews,
            "artifacts": list_artifacts(self.policy),
            "events": events,
            "terminals": term_io.list_light(4),
            "git": cached_git(self.policy.project),
            "grok": grok_status,
            "grok_activity": grok_acts,
            "turns": turns,
            "settings": settings,
            "tts": {
                "siri_voice_2_available": tts.siri_available(),
                "resolved_voice": vmeta.get("resolved"),
                "spoken_content_voice": spoken_content_selected_voice(),
            },
            "boot": {"modules_ok": self.load_error is None, "load_error": self.load_error},
        }

    def bootstrap_grok(self, session_id: str | None = None) -> dict[str, Any]:
        from bw.security import sanitize_session_id

        sid = sanitize_session_id(session_id or "") or grok.resolve_session_id(self.watch)
        if not sid:
            return {"ok": False, "error": "no session_id"}
        updates = grok.find_updates_path(sid)
        if not updates or not updates.is_file():
            return {"ok": False, "error": "updates_not_found", "session_id": sid}
        with self._grok_lock:
            n = grok.bootstrap_session(self.watch, sid)
        status = grok.grok_status(self.watch)
        return {
            "ok": bool(status.get("connected")),
            "session_id": sid,
            "ingested": n,
            "grok": status,
        }

    def grok_rebuild(self, session_id: str | None = None) -> dict[str, Any]:
        from bw.security import sanitize_session_id

        if self.load_error:
            return {"ok": False, "error": "grok_unavailable", "detail": self.load_error}
        sid = sanitize_session_id(session_id or "") or grok.resolve_session_id(self.watch)
        if not sid:
            return {"ok": False, "error": "no session_id"}
        with self._grok_lock:
            n = grok.rebuild_turns(self.watch, sid)
        return {"ok": True, "lines": n, "turns": len(grok.load_turns(self.watch, 500))}