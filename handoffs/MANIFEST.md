# Handoff manifest — download instructions

## What this bundle is

A **git-handoff v3.2-style** export of the entire **zai-wrap + build-watch v2** system so any LLM can:

- Understand architecture without reading the whole codebase
- Rebuild from `zai-wrap.REBUILD.md`
- Operate via `zai-wrap.AGENT.md` playbook

## Files in this folder

| File | Read when |
|------|-----------|
| `zai-wrap.AGENT.md` | **First** — constraints + routing |
| `zai-wrap.REBUILD.md` | Recreating the project |
| `zai-wrap.EXPLAIN.md` | Architecture + diagrams |
| `zai-wrap.HANDOFF.md` | **Full** API, CLI, protocols |
| `zai-wrap.handoff.json` | Machine metadata |
| `MANIFEST.md` | This file |

## Download methods

### 1. One-command tarball

```bash
bash ~/.grok/skills/zai-wrap/scripts/pack_handoff.sh
```

Default output: `~/Downloads/zai-wrap-handoff-2.0.0.tar.gz`

Extract:

```bash
tar -xzf ~/Downloads/zai-wrap-handoff-2.0.0.tar.gz
cd zai-wrap-handoff-2.0.0
# Give the LLM: handoffs/zai-wrap.AGENT.md + handoffs/zai-wrap.HANDOFF.md
# Install: symlink scripts per zai-wrap.HANDOFF.md
```

### 2. Upload to ChatGPT / Claude / Grok

Attach in order:

1. `zai-wrap.AGENT.md`
2. `zai-wrap.HANDOFF.md`
3. (optional) `zai-wrap.EXPLAIN.md`

### 3. Git handoff hub

```bash
cp -r ~/.grok/skills/zai-wrap/handoffs/* ~/Documents/gitreverse/handoffs/
```

### 4. After publishing on GitHub

```
https://gitingest.com/<owner>/zai-wrap
https://gitreverse.com/<owner>/zai-wrap
```

## Verify install

```bash
build-watch check
python3 scripts/test_api.py
```

## Token budget hint

| Bundle | Approx size |
|--------|-------------|
| AGENT + HANDOFF only | ~8–12k tokens |
| + EXPLAIN + REBUILD | ~15–20k tokens |
| Full skill tarball (no pyc) | ~150–250k tokens — use gitingest if on GitHub |