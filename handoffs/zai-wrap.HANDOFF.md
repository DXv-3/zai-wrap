# Git Handoff — vinnygilberti/zai-wrap (build-watch v2)

**Generated:** 2026-06-05  
**Paste this file (or the tarball from `pack_handoff.sh`) into any LLM to operate or rebuild the system.**

> **Read first:** `zai-wrap.AGENT.md` · **Recreate:** `zai-wrap.REBUILD.md` · **Architecture:** `zai-wrap.EXPLAIN.md`

---

## Service map (local + ecosystem)

| Lens | URL / path |
|------|------------|
| **Install** | `~/.grok/skills/zai-wrap/` |
| **Canvas** | http://127.0.0.1:8790/ |
| **Skill** | `~/.grok/skills/zai-wrap/SKILL.md` |
| **Handoff pack** | `~/.grok/skills/zai-wrap/handoffs/` |
| **Grok sessions** | `~/.grok/sessions/*/updates.jsonl` |
| **Git handoff hub** | `~/Documents/gitreverse/` (GIT_HANDOFF_MASTER.md) |
| **Gitingest** (other repos) | `https://gitingest.com/{owner}/{repo}` |
| **GitReverse** (other repos) | `https://gitreverse.com/{owner}/{repo}` |

---

## Repo card

```json
{
  "identity": {
    "slug": "vinnygilberti/zai-wrap",
    "name": "zai-wrap",
    "type": "local-grok-skill",
    "version": "2.0.0",
    "primary_language": "Python",
    "platform": "macOS"
  },
  "purpose": "Z.AI prompt wrappers + build-watch live dashboard for Grok/agent coding visibility",
  "stack": {
    "server": "Python 3.10+ stdlib HTTP",
    "ui": "static/canvas.html",
    "cli": "bash + python3 -m bw",
    "tts": "macOS say or BUILD_WATCH_TTS_CMD"
  },
  "root_tree_depth_1": "SKILL.md, handoffs/, prompts/, references/, scripts/, static/",
  "how_to_use_as_block": "Install to ~/.grok/skills/zai-wrap, symlink build-watch and zai-wrap to ~/.grok/bin, run build-watch on from project, connect Grok session, use zai-wrap compose for Z.AI tasks."
}
```

---

## System overview (three products)

### 1. zai-wrap (prompts)

Composes **system** + **visibility contract** + **task** for GLM/Z.AI coding tools.

| File | Role |
|------|------|
| `prompts/system.md` | Agent behavior preamble |
| `prompts/visibility.md` | Obligation to emit build-watch events |
| `prompts/build-session.md` | Session template |
| `scripts/zai-wrap` | CLI: `compose`, `system`, `visibility`, `init` |

### 2. build-watch (dashboard)

| File | Role |
|------|------|
| `scripts/build-watch` | bash: `on`, `serve`, `status`, `event`, `connect`, `grok`, `off`, `check` |
| `scripts/build_watch.py` | Shim → `bw.cli` |
| `scripts/bw/*` | Python package (server, grok, storage, …) |
| `static/canvas.html` | Browser UI |

### 3. grok-bridge (ingest)

| File | Role |
|------|------|
| `scripts/bw/grok.py` | Core bridge logic |
| `scripts/bw_connect.py` | CLI connect (no shell injection) |
| `scripts/grok_bridge.py` | Shim for status JSON |

---

## HTTP API (build-watch v2)

Base: `http://127.0.0.1:{BUILD_WATCH_PORT}` default **8790**.  
All JSON responses are **objects** (never bare `null`).  
POST bodies: max **4_000_000** bytes; oversize → **413** `payload_too_large`.

### GET

