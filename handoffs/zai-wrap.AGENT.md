# AGENT — zai-wrap + build-watch v2 (read first)

**Slug:** `vinnygilberti/zai-wrap` (local skill, not a public GitHub repo)  
**Generated:** 2026-06-05  
**Version:** build-watch **2.0.0**

## Role

You are taking over a **local macOS agent visibility stack**: Z.AI/GLM prompt wrappers + a live **build-watch** dashboard that mirrors Grok Build sessions, terminals, git, previews, and TTS.

## Read order

1. This file (`zai-wrap.AGENT.md`)
2. `zai-wrap.REBUILD.md` — recreate from scratch
3. `zai-wrap.EXPLAIN.md` — architecture
4. `zai-wrap.HANDOFF.md` — full merged spec + API + file map
5. `zai-wrap.handoff.json` — machine metadata
6. Source tree under `~/.grok/skills/zai-wrap/` (or bundled tarball)

## Hard constraints

- **Do not invent** files or APIs not listed in HANDOFF or the source tree.
- **Default bind:** `127.0.0.1:8790` only (local dashboard).
- **Path policy:** all project file I/O goes through `bw.paths.PathPolicy` (no `..`, no symlinks).
- **Grok bridge** reads `~/.grok/sessions/*/updates.jsonl` — session IDs must match `SESSION_ID_RE`.
- **TTS default:** macOS `say(1)`; external clone only via `BUILD_WATCH_TTS_CMD` / `BUILD_WATCH_TTS_BACKEND=external`.
- **Do not** guide users to clone celebrity voices without rights to the audio.

## Tool routing

| Goal | Action |
|------|--------|
| Run dashboard | `build-watch on` from project cwd |
| Smoke test API | `python3 scripts/test_api.py` |
| Link Grok session | `build-watch connect [session_id]` |
| Z.AI task prompt | `zai-wrap compose "task"` |
| Voice clone research | `references/VOICE_CLONING.md` |
| GitHub parts library | `references/GITHUB_MORPH_LIST_B.md` |
| Full handoff pack | `scripts/pack_handoff.sh` |

## Ecosystem transforms (if extending via GitHub)

| Tool | Use |
|------|-----|
| gitingest | Ingest any *other* repo for context |
| gitreverse | Reverse-engineer third-party repos |
| gittoskill | Turn a repo into a skill ZIP |
| mcptoskill | MCP server → skill |
| gitsimilar | Find analogous implementations |

## Success criteria

- `build-watch check` → `"ok": true`, `"version": "2.0.0"`
- `test_api.py` → 14 passed (or 11 with `--skip-grok`)
- Canvas at `http://127.0.0.1:8790` shows state, events, optional Grok turns