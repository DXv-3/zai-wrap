"""CLI entry: serve | check | state | event."""
from __future__ import annotations

import json
import os
import sys

from bw.app import App
from bw.server import serve


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("Usage: python -m bw serve|check|state|event", file=sys.stderr)
        sys.exit(1)
    cmd = argv[0]
    app = App()

    if cmd == "check":
        report = app.preflight(require_port=False)
        print(json.dumps(report, indent=2))
        sys.exit(0 if report.get("ok") and not app.load_error else 1)
    if cmd == "serve":
        port = int(os.environ.get("BUILD_WATCH_PORT", "8790"))
        try:
            serve(app, port)
        except OSError as exc:
            print(f"cannot bind 127.0.0.1:{port}: {exc}", file=sys.stderr)
            sys.exit(1)
    elif cmd == "state":
        print(json.dumps(app.canvas_state(), indent=2))
    elif cmd == "event":
        _cmd_event(app, argv[1:])
    else:
        sys.exit(1)


def _cmd_event(app: App, args: list[str]) -> None:
    kind = "note"
    files: list[str] = []
    msg_parts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--kind", "-k") and i + 1 < len(args):
            kind = args[i + 1]
            i += 2
        elif a in ("--files", "-f") and i + 1 < len(args):
            files = [x.strip() for x in args[i + 1].split(",") if x.strip()]
            i += 2
        else:
            msg_parts.append(a)
            i += 1
    msg = " ".join(msg_parts)
    if not msg:
        print("event requires a message", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(app.store.append_event(kind, msg, files or None)))


if __name__ == "__main__":
    main()