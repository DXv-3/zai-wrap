## Visibility contract (build-watch)

The human is watching a live dashboard at **{{BUILD_WATCH_URL}}** while you work.

After each meaningful step, append exactly one line to **{{EVENTS_PATH}}** (create the file if missing):

```json
{"ts":"<ISO8601>","kind":"<plan|edit|test|cmd|note|done>","msg":"<short human sentence>","files":["<optional paths>"]}
```

Or run in terminal:

```bash
build-watch event "<short sentence>" --kind edit --files path/to/file.py
```

**When to emit:** starting a task, finishing a file edit, running tests/build, hitting a blocker, completing the task (`kind: done`).

**Do not** spam — max ~1 event per logical step (roughly every 1–3 tool calls).