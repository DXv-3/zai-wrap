"""Startup preflight."""
from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from typing import Any


def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _load_module(script_dir: Path, filename: str, mod_name: str) -> tuple[bool, str]:
    path = script_dir / filename
    if not path.is_file():
        return False, f"missing {path}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if not spec or not spec.loader:
            return False, "spec failed"
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def run_preflight(
    script_dir: Path,
    static_dir: Path,
    watch_dir: Path,
    port: int,
    *,
    require_port: bool = True,
    package_ok: bool = True,
    load_error: str | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    py = sys.version_info
    checks.append(_check("python", py >= (3, 10), f"{py.major}.{py.minor}.{py.micro}"))
    canvas = static_dir / "canvas.html"
    checks.append(_check("canvas.html", canvas.is_file(), str(canvas)))
    for name in ("bw/__init__.py", "bw/app.py", "bw/server.py", "bw/grok.py", "bw/terminal.py"):
        p = script_dir / name
        checks.append(_check(name, p.is_file(), str(p)))
    try:
        watch_dir.mkdir(parents=True, exist_ok=True)
        probe = watch_dir / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(_check("watch_dir_writable", True, str(watch_dir)))
    except OSError as exc:
        checks.append(_check("watch_dir_writable", False, str(exc)))
    ok_grok, det_grok = _load_module(script_dir, "bw/grok.py", "bw_grok_boot")
    checks.append(_check("grok_module", ok_grok, det_grok))
    ok_term, det_term = _load_module(script_dir, "bw/terminal.py", "bw_term_boot")
    checks.append(_check("terminal_module", ok_term, det_term))
    if require_port:
        busy = port_in_use("127.0.0.1", port)
        checks.append(
            _check("port", not busy, "free" if not busy else f"127.0.0.1:{port} in use")
        )
    checks.append(_check("package_load", package_ok, load_error or "ok"))
    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "version": "2.0.0",
        "checks": checks,
        "port": port,
        "watch_dir": str(watch_dir),
        "modules_ok": package_ok,
        "load_error": load_error,
    }