| Path | Description |
|------|-------------|
| `/`, `/index.html`, `/canvas` | `canvas.html` |
| `/api/health` | Preflight report, version 2.0.0 |
| `/api/state` | Full canvas state (calls `grok_tick`) |
| `/api/canvas` | Same as canvas slice of state |
| `/api/events` | `{ "events": [...] }` |
| `/api/settings` | Current settings |
| `/api/tts/status` | `{ "playing": bool }` |
| `/api/grok/status` | Grok bridge status (503 if load_error) |
| `/api/grok/sessions` | Active sessions list |
| `/api/grok/voices` | Siri / resolved voice meta |
| `/api/grok/activity` | Recent activities |
| `/api/grok/turns?limit=80` | Parsed turns |
| `/api/terminal/list` | Light terminal list |
| `/api/terminal/mirror?pin=` | Mirror payload or 404 `no_terminal` |
| `/api/terminal/pty/poll` | PTY output drain |
| `/api/file?path=` | UTF-8 file slice (policy-checked) |
| `/api/raw?path=` | Raw bytes (capped) |

### POST

| Path | Body | Notes |
|------|------|-------|
| `/api/settings` | settings patch | Whitelisted keys only |
| `/api/tts` | `{ text, voice?, rate? }` | Starts `say` or external |
| `/api/tts/stop` | — | Stop TTS |
| `/api/file/save` | `{ path, content }` | 400 on invalid_path |
| `/api/grok/connect` | `{ session_id? }` | 404 `updates_not_found`; uses lock |
| `/api/grok/rebuild-turns` | `{ session_id? }` | Rebuild turns.jsonl under lock |
| `/api/terminal/pin` | `{ path }` or `{ content, snapshot_name? }` | 400 if empty |
| `/api/terminal/pty/start` | — | 503 `pty_unavailable` on OSError |
| `/api/terminal/pty/stop` | — | |
| `/api/terminal/pty/input` | `{ data: string }` | |
| `/api/dictation` | `{ text }` | Appends dictation.jsonl |
| `/api/event` | `{ kind, msg, files? }` | Appends events.jsonl |

### Canvas state shape (`/api/state`)

Key fields: `ts`, `project`, `previews`, `artifacts`, `events`, `terminals`, `git`, `grok`, `grok_activity`, `turns`, `settings`, `tts`, `boot`.

---

## Visibility contract (agents)

Emit progress for the dashboard:

```bash
build-watch event "Started auth middleware" --files src/auth.py
build-watch event "Tests green" --kind test
```

JSONL line in `.build-watch/events.jsonl`:

```json
{"ts":"2026-06-05T12:00:00Z","kind":"edit","msg":"Saved handler","files":["src/handler.py"]}
```

**Kinds:** `plan`, `edit`, `test`, `cmd`, `note`, `done`.

---

## Grok bridge protocol

1. **Resolve session:** `GROK_SESSION_ID` env → `.build-watch/grok_session.json` → newest `~/.grok/active_sessions.json`.
2. **Find updates:** `~/.grok/sessions/%2FUsers%2F.../<session_id>/updates.jsonl` (glob).
3. **Ingest:** Read from byte offset in `grok_offset.txt`; append activities; update turn builder state.
4. **Rebuild:** Truncate `turns.jsonl`, replay full updates (must hold `_grok_lock`).
5. **Sync:** Optional mirror of edit/shell activities into `events.jsonl` (`BUILD_WATCH_GROK_SYNC=1`).

**Update kinds handled for turns:** `agent_message_chunk`, `thought`, `tool_call`, shell/write/read/strreplace patterns (see `bw/grok.py`).

---

## Security model

- Bind **127.0.0.1** only.
- `PathPolicy`: no `..`, reject symlinks for project files.
- Terminals: only under `~/.grok` or watch dir.
- `sanitize_session_id`: `^[a-f0-9-]{8,64}$`.
- POST JSON via `parse_json_object`; invalid → 400.
- `_grok_json`: non-dict → 500 `invalid_response`.

---

## TTS backends

| Mode | Config |
|------|--------|
| **say** (default) | macOS voices, Siri Voice 2 preference |
| **external** | `BUILD_WATCH_TTS_BACKEND=external` + `BUILD_WATCH_TTS_CMD` |

Clone research: `references/VOICE_CLONING.md` (OpenVoice, Qwen3-TTS, voicebox, GPT-SoVITS).  
Template script: `scripts/tts_external.sh`.

