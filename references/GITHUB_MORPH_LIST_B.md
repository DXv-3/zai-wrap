# GitHub Morph — List B (parts library & compose targets)

**List A** = broad “what to search.” **List B** = what to **extract, morph, and compose** into zai-wrap / build-watch / git-handoff using `/github-morph` + ecosystem transforms.

---

## 1. Morph atoms (steal these *components*, not whole repos)

| Atom | GitHub search | Morph into |
|------|---------------|------------|
| `events.jsonl` bus | `append jsonl agent event language:python` | `.build-watch/events.jsonl`, `agent-chat/bus.jsonl` |
| Threading HTTP server w/ route table | `BaseHTTPRequestHandler route dict language:python` | `bw/server.py` patterns |
| JSONL tail + offset ingest | `jsonl offset tail ingest` | `bw/grok.py` updates bridge |
| PTY embed + nonblocking read | `openpty select python terminal` | `bw/terminal.py` |
| TTL probe cache | `ttl cache thread safe python` | `bw/cache.py` |
| Path policy / sandbox reads | `path traversal safe resolve python` | `bw/paths.py` |
| MCP tool descriptor → skill | `mcptoskill OR SKILL.md mcp server` | `.grok/skills/*` scaffolds |
| Tool-call UI lifecycle | `tool approval pending react agent` | canvas “agent tools” panel |
| Voice ref → TTS subprocess | `reference audio tts cli stdin` | `tts_external.sh` + `bw/tts.py` |
| Preflight checklist JSON | `health check cli json report` | `bw/boot.py` / `build-watch check` |
| Git worktree isolate | `git worktree python parallel` | `/best-of-n`, `/execute-plan` |
| Similar-repo ranker | `gitsimilar OR duplicate repo search` | handoff hub discovery |
| Handoff bundle writer | `AGENT.md handoff export` | `gitreverse` / `handoff reverse` |

---

## 2. Compose recipes (multi-repo → one feature)

Use **gitsimilar** → **gitingest** → **extract** → **morph** → drop into `scripts/bw/` or `static/`.

