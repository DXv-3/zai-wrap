#!/usr/bin/env python3
"""
gateway_smoke_test.py — Test each configured model provider with one cheap call.

Usage:
  python3 ~/.grok/skills/zai-wrap/scripts/gateway_smoke_test.py
  python3 gateway_smoke_test.py --skip grok_api,kimi

Skips providers whose API key env vars are unset. Prints a summary table.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
from pathlib import Path

# Allow running from scripts/ dir or repo root
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from model_gateway import ModelGateway, ModelRouter, _BACKENDS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip", default="", help="Comma-separated providers to skip")
    parser.add_argument("--prompt", default="Reply with exactly: GATEWAY_OK")
    args = parser.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    gw = ModelGateway()
    results = []

    print(f"\n{'Provider':<14} {'Model':<28} {'Status':<10} {'Latency':>10}  Notes")
    print("-" * 72)

    for provider, cfg in _BACKENDS.items():
        if provider in skip:
            results.append((provider, cfg["default_model"], "SKIPPED", 0, "--skip flag"))
            print(f"{provider:<14} {cfg['default_model']:<28} {'SKIPPED':<10} {'':>10}  --skip flag")
            continue

        key_env = cfg.get("key_env")
        if key_env and not os.environ.get(key_env):
            results.append((provider, cfg["default_model"], "NO_KEY", 0, f"{key_env} not set"))
            print(f"{provider:<14} {cfg['default_model']:<28} {'NO_KEY':<10} {'':>10}  {key_env} not set")
            continue

        t0 = time.monotonic()
        try:
            resp = gw.call(args.prompt, model=f"{provider}/{cfg['default_model']}")
            latency = (time.monotonic() - t0) * 1000
            if resp.ok:
                status = "OK"
                notes = resp.text.strip()[:40]
            else:
                status = "FAIL"
                notes = resp.error[:40]
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            status = "ERROR"
            notes = str(exc)[:40]

        results.append((provider, cfg["default_model"], status, latency, notes))
        status_icon = "✓" if status == "OK" else "✗"
        print(f"{provider:<14} {cfg['default_model']:<28} {status_icon+status:<10} {latency:>8.0f}ms  {notes}")

    ok = sum(1 for r in results if r[2] == "OK")
    total_tested = sum(1 for r in results if r[2] not in ("SKIPPED", "NO_KEY"))
    print(f"\n{ok}/{total_tested} providers operational")

    if ok == 0 and total_tested > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
