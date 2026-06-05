#!/usr/bin/env python3
"""Smoke tests for build-watch v2 HTTP API.

Usage:
  python3 test_api.py                    # default http://127.0.0.1:8790
  python3 test_api.py --base http://127.0.0.1:8790
  BUILD_WATCH_PORT=8791 python3 test_api.py --base http://127.0.0.1:8791
  python3 test_api.py --skip-grok        # skip live Grok session tests

Exit 0 if all pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bw.constants import MAX_POST_BYTES

DEFAULT_BASE = f"http://127.0.0.1:{os.environ.get('BUILD_WATCH_PORT', '8790')}"


def http(
    base: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    raw: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    url = base.rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read() or b"{}")
            return resp.status, payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        raw_body = exc.read()
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {}
        return exc.code, payload if isinstance(payload, dict) else {}


class Runner:
    def __init__(self, base: str, *, skip_grok: bool) -> None:
        self.base = base
        self.skip_grok = skip_grok
        self.passed = 0
        self.failed = 0

    def ok(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"OK   {name}" + (f"  ({detail})" if detail else ""))
        else:
            self.failed += 1
            print(f"FAIL {name}" + (f"  ({detail})" if detail else ""))

    def expect_status(self, name: str, code: int, expect: int, extra: str = "") -> None:
        self.ok(name, code == expect, f"got={code} expect={expect} {extra}".strip())

    def run(self) -> int:
        print(f"build-watch API smoke tests → {self.base}\n")

        c, pl = http(self.base, "GET", "/api/health")
        self.expect_status("health", c, 200)
        self.ok("health_ok", pl.get("ok") is True, str(pl.get("version", "")))

        c, _ = http(self.base, "GET", "/api/state")
        self.expect_status("state", c, 200)

        c, pl = http(self.base, "GET", "/api/terminal/mirror")
        self.ok(
            "mirror",
            c in (200, 404),
            pl.get("error") or "has_mirror",
        )

        c, _ = http(self.base, "POST", "/api/settings", raw=b"not-json")
        self.expect_status("bad_json", c, 400)

        c, _ = http(self.base, "POST", "/api/settings", raw=b"x" * (MAX_POST_BYTES + 1))
        self.expect_status("oversize_body", c, 413)

        c, pl = http(
            self.base,
            "POST",
            "/api/file/save",
            {"path": "../../../etc/passwd", "content": "x"},
        )
        self.expect_status("save_bad_path", c, 400, str(pl.get("error")))

        c, pl = http(self.base, "POST", "/api/terminal/pin", {})
        self.expect_status("pin_empty", c, 400)

        c, pl = http(
            self.base,
            "POST",
            "/api/grok/connect",
            {"session_id": "deadbeef-dead-beef-dead-beefdeadbeef"},
        )
        self.expect_status("connect_missing_updates", c, 404, str(pl.get("error")))

        c, pl = http(self.base, "POST", "/api/terminal/pty/start")
        self.expect_status("pty_start", c, 200)
        if pl.get("ok"):
            c, _ = http(self.base, "GET", "/api/terminal/pty/poll")
            self.expect_status("pty_poll", c, 200)
        c, _ = http(self.base, "POST", "/api/terminal/pty/stop")
        self.expect_status("pty_stop", c, 200)

        if not self.skip_grok:
            self._grok_live_tests()
        else:
            print("SKIP grok live tests (--skip-grok)")

        print(f"\n--- {self.passed} passed, {self.failed} failed ---")
        return 0 if self.failed == 0 else 1

    def _grok_live_tests(self) -> None:
        active = Path.home() / ".grok/active_sessions.json"
        if not active.is_file():
            print("SKIP grok live (no ~/.grok/active_sessions.json)")
            return
        try:
            sessions = json.loads(active.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("SKIP grok live (invalid active_sessions.json)")
            return
        if not sessions:
            print("SKIP grok live (no sessions)")
            return
        sid = sessions[0].get("session_id")
        if not sid:
            print("SKIP grok live (no session_id)")
            return
        c, pl = http(self.base, "POST", "/api/grok/connect", {"session_id": sid})
        self.expect_status("connect_live", c, 200, f"ok={pl.get('ok')}")
        c, _ = http(self.base, "POST", "/api/grok/rebuild-turns", {"session_id": sid})
        self.expect_status("rebuild_live", c, 200)


def main() -> None:
    p = argparse.ArgumentParser(description="build-watch HTTP smoke tests")
    p.add_argument("--base", default=DEFAULT_BASE, help="Server base URL")
    p.add_argument("--skip-grok", action="store_true", help="Skip tests needing live Grok session")
    args = p.parse_args()
    sys.exit(Runner(args.base, skip_grok=args.skip_grok).run())


if __name__ == "__main__":
    main()