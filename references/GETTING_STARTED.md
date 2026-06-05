# Build Watch — End-to-End Guide

**What it is:** A browser window that shows your **running app** while you build in **Grok Build** (your normal terminal). Think Lovable’s preview pane — Grok codes there; you watch here.

**Dashboard URL:** http://127.0.0.1:8790 (default port)

---

## 1. One-time setup (5 minutes)

### Install CLI tools

```bash
mkdir -p ~/.grok/bin
ln -sf ~/.grok/skills/zai-wrap/scripts/build-watch ~/.grok/bin/build-watch
ln -sf ~/.grok/skills/zai-wrap/scripts/zai-wrap ~/.grok/bin/zai-wrap
export PATH="$HOME/.grok/bin:$PATH"
```

Add to `~/.zshrc` if you want it permanent:

```bash
export PATH="$HOME/.grok/bin:$PATH"
```

### Verify

```bash
build-watch check
```

Should pass preflight (Python, canvas files, port).

---

## 2. Every session — start Build Watch

**Always run from the project you are building**, not from `~/.grok/skills/zai-wrap`.

```bash
cd ~/Documents/gitreverse    # ← your real project
build-watch on
```

This will:

1. Create `.build-watch/` in the project (events, Grok link, settings)
2. Start the local server on port **8790**
3. Open **http://127.0.0.1:8790** in your browser

**Pin that browser tab** — you can use it in any window; it stays the preview.

### Check status (optional)

```bash
build-watch status
```

Shows project path, watch dir, server PID, URL.

### Stop when done

```bash
build-watch off
```

---

## 3. Link Grok (any terminal tab)

You code in **Grok Build** (terminal). Build Watch **follows** that session.

### In the browser

1. Open **http://127.0.0.1:8790**
2. **Grok tab** dropdown (header) — lists open Grok sessions  
   - **★** = folder matches your project (pick this when possible)
3. Click **Link Grok**
4. Status bar should say you’re linked

### In the terminal (same thing)

```bash
cd ~/Documents/gitreverse
build-watch connect                  # auto-pick best tab
build-watch connect <session-id>     # specific tab
build-watch grok                     # debug: bridge status
```

### Deep link (bookmark per session)

```
http://127.0.0.1:8790/?session=019e957a-23c6-7463-b117-d85ce73a14ef
```

Replace with your session id from the dropdown.

### If linking fails

| Message | Fix |
|---------|-----|
| No Grok tabs found | Open **Grok Build** in a terminal tab first, then refresh Build Watch |
| updates_not_found | That tab has no log yet — pick another tab in the dropdown |
| Wrong project in header | `build-watch off` then `cd YOUR_PROJECT && build-watch on` |

---

## 4. Watch your app (the main point)

### Center preview

- Shows your **live app** when Grok runs a dev server (`npm run dev`, Vite on 5173, Next on 3000, etc.)
- Or shows an **HTML file** from the project (e.g. `handoff-preview.html`)
- **↻** refreshes; URL bar accepts dev server URL or `path/to/file.html`

Build Watch auto-detects common dev ports (5173, 3000, 8080, …). It **never** uses port 8790 (itself) as the app preview.

### Optional panels

| Button | Purpose |
|--------|---------|
| **What Grok did** | Timeline of edits and commands — click a file to open |
| **Open a file** | Shortcuts to HTML and project files |
| **Show Grok terminal output** | Optional copy of Grok’s terminal (bottom) |

You can ignore these if you only want the preview.

### **How it works** (in the UI)

Click the header button for a short glossary.

---

## 5. Daily workflow (recommended)

```
┌─────────────────────┐     ┌──────────────────────────┐
│  Grok Build         │     │  Build Watch (browser)   │
│  (terminal tab)     │     │  http://127.0.0.1:8790   │
│                     │     │                          │
│  Chat + commands    │────▶│  Big preview of your app │
│  npm run dev        │     │  (read-only watch)       │
└─────────────────────┘     └──────────────────────────┘
         ▲                              ▲
         │         Link Grok              │
         └──────────────────────────────────┘
```

1. `cd your-project && build-watch on`
2. Pin the browser tab
3. Open Grok Build → work as usual
4. Pick Grok tab → **Link Grok**
5. When dev server starts, preview fills in automatically
6. `build-watch off` when finished

---

## 6. Z.AI / Cline / Claude Code (optional)

Build Watch is separate from **zai-wrap** prompts (GLM Coding Plan).

```bash
cd your-project
zai-wrap compose "add user settings page"
```

Copy the output into Cline or Claude Code (with Z.AI endpoint configured).  
While that agent runs, keep Build Watch open if the same machine is also using Grok Build, or log steps manually:

```bash
build-watch event "Finished settings API" --kind done --files src/settings.ts
```

See [SKILL.md](../SKILL.md) for Z.AI endpoint URLs.

---

## 7. Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `BUILD_WATCH_PORT` | `8790` | Dashboard port |
| `BUILD_WATCH_PROJECT` | auto (cwd with `.git` or `.build-watch`) | Force project root |
| `BUILD_WATCH_DIR` | `.build-watch` | Watch data folder |
| `GROK_SESSION_ID` | — | Force a Grok session id |
| `BUILD_WATCH_GROK_SYNC` | `1` | Mirror Grok edits into event stream |

Example — watch a specific project from anywhere:

```bash
export BUILD_WATCH_PROJECT=~/Documents/gitreverse
build-watch on
```

---

## 8. Troubleshooting

### Preview is empty or shows the dashboard itself

- Hard refresh: `⌘⇧R`
- Click **Open a file** → pick an `.html` file  
- Or paste your dev server URL (from Grok output, e.g. `http://127.0.0.1:5173`) and **Open**

### Preview never updates

- Confirm **Link Grok** and the right tab in the dropdown
- Run `npm run dev` (or equivalent) in Grok
- Click **↻** refresh

### “Offline” in status bar

```bash
build-watch on
# or
curl http://127.0.0.1:8790/api/health
```

### Run API smoke tests (developers)

```bash
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py --skip-grok
```

### Advanced / legacy UI

http://127.0.0.1:8790/canvas-legacy — older tabbed canvas (Read, Workshop, etc.)

---

## 9. Command cheat sheet

| Command | What it does |
|---------|----------------|
| `build-watch on` | Start + open browser |
| `build-watch off` | Stop server |
| `build-watch status` | Project, URL, PID |
| `build-watch connect` | Link Grok session |
| `build-watch grok` | JSON bridge status |
| `build-watch event "msg"` | Log a step to the feed |
| `build-watch check` | Preflight |
| `zai-wrap init` | Create `.build-watch/` |
| `zai-wrap compose "task"` | GLM prompt for other tools |

---

## 10. Mental model

- **You are not building inside Build Watch** — you are **watching** what Grok builds.
- **One browser tab** can stay open anywhere on your machine.
- **Multiple Grok tabs** → use the dropdown to choose which one to follow.
- **One project per server start** → always `cd` into the right repo before `build-watch on`.

Repo: https://github.com/DXv-3/zai-wrap