---

## CLI reference

### build-watch

```bash
build-watch on          # init + serve + open browser
build-watch serve       # foreground server
build-watch check       # JSON preflight
build-watch status
build-watch event "msg" [--kind edit] [--files a,b]
build-watch connect [session_id]
build-watch grok
build-watch off
```

### zai-wrap

```bash
zai-wrap compose "task"
zai-wrap system
zai-wrap visibility
zai-wrap init            # mkdir .build-watch
```

### Python

```bash
python3 -m bw serve|check|state|event
python3 scripts/test_api.py [--skip-grok] [--base URL]
python3 scripts/bw_connect.py <watch_dir> <session_id>
```

---

## Shims (backward compatibility)

| Shim | Delegates to |
|------|----------------|
| `build_watch.py` | `bw.cli` |
| `grok_bridge.py` | `bw.grok` |
| `bw_boot.py` | `bw.boot` |
| `terminal_embed.py` | `bw.terminal` |
| `bw_common.py` | re-exports from `bw.*` |

---

## Testing & review history

- **Smoke:** `scripts/test_api.py` — 14 tests (health, state, 413, 404 connect, PTY, live grok).
- **Review (2026-06-05):** server None-guards, POST drain, grok lock, PTY lock, `import sys`, file save 400, bw_connect path policy.

---

## GitHub morph / discovery (extension)

- **List A:** broad search topics (conversation).
- **List B:** `references/GITHUB_MORPH_LIST_B.md` — atoms to extract, compose recipes, morph queries.

Pipeline: `gitsimilar → gitingest → /github-morph extract → morph into bw/*`.

---

## Download / handoff for any LLM

### Option A — tarball (recommended)

```bash
~/.grok/skills/zai-wrap/scripts/pack_handoff.sh
# Creates ~/Downloads/zai-wrap-handoff-2.0.0.tar.gz (or cwd)
```

Contents: `handoffs/`, `SKILL.md`, `prompts/`, `references/`, `scripts/` (no `__pycache__`), `static/`.

### Option B — copy handoffs only

```bash
cp -r ~/.grok/skills/zai-wrap/handoffs ~/Downloads/zai-wrap-handoffs
```

Paste `zai-wrap.AGENT.md` + `zai-wrap.HANDOFF.md` into the model.

### Option C — git-handoff hub

```bash
cp ~/.grok/skills/zai-wrap/handoffs/* ~/Documents/gitreverse/handoffs/
```

### Option D — GitHub + gitingest (published)

- **Repo:** https://github.com/DXv-3/zai-wrap
- **Ingest:** https://gitingest.com/DXv-3/zai-wrap
- **Reverse:** https://gitreverse.com/DXv-3/zai-wrap

---

## Rebuild prompt (short)

Build a macOS-local agent dashboard at port 8790: stdlib Python HTTP server, JSON API, static canvas polling `/api/state`, `.build-watch/` JSONL event log, Grok `updates.jsonl` tail ingest, path sandbox, macOS TTS with optional external clone command, bash CLIs `build-watch` and `zai-wrap`, smoke test script, and git-handoff documentation in `handoffs/`. Version 2.0.0. Thread-safe grok ingest and PTY. Return 413 on oversized POST bodies.

---

## File index (source of truth)

| Path | ~lines | Summary |
|------|--------|---------|
| `scripts/bw/server.py` | 340 | HTTP routes |
| `scripts/bw/grok.py` | 570 | Session bridge |
| `scripts/bw/app.py` | 130 | App core |
| `scripts/bw/storage.py` | 140 | JSONL store |
| `scripts/bw/terminal.py` | 220 | PTY + pin |
| `scripts/bw/security.py` | 120 | Sanitizers |
| `scripts/bw/tts.py` | 260 | TTS |
| `static/canvas.html` | large | UI |
| `scripts/test_api.py` | 120 | Smoke tests |

---

*End of handoff — vinnygilberti/zai-wrap build-watch v2.0.0*