---
name: zai-wrap
description: >
  Wrapper prompt system for Z.AI (GLM Coding Plan) plus build-watch — live terminal/git
  dashboard so you see what agents build while they work. Use for z.ai, GLM, Cline,
  Claude Code with z.ai endpoint, build visibility, terminal mirror, or /zai-wrap.
metadata:
  short-description: "Z.AI prompt wrappers + live build dashboard"
---

# zai-wrap — Z.AI Prompt Wrappers + Build Watch

Two pieces that work together:

1. **Wrapper prompts** — 7-section tasks tuned for GLM-5.1 / Coding Plan, with a **visibility contract** so the model reports progress you can see on the dashboard.
2. **build-watch canvas** — Lovable/Grok-style UI (`http://127.0.0.1:8790`): **Read tab** (turn cards, thinking, copy, **Siri Voice 2** listen), **Grok Build**, preview, document/code, build stream.
3. **grok-bridge** — Tails `~/.grok/sessions/.../updates.jsonl` from your active Grok Build session (Shell, Write, StrReplace, Read).

## Handoff (any LLM download)

Full git-handoff bundle: `handoffs/zai-wrap.AGENT.md` (read first) + `handoffs/zai-wrap.HANDOFF.md`.

```bash
bash ~/.grok/skills/zai-wrap/scripts/pack_handoff.sh
# → ~/Downloads/zai-wrap-handoff-2.0.0.tar.gz
```

See `handoffs/MANIFEST.md` for upload / gitingest options.

## Quick start

```bash
# Install CLI (once)
mkdir -p ~/.grok/bin
ln -sf ~/.grok/skills/zai-wrap/scripts/zai-wrap ~/.grok/bin/zai-wrap
ln -sf ~/.grok/skills/zai-wrap/scripts/build-watch ~/.grok/bin/build-watch
export PATH="$HOME/.grok/bin:$PATH"

# From your project
cd ~/Documents/gitreverse
build-watch on                    # opens canvas + auto-connects Grok Build
build-watch connect               # link session (or pass session_id)
zai-wrap compose "add auth middleware"   # copy prompt → paste in Cline/Claude Code (z.ai)
```

## Z.AI setup (Coding Plan)

Point your coding tool at Z.AI (see [docs.z.ai/devpack](https://docs.z.ai/devpack/overview)):

- **Coding endpoint:** `https://api.z.ai/api/coding/paas/v4` (for supported tools only)
- **General API:** `https://api.z.ai/api/paas/v4`
- Models: `glm-5.1`, `glm-4.7`, etc.

Wrapper prompts assume you paste into **Claude Code, Cline, OpenCode, Roo**, or similar — not raw SDK unless you add your own hooks.

## Wrapper commands

| Command | Purpose |
|---------|---------|
| `zai-wrap compose "task"` | Full session prompt (system + task + visibility) |
| `zai-wrap system` | System preamble only |
| `zai-wrap visibility` | Visibility contract only |
| `zai-wrap init` | Create `.build-watch/` in project |

## API smoke tests

After server changes:

```bash
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py --skip-grok
```

## Custom / cloned voices (local, free)

Default TTS is macOS `say` (Siri Voice 2). For **local voice cloning**, see [references/VOICE_CLONING.md](references/VOICE_CLONING.md) (OpenVoice, Qwen3-TTS, voicebox, GPT-SoVITS, RVC). Hook via:

```bash
export BUILD_WATCH_TTS_BACKEND=external
export BUILD_WATCH_TTS_CMD="$HOME/.grok/skills/zai-wrap/scripts/tts_external.sh"
export BUILD_WATCH_VOICE_REF="$PWD/.build-watch/voices/reference.wav"
```

Use only audio you have rights to clone (see legal note in that doc).

## Visibility contract (for any agent)

Agents working with build-watch should append one JSON line per meaningful step:

```bash
build-watch event "Started auth middleware" --files src/hub_auth.py
build-watch event "Tests green" --kind test
```

Or append manually to `.build-watch/events.jsonl`:

```json
{"ts":"2026-06-04T12:00:00Z","kind":"edit","msg":"Added rate limiter","files":["hub_rate_limit.py"]}
```

Kinds: `plan`, `edit`, `test`, `cmd`, `note`, `done`.

## build-watch commands

| Command | Purpose |
|---------|---------|
| `build-watch on` | Init `.build-watch/`, start server, open browser |
| `build-watch serve` | Server only (port 8790) |
| `build-watch status` | Paths, terminal count, last events |
| `build-watch event "msg"` | Log a build step |
| `build-watch connect [session_id]` | Link Grok Build `updates.jsonl` |
| `build-watch grok` | Bridge status |
| `build-watch off` | Stop background server |

**Grok connection:** reads `~/.grok/active_sessions.json` + tails `updates.jsonl` for Shell/Write/StrReplace/Read. Canvas **Grok Build** tab shows terminal output + code edits live.

Environment:

| Var | Default |
|-----|---------|
| `BUILD_WATCH_PORT` | `8790` |
| `BUILD_WATCH_DIR` | `.build-watch` in project cwd |
| `GROK_TERMINALS_DIR` | Auto-discover under `~/.grok/projects` |

## When invoked in Grok

1. Run `zai-wrap init` and `build-watch on` in the user's project cwd.
2. Tell them to keep the dashboard open in a browser tab while Grok works.
3. For Z.AI sessions in another tool, run `zai-wrap compose "<task>"` and give them the block to paste.
4. Periodically `build-watch event` for major steps so the dashboard stays live.

## Difficulty (honest)

| Piece | Effort | Notes |
|-------|--------|-------|
| Wrapper prompts | **Done** | Templates + CLI |
| Terminal mirror | **Easy** | Parse Grok `terminals/*.txt` (already on disk) |
| Git/file watch | **Easy** | `git status`, mtime poll |
| Live web UI | **Easy** | Stdlib Python + SSE |
| Full PTY hijack | **Hard** | Not needed; file-based mirror is enough |