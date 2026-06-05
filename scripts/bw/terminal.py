#!/usr/bin/env python3
"""Embedded terminal mirror + optional PTY shell for build-watch canvas."""
from __future__ import annotations

import fcntl
import json
import os
import select
import subprocess
import threading
from pathlib import Path
from typing import Any

from bw.constants import MAX_PTY_INPUT
from bw.paths import PathPolicy
from bw.security import sanitize_snapshot_name


class EmbeddedShell:
    """PTY shell in project cwd (sibling to Grok terminal, not the same OS window)."""

    def __init__(self) -> None:
        self._master: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._api_lock = threading.Lock()
        self._lock = threading.Lock()
        self._chunks: list[str] = []

    def running(self) -> bool:
        with self._api_lock:
            return self._proc is not None and self._proc.poll() is None

    def start(self, cwd: Path) -> dict[str, Any]:
        with self._api_lock:
            try:
                self._stop_unlocked()
                master, slave = os.openpty()
                shell = os.environ.get("SHELL", "/bin/zsh")
                self._proc = subprocess.Popen(
                    [shell, "-l"],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=str(cwd),
                    close_fds=True,
                )
                os.close(slave)
                self._master = master
                flags = fcntl.fcntl(master, fcntl.F_GETFL)
                fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                threading.Thread(target=self._read_loop, daemon=True).start()
                return {"ok": True, "shell": shell, "cwd": str(cwd)}
            except OSError as exc:
                self._stop_unlocked()
                return {"ok": False, "error": "pty_unavailable", "detail": str(exc)[:200]}

    def _read_loop(self) -> None:
        while self.running() and self._master is not None:
            try:
                r, _, _ = select.select([self._master], [], [], 0.25)
                if not r:
                    continue
                data = os.read(self._master, 8192)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                with self._lock:
                    self._chunks.append(text)
                    if len(self._chunks) > 400:
                        self._chunks = self._chunks[-200:]
            except OSError:
                break

    def write(self, text: str) -> str | None:
        with self._api_lock:
            if self._master is None:
                return "pty_unavailable"
            if len(text) > MAX_PTY_INPUT:
                text = text[:MAX_PTY_INPUT]
            try:
                os.write(self._master, text.encode("utf-8"))
            except OSError:
                return "pty_unavailable"
        return None

    def drain(self) -> str:
        with self._lock:
            out = "".join(self._chunks)
            self._chunks = []
        return out

    def stop(self) -> None:
        with self._api_lock:
            self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
        self._proc = None
        if self._master is not None:
            try:
                os.close(self._master)
            except OSError:
                pass
        self._master = None
        with self._lock:
            self._chunks = []


def pin_path(watch_dir: Path) -> Path:
    return watch_dir / "terminal_pin.json"


def load_pin(watch_dir: Path) -> dict[str, Any]:
    p = pin_path(watch_dir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _policy(watch_dir: Path) -> PathPolicy:
    from bw.paths import resolve_project, resolve_watch

    project = resolve_project()
    return PathPolicy(project, watch_dir if watch_dir.is_absolute() else resolve_watch(project))


def save_pin(watch_dir: Path, pin: dict[str, Any]) -> dict[str, Any]:
    watch_dir.mkdir(parents=True, exist_ok=True)
    pin_path(watch_dir).write_text(json.dumps(pin, indent=2), encoding="utf-8")
    return pin


def parse_terminal_body(path: Path, max_chars: int = 120_000) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"')
            body = parts[2]
            if "---" in body:
                body, _, tail = body.rpartition("---")
                for line in tail.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        meta[k.strip()] = v.strip()
    running = meta.get("exit_code") in (None, "", "-1") and "ended_at" not in meta
    return {
        "id": path.stem,
        "path": str(path),
        "name": path.name,
        "cwd": meta.get("cwd", ""),
        "command": meta.get("command", ""),
        "running": running,
        "exit_code": meta.get("exit_code"),
        "output": body[-max_chars:],
        "mtime": path.stat().st_mtime,
    }


def list_terminal_files(discover_fn) -> list[dict[str, Any]]:
    files: list[Path] = []
    for d in discover_fn():
        files.extend(d.glob("*.txt"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "id": p.stem,
            "path": str(p),
            "name": p.name,
            "mtime": p.stat().st_mtime,
        }
        for p in files[:24]
    ]


def resolve_mirror(
    watch_dir: Path,
    discover_fn,
    parse_fn,
    pin_hint: str | None = None,
) -> dict[str, Any] | None:
    policy = _policy(watch_dir)
    if pin_hint:
        p = Path(pin_hint)
        if p.is_file() and policy.allowed_terminal(p):
            return parse_terminal_body(p)
    pin = load_pin(watch_dir)
    if pin.get("path"):
        p = Path(pin["path"])
        if p.is_file() and policy.allowed_terminal(p):
            return parse_terminal_body(p)
    if pin.get("snapshot_path"):
        snap = Path(pin["snapshot_path"])
        if snap.is_file() and policy.allowed_watch_file(snap):
            data = parse_terminal_body(snap)
            data["dropped"] = True
            return data
    terms = parse_fn(12)
    if not terms:
        return None
    active = next((t for t in terms if t.get("running")), terms[0])
    path = active.get("path")
    if path:
        p = Path(path)
        if p.is_file() and policy.allowed_terminal(p):
            out = parse_terminal_body(p)
            out["output_tail"] = active.get("output_tail", "")
            return out
    return {
        "id": active.get("id"),
        "path": path,
        "name": active.get("id", "terminal"),
        "cwd": active.get("cwd", ""),
        "command": active.get("command", ""),
        "running": active.get("running", False),
        "output": active.get("output_full") or active.get("output_tail", ""),
        "mtime": active.get("mtime"),
    }