# zai-wrap

Z.AI (GLM Coding Plan) prompt wrappers plus **build-watch** — a local live dashboard for coding agents on macOS.

- **Canvas UI:** http://127.0.0.1:8790 — Grok Build stream, terminals, git, previews, TTS
- **Grok bridge:** tails `~/.grok/sessions/.../updates.jsonl`
- **Handoff bundle:** [`handoffs/zai-wrap.AGENT.md`](handoffs/zai-wrap.AGENT.md) + [`handoffs/zai-wrap.HANDOFF.md`](handoffs/zai-wrap.HANDOFF.md)

## Quick install

```bash
git clone https://github.com/DXv-3/zai-wrap.git ~/.grok/skills/zai-wrap
mkdir -p ~/.grok/bin
ln -sf ~/.grok/skills/zai-wrap/scripts/build-watch ~/.grok/bin/build-watch
ln -sf ~/.grok/skills/zai-wrap/scripts/zai-wrap ~/.grok/bin/zai-wrap
export PATH="$HOME/.grok/bin:$PATH"

cd ~/your-project
build-watch on
zai-wrap compose "your task"
```

## Commands

| CLI | Purpose |
|-----|---------|
| `build-watch on` | Start server + open canvas |
| `build-watch connect` | Link Grok Build session |
| `build-watch check` | Preflight (v2.0.0) |
| `zai-wrap compose "…"` | Z.AI session prompt |
| `python3 scripts/test_api.py` | API smoke tests |

## LLM context (gitingest / gitreverse)

- **Ingest:** https://gitingest.com/DXv-3/zai-wrap
- **Reverse:** https://gitreverse.com/DXv-3/zai-wrap

## Docs

- [SKILL.md](SKILL.md) — Grok skill entry
- [references/VOICE_CLONING.md](references/VOICE_CLONING.md) — local voice clone options
- [references/GITHUB_MORPH_LIST_B.md](references/GITHUB_MORPH_LIST_B.md) — GitHub parts library
- `bash scripts/pack_handoff.sh` — tarball for offline handoff

## Requirements

- macOS, Python 3.10+
- Grok CLI sessions (optional, for bridge)
- Z.AI endpoint in Cline/Claude Code (optional, for wrappers)

## License

MIT