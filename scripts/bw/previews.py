"""Preview discovery and git snapshot."""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Any

from bw.cache import TTLCache
from bw.constants import ARTIFACT_GLOBS, PREVIEW_PORTS
from bw.paths import PathPolicy

_ports_cache = TTLCache(ttl_sec=5.0)
_git_cache = TTLCache(ttl_sec=8.0)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


def open_ports() -> set[int]:
    return _ports_cache.get(lambda: {p for p, _ in PREVIEW_PORTS if port_open(p)})


def discover_previews(
    policy: PathPolicy,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cwd = policy.project
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    listening = open_ports()

    for port, label in PREVIEW_PORTS:
        if port in listening:
            url = f"http://127.0.0.1:{port}"
            if url not in seen:
                seen.add(url)
                out.append({"url": url, "label": label, "type": "server", "port": port})

    for pattern in ARTIFACT_GLOBS:
        for p in sorted(cwd.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)[:8]:
            rel = str(p.relative_to(cwd))
            ext = p.suffix.lower()
            kind = "html" if ext in (".html", ".htm") else "markdown" if ext == ".md" else "file"
            out.append(
                {
                    "url": f"/api/raw?path={rel}",
                    "label": p.name,
                    "type": kind,
                    "path": rel,
                    "mtime": p.stat().st_mtime,
                }
            )

    known = {a.get("path") for a in out if a.get("path")}
    for ev in reversed(events):
        for rel in ev.get("files") or []:
            sp = policy.safe_project_file(str(rel))
            if not sp:
                continue
            rel_safe = str(sp.relative_to(cwd))
            if rel_safe in known:
                continue
            known.add(rel_safe)
            ext = sp.suffix.lower()
            kind = "html" if ext in (".html", ".htm") else "markdown" if ext == ".md" else "code"
            out.insert(
                0,
                {
                    "url": f"/api/raw?path={rel_safe}" if kind == "html" else f"/api/file?path={rel_safe}",
                    "label": sp.name,
                    "type": kind,
                    "path": rel_safe,
                    "mtime": sp.stat().st_mtime,
                    "pinned": True,
                },
            )
    return out[:20]


def pick_primary(previews: list[dict[str, Any]]) -> str | None:
    if not previews:
        return None
    for p in previews:
        if p.get("type") == "server" and p.get("port") not in (8790,):
            return p["url"]
    for name in ("handoff-preview.html", "index.html"):
        for p in previews:
            if p.get("path") == name or p.get("label") == name:
                return p["url"]
    for p in previews:
        if p.get("type") == "html":
            return p["url"]
    for p in previews:
        if p.get("type") == "server":
            return p["url"]
    return previews[0]["url"]


def list_artifacts(policy: PathPolicy) -> list[dict[str, Any]]:
    cwd = policy.project
    items: list[dict[str, Any]] = []
    for pattern in ARTIFACT_GLOBS:
        for p in cwd.glob(pattern):
            rel = str(p.relative_to(cwd))
            items.append(
                {
                    "path": rel,
                    "name": p.name,
                    "type": p.suffix.lower().lstrip(".") or "file",
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
            )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:40]


def git_snapshot(cwd: Path) -> dict[str, Any]:
    if not (cwd / ".git").is_dir():
        return {"enabled": False}
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip().splitlines()
        return {
            "enabled": True,
            "branch": branch,
            "changed_count": len(status),
            "status_lines": status[:24],
        }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"enabled": False}


def cached_git(cwd: Path) -> dict[str, Any]:
    return _git_cache.get(lambda: git_snapshot(cwd))