"""HTTP server — route table, safe I/O."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from bw import grok, tts
from bw import terminals as term_io
from bw.app import App
from bw.constants import (
    ALLOWED_ORIGIN,
    MAX_FILE_READ,
    MAX_POST_BYTES,
    MAX_RAW_BYTES,
    MAX_TERMINAL_PIN,
)
from bw.constants import DEFAULT_SETTINGS
from bw.security import (
    clamp_int,
    parse_json_object,
    resolve_tts_voice,
    sanitize_session_id,
    sanitize_voice_name,
)
from bw.terminal import resolve_mirror


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class CanvasHandler(BaseHTTPRequestHandler):
    app: App

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _write(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(body)

    def _bytes(self, data: bytes, content_type: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(data)

    def _read_body(self) -> bytes | None:
        raw = self.headers.get("Content-Length", "0")
        try:
            declared = int(raw)
        except (TypeError, ValueError):
            declared = 0
        if declared > MAX_POST_BYTES:
            remaining = declared
            while remaining > 0:
                chunk = min(remaining, 65_536)
                self.rfile.read(chunk)
                remaining -= chunk
            return None
        length = clamp_int(declared, 0, 0, MAX_POST_BYTES)
        if length <= 0:
            return b"{}"
        return self.rfile.read(length)

    def _dispatch(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                self._json({"error": "internal", "detail": str(exc)[:300]}, 500)
            except Exception:
                pass

    def do_GET(self) -> None:
        self._dispatch(self._get)

    def do_POST(self) -> None:
        self._dispatch(self._post)

    def _get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)
        app = self.app

        if path in ("/", "/index.html", "/canvas"):
            canvas = app.static_dir / "canvas.html"
            if not canvas.is_file():
                self._json({"error": "canvas_missing"}, 503)
                return
            self._bytes(canvas.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/canvas-legacy":
            legacy = app.static_dir / "canvas-legacy.html"
            if legacy.is_file():
                self._bytes(legacy.read_bytes(), "text/html; charset=utf-8")
                return
            self.send_error(404)
            return
        if path.startswith("/assets/"):
            rel = unquote(path[len("/assets/") :]).lstrip("/")
            if rel and ".." not in rel.split("/"):
                target = (app.static_dir / rel).resolve()
                root = app.static_dir.resolve()
                if target.is_file() and str(target).startswith(str(root)):
                    mime, _ = mimetypes.guess_type(str(target))
                    self._bytes(target.read_bytes(), mime or "application/octet-stream")
                    return
            self.send_error(404)
            return

        routes: dict[str, Callable[[], None]] = {
            "/api/health": lambda: self._json(app.preflight(require_port=False)),
            "/api/state": lambda: self._json({**app.canvas_state(), "watch_url": _watch_url(), "events_path": str(app.store.events_path())}),
            "/api/canvas": lambda: self._json(app.canvas_state()),
            "/api/events": lambda: self._json({"events": app.store.load_events()}),
            "/api/settings": lambda: self._json(app.store.load_settings()),
            "/api/tts/status": lambda: self._json({"playing": tts.tts_status()}),
            "/api/grok/status": lambda: self._grok_json(lambda: grok.grok_status(app.watch)),
            "/api/grok/sessions": lambda: self._grok_json(lambda: {"sessions": grok.load_active_sessions()}),
            "/api/grok/voices": lambda: self._json({
                "siri_voice_2_available": tts.siri_available(),
                "resolved_voice": resolve_tts_voice("Siri Voice 2").get("resolved"),
            }),
            "/api/terminal/list": lambda: self._json({"terminals": term_io.list_light(24)}),
            "/api/terminal/pty/poll": lambda: self._pty_poll(),
        }
        if path in routes:
            routes[path]()
            return

        if path == "/api/grok/activity":
            app.grok_tick()
            self._grok_json(lambda: {"activity": grok.load_activities(app.watch, 120)})
            return
        if path == "/api/grok/turns":
            app.grok_tick()
            limit = clamp_int((qs.get("limit") or ["80"])[0], 80, 1, 500)
            self._grok_json(lambda: {"turns": grok.load_turns(app.watch, limit)})
            return
        if path == "/api/terminal/mirror":
            pin = (qs.get("pin") or [None])[0]
            data = resolve_mirror(
                app.watch,
                term_io.discover_dirs,
                term_io.list_full,
                unquote(pin) if pin else None,
            )
            self._json(data or {"error": "no_terminal"}, 404 if not data else 200)
            return
        if path == "/api/file":
            rel = unquote((qs.get("path") or [""])[0])
            target = app.policy.safe_project_file(rel)
            if not target:
                self.send_error(404)
                return
            text = target.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_READ]
            self._json({"path": rel, "content": text, "name": target.name})
            return
        if path == "/api/raw":
            rel = unquote((qs.get("path") or [""])[0])
            target = app.policy.safe_project_file(rel)
            if not target:
                self.send_error(404)
                return
            mime, _ = mimetypes.guess_type(str(target))
            self._bytes(target.read_bytes()[:MAX_RAW_BYTES], mime or "application/octet-stream")
            return
        self.send_error(404)

    def _post(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        raw = self._read_body()
        if raw is None:
            self._json({"error": "payload_too_large"}, 413)
            return
        if len(raw) > MAX_POST_BYTES:
            self._json({"error": "payload_too_large"}, 413)
            return
        data = parse_json_object(raw)
        if data is None:
            self._json({"error": "invalid json"}, 400)
            return
        app = self.app

        if path == "/api/settings":
            patch = {k: data[k] for k in DEFAULT_SETTINGS if k in data}
            self._json(app.store.save_settings(patch))
            return
        if path == "/api/tts":
            settings = app.store.load_settings()
            voice = sanitize_voice_name(str(data["voice"])) if data.get("voice") is not None else None
            rate = clamp_int(data["rate"], 190, 80, 400) if data.get("rate") is not None else None
            result = tts.tts_speak(str(data.get("text") or ""), settings, voice=voice, rate=rate)
            code = 422 if result.get("error") == "voice_not_installed" else 400 if result.get("error") == "empty_text" else 200
            self._json(result, code)
            return
        if path == "/api/tts/stop":
            tts.tts_stop()
            self._json({"ok": True})
            return
        if path == "/api/file/save":
            if data.get("content") is None:
                self._json({"error": "content required"}, 400)
                return
            result = app.save_file(str(data.get("path") or ""), str(data["content"]))
            code = 200 if result.get("ok") else (413 if result.get("error") == "too_large" else 400)
            self._json(result, code)
            return
        if path == "/api/grok/connect":
            sid = sanitize_session_id(str(data.get("session_id") or "")) or grok.resolve_session_id(app.watch)
            if not sid:
                self._json({"error": "no session_id"}, 400)
                return
            self._grok_json(lambda: app.bootstrap_grok(sid))
            return
        if path == "/api/grok/rebuild-turns":
            sid = sanitize_session_id(str(data.get("session_id") or "")) or grok.resolve_session_id(app.watch)
            if not sid:
                self._json({"error": "no session_id"}, 400)
                return
            self._grok_json(lambda: app.grok_rebuild(sid))
            return
        if path == "/api/terminal/pin":
            self._terminal_pin(data)
            return
        if path == "/api/terminal/pty/start":
            result = app.shell.start(app.policy.project)
            code = 503 if result.get("error") == "pty_unavailable" else 200
            self._json(result, code)
            return
        if path == "/api/terminal/pty/stop":
            app.shell.stop()
            self._json({"ok": True})
            return
        if path == "/api/terminal/pty/input":
            raw_in = data.get("data")
            if raw_in is not None and not isinstance(raw_in, str):
                self._json({"error": "data must be string"}, 400)
                return
            err = app.shell.write(raw_in or "")
            if err:
                self._json({"error": err}, 503)
                return
            self._json({"ok": True})
            return
        if path == "/api/dictation":
            text = (data.get("text") or "").strip()
            if not text:
                self._json({"error": "empty"}, 400)
                return
            self._json({"ok": True, "row": app.store.append_dictation(text)})
            return
        if path == "/api/event":
            raw_files = data.get("files")
            files = [str(x) for x in raw_files[:24]] if isinstance(raw_files, list) else None
            ev = app.store.append_event(str(data.get("kind", "note")), str(data.get("msg", "")), files)
            self._json({"ok": True, "event": ev})
            return
        self.send_error(404)

    def _grok_json(self, fn: Callable[[], Any]) -> None:
        if self.app.load_error:
            self._json({"error": "grok_unavailable", "detail": self.app.load_error}, 503)
            return
        payload = fn()
        if payload is None or not isinstance(payload, dict):
            self._json({"error": "invalid_response"}, 500)
            return
        code = 200
        if payload.get("ok") is False or payload.get("error"):
            err = payload.get("error")
            if err == "no session_id":
                code = 400
            elif err == "updates_not_found":
                code = 404
            elif err == "grok_unavailable":
                code = 503
            else:
                code = 422
        self._json(payload, code)

    def _pty_poll(self) -> None:
        self._json({"running": self.app.shell.running(), "output": self.app.shell.drain()})

    def _terminal_pin(self, data: dict[str, Any]) -> None:
        from datetime import datetime, timezone
        from pathlib import Path

        from bw.terminal import save_pin
        from bw.security import sanitize_snapshot_name

        wd = self.app.watch
        if data.get("content") is not None:
            content = str(data["content"])
            if len(content) > MAX_TERMINAL_PIN:
                self._json({"error": "too_large"}, 413)
                return
            snap = sanitize_snapshot_name(str(data.get("snapshot_name") or "dropped-terminal.txt"))
            snap_path = self.app.policy.snapshot_path(snap)
            if not snap_path:
                self._json({"error": "invalid_snapshot"}, 400)
                return
            snap_path.write_text(content, encoding="utf-8")
            pin = {
                "snapshot_path": str(snap_path),
                "name": snap,
                "pinned_at": datetime.now(timezone.utc).isoformat(),
            }
        elif data.get("path"):
            p = Path(str(data["path"]))
            if not p.is_file() or not self.app.policy.allowed_terminal(p):
                self._json({"error": "invalid_path"}, 400)
                return
            pin = {"path": str(p.resolve()), "name": p.name, "pinned_at": datetime.now(timezone.utc).isoformat()}
        else:
            self._json({"error": "path or content required"}, 400)
            return
        self._json({"ok": True, "pin": save_pin(wd, pin)})


def _watch_url() -> str:
    return f"http://127.0.0.1:{os.environ.get('BUILD_WATCH_PORT', '8790')}"


def serve(app: App, port: int) -> None:
    report = app.preflight(require_port=True)
    if not report.get("ok") or app.load_error:
        raise SystemExit(json.dumps(report, indent=2))
    os.chdir(app.policy.project)
    app.store.ensure()
    sid = grok.resolve_session_id(app.watch)
    if sid and not app.load_error:
        try:
            grok.bootstrap_session(app.watch, sid)
            print(f"grok-bridge: connected session {sid}", flush=True)
        except Exception as exc:
            print(f"grok-bridge: bootstrap failed: {exc}", file=sys.stderr)
    handler = type("Handler", (CanvasHandler,), {"app": app})
    server = ReuseServer(("127.0.0.1", port), handler)
    print(f"build-watch v2: http://127.0.0.1:{port}  project={app.policy.project}", flush=True)
    server.serve_forever()