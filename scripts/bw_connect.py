#!/usr/bin/env python3
"""Connect Grok session to watch dir (no shell injection)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent
if str(_SCRIPT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT))

from bw import grok
from bw.paths import resolve_watch, resolve_project
from bw.security import is_path_under, sanitize_session_id


def _resolve_watch_arg(arg: str | None) -> Path:
    project = resolve_project()
    expected = resolve_watch(project).resolve()
    if not arg:
        return expected
    watch = Path(arg).resolve()
    if watch == expected or is_path_under(project, watch):
        return watch
    print(
        json.dumps({"error": "watch_dir_outside_project", "project": str(project)}),
        file=sys.stderr,
    )
    sys.exit(1)


def main() -> None:
    watch = _resolve_watch_arg(sys.argv[1] if len(sys.argv) > 1 else None)
    sid = sanitize_session_id(sys.argv[2] if len(sys.argv) > 2 else "")
    if not sid:
        print(json.dumps({"error": "invalid session_id"}), file=sys.stderr)
        sys.exit(1)
    updates = grok.find_updates_path(sid)
    if not updates or not updates.is_file():
        print(
            json.dumps({"error": "updates_not_found", "session_id": sid}),
            file=sys.stderr,
        )
        sys.exit(1)
    n = grok.bootstrap_session(watch, sid)
    print(json.dumps({"session_id": sid, "ingested": n, "status": grok.grok_status(watch)}, indent=2))


if __name__ == "__main__":
    main()