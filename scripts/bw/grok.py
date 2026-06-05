#!/usr/bin/env python3
"""Bridge Grok Build session updates.jsonl → build-watch canvas."""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bw.security import sanitize_session_id
from bw.storage import tail_jsonl

GROK_HOME = Path.home() / ".grok"
SESSIONS_ROOT = GROK_HOME / "sessions"
ACTIVE_FILE = GROK_HOME / "active_sessions.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode_cwd(cwd: str) -> str:
    return cwd.replace("/", "%2F")


def find_updates_path(session_id: str) -> Path | None:
    session_id = sanitize_session_id(session_id) or ""
    if not session_id:
        return None
    candidates = list(SESSIONS_ROOT.glob(f"*/{session_id}/updates.jsonl"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return None


def load_active_sessions() -> list[dict[str, Any]]:
    if not ACTIVE_FILE.is_file():
        return []
    try:
        data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def resolve_session_id(watch_dir: Path) -> str | None:
    if sid := sanitize_session_id(os.environ.get("GROK_SESSION_ID")):
        return sid
    link = watch_dir / "grok_session.json"
    if link.is_file():
        try:
            data = json.loads(link.read_text(encoding="utf-8"))
            return sanitize_session_id(str(data.get("session_id") or ""))
        except json.JSONDecodeError:
            pass
    sessions = load_active_sessions()
    if not sessions:
        return None
    # Most recently opened
    sessions.sort(key=lambda s: s.get("opened_at", ""), reverse=True)
    return sanitize_session_id(str(sessions[0].get("session_id") or ""))


def save_session_link(watch_dir: Path, session_id: str) -> None:
    session_id = sanitize_session_id(session_id) or ""
    if not session_id:
        return
    watch_dir.mkdir(parents=True, exist_ok=True)
    path = watch_dir / "grok_session.json"
    updates = find_updates_path(session_id)
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "updates_path": str(updates) if updates else None,
                "linked_at": _utc_now(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def activity_path(watch_dir: Path) -> Path:
    return watch_dir / "grok_activity.jsonl"


def offset_path(watch_dir: Path) -> Path:
    return watch_dir / "grok_updates.offset"


def turns_path(watch_dir: Path) -> Path:
    return watch_dir / "turns.jsonl"


def turn_state_path(watch_dir: Path) -> Path:
    return watch_dir / "grok_turn_state.json"


MAX_TURN_FIELD = 50_000


def _append_text(existing: str, chunk: str, limit: int = MAX_TURN_FIELD) -> str:
    combined = (existing or "") + (chunk or "")
    return combined[:limit] if len(combined) > limit else combined


def append_turn(watch_dir: Path, turn: dict[str, Any]) -> None:
    tp = turns_path(watch_dir)
    tp.parent.mkdir(parents=True, exist_ok=True)
    with tp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")


def load_turns(watch_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    return tail_jsonl(turns_path(watch_dir), limit)


class TurnBuilder:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id or "unknown"
        self.counter = 0
        self.current: dict[str, Any] | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "counter": self.counter,
            "current": self.current,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> TurnBuilder:
        b = cls(str(data.get("session_id") or "unknown"))
        b.counter = int(data.get("counter") or 0)
        cur = data.get("current")
        b.current = cur if isinstance(cur, dict) else None
        return b


def save_turn_state(watch_dir: Path, builder: TurnBuilder) -> None:
    turn_state_path(watch_dir).write_text(
        json.dumps(builder.to_state(), indent=2),
        encoding="utf-8",
    )


def load_turn_builder(watch_dir: Path, session_id: str) -> TurnBuilder:
    p = turn_state_path(watch_dir)
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("session_id") == session_id:
                return TurnBuilder.from_state(data)
        except json.JSONDecodeError:
            pass
    return TurnBuilder(session_id)


def finalize_turn(watch_dir: Path, builder: TurnBuilder) -> dict[str, Any] | None:
    cur = builder.current
    if not cur:
        return None
    if not (cur.get("user_text") or cur.get("agent_text") or cur.get("thought_text")):
        builder.current = None
        return None
    cur["ts_end"] = _utc_now()
    cur.pop("_streaming_user", None)
    append_turn(watch_dir, cur)
    finished = cur
    builder.current = None
    return finished


def _ensure_open_turn(builder: TurnBuilder, model: str = "", prompt_id: str = "") -> dict[str, Any]:
    if builder.current:
        return builder.current
    builder.counter += 1
    builder.current = {
        "turn_id": f"{builder.session_id}-turn-{builder.counter}",
        "ts_start": _utc_now(),
        "user_text": "",
        "thought_text": "",
        "agent_text": "",
        "tool_ids": [],
        "model": model,
        "prompt_id": prompt_id,
    }
    return builder.current


def process_update_for_turns(
    builder: TurnBuilder, obj: dict[str, Any], watch_dir: Path
) -> dict[str, Any] | None:
    """Update turn accumulator; returns finalized turn when a new user message starts."""
    params = obj.get("params") or {}
    update = params.get("update") or {}
    kind = update.get("sessionUpdate") or ""
    meta = obj.get("_meta") or update.get("_meta") or {}
    model = str(meta.get("modelId") or "")
    prompt_id = str(meta.get("promptId") or "")
    finalized: dict[str, Any] | None = None

    if kind == "user_message_chunk":
        text = _text_from_content(update.get("content"))
        if not text.strip():
            return None
        cur_open = builder.current
        if cur_open and cur_open.get("_streaming_user"):
            cur_open["user_text"] = _append_text(cur_open.get("user_text", ""), text)
            if model:
                cur_open["model"] = model
            if prompt_id:
                cur_open["prompt_id"] = prompt_id
            return None
        finalized = finalize_turn(watch_dir, builder)
        builder.counter += 1
        builder.current = {
            "turn_id": f"{builder.session_id}-turn-{builder.counter}",
            "ts_start": _utc_now(),
            "user_text": text,
            "thought_text": "",
            "agent_text": "",
            "tool_ids": [],
            "model": model,
            "prompt_id": prompt_id,
            "_streaming_user": True,
        }
        return finalized

    cur = _ensure_open_turn(builder, model, prompt_id)
    cur.pop("_streaming_user", None)
    if model:
        cur["model"] = model
    if prompt_id:
        cur["prompt_id"] = prompt_id

    if kind == "agent_thought_chunk":
        text = _text_from_content(update.get("content"))
        if text.strip():
            cur["thought_text"] = _append_text(cur.get("thought_text", ""), text)
    elif kind == "agent_message_chunk":
        text = _text_from_content(update.get("content"))
        if text.strip():
            cur["agent_text"] = _append_text(cur.get("agent_text", ""), text)
    elif kind == "tool_call":
        tid = update.get("toolCallId")
        if tid and tid not in cur["tool_ids"]:
            cur["tool_ids"].append(tid)

    return None


def rebuild_turns(watch_dir: Path, session_id: str | None = None) -> int:
    """Rebuild turns.jsonl from full updates.jsonl."""
    sid = sanitize_session_id(session_id or "") or resolve_session_id(watch_dir)
    if not sid:
        return 0
    updates_file = find_updates_path(sid)
    if not updates_file or not updates_file.is_file():
        return 0

    tp = turns_path(watch_dir)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text("", encoding="utf-8")
    builder = TurnBuilder(sid)
    n = 0
    with updates_file.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            process_update_for_turns(builder, obj, watch_dir)
            n += 1
    finalize_turn(watch_dir, builder)
    save_turn_state(watch_dir, builder)
    return n


def append_activity(watch_dir: Path, item: dict[str, Any]) -> None:
    ap = activity_path(watch_dir)
    ap.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(item, ensure_ascii=False) + "\n"
    with ap.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def load_activities(watch_dir: Path, limit: int = 120) -> list[dict[str, Any]]:
    return tail_jsonl(activity_path(watch_dir), limit)


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                inner = c.get("content")
                if isinstance(inner, dict) and inner.get("type") == "text":
                    parts.append(inner.get("text", ""))
                elif isinstance(inner, str):
                    parts.append(inner)
        return "".join(parts)
    if isinstance(content, dict) and content.get("type") == "text":
        return content.get("text", "")
    return ""


def _extract_shell_output(update: dict[str, Any]) -> str:
    ro = update.get("rawOutput") or {}
    if isinstance(ro, dict):
        if ro.get("type") == "Bash":
            return (ro.get("output_for_prompt") or ro.get("output") or "")[:8000]
        # CursorShell variant
        if "output_for_prompt" in ro:
            return str(ro.get("output_for_prompt", ""))[:8000]
    content = update.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                inner = block.get("content")
                if isinstance(inner, dict) and inner.get("type") == "text":
                    return inner.get("text", "")[:8000]
    return ""


def _extract_write_code(update: dict[str, Any]) -> tuple[str | None, str]:
    ri = update.get("rawInput") or {}
    path = ri.get("path") or ""
    contents = ri.get("contents") or ri.get("content") or ""
    if not contents and update.get("content"):
        contents = _text_from_content(update.get("content"))
    ro = update.get("rawOutput") or {}
    if isinstance(ro, dict):
        fc = ro.get("FileContent") or ro.get("fileContent") or {}
        if isinstance(fc, dict) and fc.get("content"):
            contents = fc["content"]
    return path or None, (contents or "")[:12000]


def _extract_strreplace(update: dict[str, Any]) -> tuple[str | None, str]:
    ri = update.get("rawInput") or {}
    path = ri.get("path") or ""
    new = ri.get("new_string") or ri.get("newString") or ""
    return path or None, new[:12000]


def parse_update_record(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn one updates.jsonl line into 0..n activity records."""
    params = obj.get("params") or {}
    update = params.get("update") or {}
    kind = update.get("sessionUpdate") or ""
    meta = obj.get("_meta") or update.get("_meta") or {}
    model = meta.get("modelId") or params.get("modelId") or ""
    ts = _utc_now()
    out: list[dict[str, Any]] = []

    if kind == "user_message_chunk":
        text = _text_from_content(update.get("content"))
        if text.strip():
            out.append(
                {
                    "ts": ts,
                    "type": "user",
                    "title": "You",
                    "status": "completed",
                    "text": text[:2000],
                    "model": model,
                }
            )
        return out

    if kind == "agent_message_chunk":
        text = _text_from_content(update.get("content"))
        if text.strip():
            out.append(
                {
                    "ts": ts,
                    "type": "agent",
                    "title": "Grok",
                    "status": "completed",
                    "text": text[:2000],
                    "model": model,
                }
            )
        return out

    if kind == "tool_call":
        title = update.get("title") or "Tool"
        raw = update.get("rawInput") or {}
        item: dict[str, Any] = {
            "ts": ts,
            "type": _tool_type(title),
            "title": title,
            "status": "running",
            "tool_id": update.get("toolCallId"),
            "model": model,
        }
        if title == "Shell":
            item["command"] = raw.get("command") or raw.get("description") or ""
        elif title in ("Write", "StrReplace"):
            item["path"] = raw.get("path") or ""
        elif title == "Read":
            item["path"] = raw.get("path") or ""
        elif title == "Grep":
            item["pattern"] = raw.get("pattern") or ""
        out.append(item)
        return out

    if kind == "tool_call_update":
        title = update.get("title") or update.get("kind") or "Tool"
        status_raw = (update.get("status") or "").lower()
        status = "completed" if status_raw in ("completed", "complete") else (
            "failed" if status_raw in ("failed", "error") else "running"
        )
        item: dict[str, Any] = {
            "ts": ts,
            "type": _tool_type(str(title)),
            "title": str(title),
            "status": status,
            "tool_id": update.get("toolCallId"),
            "model": model,
        }
        if str(title) == "Shell" or update.get("kind") == "execute":
            item["command"] = (update.get("rawInput") or {}).get("command", "")
            out_text = _extract_shell_output(update)
            if out_text:
                item["output"] = out_text
        elif str(title) == "Write":
            path, code = _extract_write_code(update)
            if path:
                item["path"] = path
            if code:
                item["code"] = code
        elif str(title) == "StrReplace":
            path, code = _extract_strreplace(update)
            if path:
                item["path"] = path
            if code:
                item["code"] = code
        elif str(title) in ("Read", "read"):
            locs = update.get("locations") or []
            if locs and isinstance(locs[0], dict):
                item["path"] = locs[0].get("path", "")
            path, code = _extract_write_code(update)
            if code and not item.get("code"):
                item["code"] = code[:4000]
        out.append(item)
        return out

    return out


def _tool_type(title: str) -> str:
    t = title.lower()
    if t == "shell":
        return "shell"
    if t in ("write", "strreplace"):
        return "edit"
    if t == "read":
        return "read"
    return "tool"


def bootstrap_session(watch_dir: Path, session_id: str, tail_bytes: int = 600_000) -> int:
    """Ingest recent history from updates.jsonl (last tail_bytes)."""
    session_id = sanitize_session_id(session_id) or ""
    if not session_id:
        return 0
    updates_file = find_updates_path(session_id)
    if not updates_file or not updates_file.is_file():
        return 0
    save_session_link(watch_dir, session_id)
    size = updates_file.stat().st_size
    start = max(0, size - tail_bytes)
    offset_path(watch_dir).write_text(str(start), encoding="utf-8")
    rebuild_turns(watch_dir, session_id)
    return ingest_updates(watch_dir, session_id)


def ingest_updates(watch_dir: Path, session_id: str | None = None) -> int:
    """Read new lines from updates.jsonl; append activities. Returns count ingested."""
    sid = sanitize_session_id(session_id or "") or resolve_session_id(watch_dir)
    if not sid:
        return 0
    updates_file = find_updates_path(sid)
    if not updates_file or not updates_file.is_file():
        return 0

    off_file = offset_path(watch_dir)
    offset = 0
    if off_file.is_file():
        try:
            offset = int(off_file.read_text().strip())
        except ValueError:
            offset = 0

    size = updates_file.stat().st_size
    if offset > size:
        offset = 0

    builder = load_turn_builder(watch_dir, sid)
    ingested = 0
    with updates_file.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            process_update_for_turns(builder, obj, watch_dir)
            for act in parse_update_record(obj):
                append_activity(watch_dir, act)
                ingested += 1
        new_offset = f.tell()

    off_file.write_text(str(new_offset), encoding="utf-8")
    save_turn_state(watch_dir, builder)
    return ingested


def grok_status(watch_dir: Path) -> dict[str, Any]:
    sid = resolve_session_id(watch_dir)
    updates = find_updates_path(sid) if sid else None
    sessions = load_active_sessions()
    return {
        "connected": bool(sid and updates and updates.is_file()),
        "session_id": sid,
        "updates_path": str(updates) if updates else None,
        "active_sessions": sessions,
        "activity_count": len(load_activities(watch_dir)),
        "turn_count": len(load_turns(watch_dir, 500)),
        "terminals_dir": str(Path.home() / ".grok" / "projects"),
    }


def sync_to_build_events(watch_dir: Path, append_event_fn) -> None:
    """Mirror latest grok edit/shell activities into build-watch events (dedupe)."""
    seen_file = watch_dir / "grok_synced.ids"
    seen: set[str] = set()
    if seen_file.is_file():
        seen = {x.strip() for x in seen_file.read_text().splitlines() if x.strip()}

    for act in load_activities(watch_dir, 20):
        aid = act.get("tool_id") or f"{act.get('ts')}-{act.get('title')}-{act.get('path','')}"
        if aid in seen or act.get("status") != "completed":
            continue
        kind = "cmd" if act.get("type") == "shell" else "edit" if act.get("type") == "edit" else "note"
        msg = act.get("command") or act.get("text") or f"{act.get('title')} {act.get('path','')}".strip()
        if not msg:
            continue
        files = [act["path"]] if act.get("path") else None
        append_event_fn(kind, msg[:300], files)
        seen.add(aid)
        if len(seen) > 500:
            seen = set(list(seen)[-300:])

    seen_file.write_text("\n".join(seen) + "\n", encoding="utf-8")