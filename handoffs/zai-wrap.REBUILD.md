# REBUILD — zai-wrap + build-watch v2

## What to build

A **local-first agent visibility system** for macOS:

1. **zai-wrap** — CLI that prints 7-section prompts (system + visibility + task) for Z.AI / GLM coding tools.
2. **build-watch** — Python HTTP server on `127.0.0.1:8790` + `canvas.html` dashboard.
3. **grok-bridge** — Incrementally ingest Grok Build `updates.jsonl` into watch-dir JSONL + canvas turns.

## Reverse-engineered intent

> I want to see what my coding agents are doing while they work — terminal output, file edits, git status, preview URLs, and Grok tool calls — in one browser tab. I also want copy-paste prompts tuned for Z.AI that tell the agent to emit build events. The stack must run locally on a Mac with minimal deps (stdlib HTTP + optional `say` for TTS), store state in `.build-watch/`, and never expose the server beyond localhost.

## Stack

| Layer | Tech |
|-------|------|
| Server | Python 3.10+, `http.server.ThreadingHTTPServer` |
| UI | Static HTML/JS `canvas.html` |
| CLI | bash `build-watch`, `zai-wrap` + `python3 -m bw` |
| TTS | macOS `say` or external shell hook |
| Grok | Read-only tail of `updates.jsonl` |

## Root layout (install tree)

```
~/.grok/skills/zai-wrap/
├── SKILL.md
├── handoffs/          ← this bundle
├── prompts/
│   ├── system.md
│   ├── visibility.md
│   └── build-session.md
├── references/
│   ├── VOICE_CLONING.md
│   └── GITHUB_MORPH_LIST_B.md
├── static/
│   ├── canvas.html      # primary UI
│   └── dashboard.html   # legacy/simple
└── scripts/
    ├── build-watch      # bash dispatcher
    ├── build_watch.py   # shim → bw.cli
    ├── zai-wrap
    ├── lib.sh
    ├── bw_connect.py
    ├── grok_bridge.py   # shim
    ├── test_api.py
    ├── tts_external.sh
    ├── pack_handoff.sh
    └── bw/
        ├── __main__.py
        ├── cli.py
        ├── app.py
        ├── server.py
        ├── grok.py
        ├── storage.py
        ├── paths.py
        ├── security.py
        ├── terminal.py
        ├── terminals.py
        ├── previews.py
        ├── tts.py
        ├── cache.py
        ├── boot.py
        └── constants.py
```

## Build steps (ordered)

1. Implement `bw/constants.py` limits + `DEFAULT_SETTINGS`.
2. Implement `bw/security.py` sanitizers + `parse_json_object`.
3. Implement `bw/paths.py` `PathPolicy`, `resolve_project`, `resolve_watch`.
4. Implement `bw/storage.py` JSONL append with locks.
5. Implement `bw/grok.py` — find updates, ingest, turns builder, rebuild.
6. Implement `bw/terminal.py` + `terminals.py`.
7. Implement `bw/previews.py` + `bw/cache.py`.
8. Implement `bw/tts.py` (say + optional external).
9. Implement `bw/app.py` orchestration + `_grok_lock`.
10. Implement `bw/server.py` full route table + error semantics.
11. Implement `bw/cli.py` + `bw/boot.py`.
12. Wire bash CLIs + shims.
13. Build `static/canvas.html` polling `/api/state`.
14. Add `test_api.py` smoke tests.

## Verification

```bash
export PATH="$HOME/.grok/bin:$PATH"
cd <project>
build-watch check
build-watch on
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BUILD_WATCH_PORT` | `8790` | HTTP port |
| `BUILD_WATCH_DIR` | `.build-watch` | Watch directory name/path |
| `BUILD_WATCH_PROJECT` | auto-detect | Project root |
| `GROK_SESSION_ID` | — | Force session |
| `BUILD_WATCH_GROK_SYNC` | `1` | Mirror grok edits to events |
| `BUILD_WATCH_TTS_BACKEND` | `say` | or `external` |
| `BUILD_WATCH_TTS_CMD` | — | External TTS shell command |
| `BUILD_WATCH_VOICE_REF` | — | Reference WAV for clone backend |

## API contract

See `zai-wrap.HANDOFF.md` § HTTP API — must match exactly for canvas compatibility.

## Do not

- Bind `0.0.0.0` without authentication.
- Skip path policy on file read/write.
- Return `None` from JSON handlers (always dict + proper status).
- Block HTTP keep-alive on truncated POST bodies (return 413 + drain).