| You want | Compose from | Command sketch |
|----------|--------------|----------------|
| Canvas tool-call strip | `inference.sh` tool-ui + shadcn agent | `/github-morph find "tool pending approval react" --language typescript` |
| Live protocol debug for APIs | [Mouseww/anything-analyzer](https://github.com/Mouseww/anything-analyzer) MCP | `mcptoskill` → Grok MCP; morph MITM hooks → local-only |
| Diagrams on build stream | [yctimlin/mcp_excalidraw](https://github.com/yctimlin/mcp_excalidraw) | MCP + canvas iframe for architecture events |
| Repo context sidebar | repomix + gitingest + [pudiish/crawler-sage](https://github.com/pudiish/crawler-sage) | Morph watcher → `.build-watch/context.pack` |
| PR babysit loop | graphite / gh-stack + ci-retry bots | Morph “pending review” flow from `/review` PR mode |
| Skill from any MCP | filiksyos **mcptoskill** | `https://…` → `.grok/skills/<name>/` |
| Skill from any repo | **gittoskill** + objective | “build-watch grok bridge” ZIP → merge with zai-wrap |
| Rules bootstrap | **gitrules** | One-shot Agents.md + MCP install for new projects |
| Voice studio in canvas | voicebox + Qwen3-TTS | Extract MLX CLI wrapper → `tts_external.sh` |
| Photo dedup sidebar | imagededup + perceptual hash | `/github-photo-dedup` skill (already have) |

---

## 3. Ecosystem transforms (run on every candidate repo)

| Step | Transform | When |
|------|-----------|------|
| 1 | `github.com/o/r` → **gitsimilar** | Shortlist 5–15 repos |
| 2 | → **gitingest.com/o/r** | Full digest for reviewer subagent |
| 3 | → **gitreverse.com/o/r** | “Rebuild prompt” for morph plan |
| 4 | **gittoskill** + objective | Auto-skill if fit is narrow |
| 5 | **mcptoskill** | If repo is MCP-first |
| 6 | **gitcontainer** | Before running unknown Python locally |
| 7 | `handoff hub o/r` | Token budget + playbook in gitreverse hub |

---

## 4. `/github-morph find` queries (List B — different from List A)

### Handoff & context packing
```
/github-morph find "repomix pack codebase" --language python
/github-morph find "tree-sitter chunk indexer agent"
/github-morph find "codebase map mermaid generator"
/github-morph find "gitingest alternative local"
```

### Agent coordination (your multi-tab stack)
```
/github-morph find "orchestrator events jsonl"
/github-morph find "human approval tool call agent"
/github-morph find "subagent worktree isolated"
/github-morph find "tmux dashboard agent panes"
```

### Build visibility (morph into canvas)
```
/github-morph find "asciinema player embed"
/github-morph find "dev dashboard git webhook events"
/github-morph find "live reload preview iframe sandbox"
/github-morph find "terminal stream websocket python"
```

### Grok / session bridge
```
/github-morph find "session jsonl tail watcher"
/github-morph find "tool use log parser assistant"
/github-morph find "cursor updates.jsonl" 
```

### macOS local inference
```
/github-morph find "mlx python server fastapi"
/github-morph find "whisper.cpp mlx"
/github-morph find "coreml speech synthesis"
```

### Security & governance
```
/github-morph find "command allowlist agent sandbox"
/github-morph find "secret scan pre commit hook"
/github-morph find "audit log tool invocation"
```

### Testing & quality
```
/github-morph find "http smoke test script argparse"
/github-morph find "contract test openapi mock"
/github-morph find "llm eval harness pytest"
```

### UI morph targets
```
/github-morph find "bento grid dashboard dark"
/github-morph find "streaming markdown code highlight"
/github-morph find "voice waveform player web"
```

---

## 5. Morph map: external pattern → your tree

| Source pattern | Target path | Notes |
|----------------|-------------|-------|
| FastAPI + SSE stream | `bw/server.py` or separate `bw/stream.py` | Optional `/api/stream` for canvas |
| React tool-call card | `static/canvas.html` | Match `tools-ui` / `agent-ui` skills |
| LangGraph checkpoint | `.build-watch/checkpoints/` | Resume long agent runs |
| OpenTelemetry span | `.build-watch/trace.jsonl` | Debug grok_tick latency |
| Chromium CDP scrape | MCP browser skill | Research, not canvas core |
| Graphite stack metadata | `handoff` PR plans | `/execute-plan` DAG |

---

## 6. Priority morph queue (do these next)

1. **Repomix/gitingest watcher** → auto-refresh project context in canvas  
2. **MCP anything-analyzer** → debug z.ai / Grok API calls from build-watch  
3. **Tool-call UI atoms** → show pending/approved tools on Read tab  
4. **gitrules + gittoskill** → spawn skills from repos you star  
5. **Excalidraw MCP** → architecture diagrams on `build-watch event --kind design`  
6. **MLX whisper** → dictation tab (you already have `/api/dictation`)  

---

## 7. Anti-patterns (don’t morph wholesale)

- Full Electron apps → too heavy for canvas sidebar  
- GPU-only training UIs → keep as external CLI (`tts_external.sh` model)  
- Cloud-only SaaS agents → contradicts local `.build-watch/` ownership  
- Monorepos >50MB ingest → use `gitingest` partial paths / repomix filters  

---

## 8. One-liner workflow

```text
gitsimilar → gitingest digest → /github-morph extract --component <atom>
→ /github-morph morph --to bw/<module>.py → test_api.py → build-watch event
```

Related: [VOICE_CLONING.md](VOICE_CLONING.md) · List A (conversation) · `~/Documents/gitreverse/gitreverse_v3_master.md`