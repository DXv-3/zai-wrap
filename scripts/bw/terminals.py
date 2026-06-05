"""Grok terminal file discovery and parsing."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bw.paths import PathPolicy


def discover_dirs() -> list[Path]:
    if custom := os.environ.get("GROK_TERMINALS_DIR"):
        p = Path(custom)
        return [p] if p.is_dir() else []
    base = Path.home() / ".grok" / "projects"
    if not base.is_dir():
        return []
    return sorted(
        [t for t in base.glob("**/terminals") if t.is_dir()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )


def _meta_from_head(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    if not text.startswith("---"):
        return meta
    parts = text.split("---", 2)
    if len(parts) < 3:
        return meta
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"')
    return meta


def summary(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(16_384)
    except OSError:
        return {}
    meta = _meta_from_head(head)
    running = meta.get("exit_code") in (None, "", "-1") and "ended_at" not in meta
    return {
        "id": path.stem,
        "path": str(path),
        "cwd": meta.get("cwd", ""),
        "command": (meta.get("command") or "")[:180],
        "running": running,
        "exit_code": meta.get("exit_code"),
        "mtime": path.stat().st_mtime,
    }


def parse_full(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            meta = _meta_from_head(text)
            body = parts[2]
            if "---" in body:
                body, _, tail = body.rpartition("---")
                for line in tail.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        meta[k.strip()] = v.strip()
    lines = body.strip().splitlines()
    tail = "\n".join(lines[-30:]) if lines else ""
    running = meta.get("exit_code") in (None, "", "-1") and "ended_at" not in meta
    return {
        "id": path.stem,
        "path": str(path),
        "cwd": meta.get("cwd", ""),
        "command": meta.get("command", "")[:180],
        "running": running,
        "exit_code": meta.get("exit_code"),
        "output_tail": tail[-3000:],
        "output_full": body.strip()[-120_000:],
        "mtime": path.stat().st_mtime,
    }


def collect_files(limit_files: int = 24) -> list[Path]:
    files: list[Path] = []
    for d in discover_dirs():
        files.extend(d.glob("*.txt"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit_files]


def list_light(limit: int = 24) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in collect_files(limit):
        row = summary(p)
        if row:
            out.append(row)
    return out


def list_full(limit: int = 12) -> list[dict[str, Any]]:
    return [parse_full(p) for p in collect_files(limit)]