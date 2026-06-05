# Free local voice cloning (GitHub research)

Research for wiring **custom / cloned voices** into build-watch canvas TTS (today: macOS `say` + Siri).

## Legal note (important)

Cloning a **celebrity voice** (e.g. from movie clips or YouTube) without permission can violate **right of publicity**, **copyright**, and platform terms. Scarlett Johansson has pursued legal action over unauthorized AI voice likeness. Use only:

- Audio **you recorded** or have a **license** to use
- Royalty-free / CC voice samples
- **Voice design** prompts (describe timbre) where the model supports it — not impersonation of a named person

This doc is for **local, open-source tooling** with audio you own.

---

## Top GitHub options (free / open source)

| Project | Stars | License | Best for | macOS |
|---------|------:|---------|----------|-------|
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | ~29k | MIT | All-in-one studio: clone, dictate, UI; **MLX** on Apple Silicon | Excellent |
| [myshell-ai/OpenVoice](https://github.com/myshell-ai/OpenVoice) | ~37k | MIT | **Instant** clone from short reference WAV (~5–30s) | Good (Python) |
| [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | ~58k | MIT | Few-shot TTS; **~1 min** training data; high quality | GPU preferred |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | ~12k | Apache-2.0 | Voice **design** + **cloning**; streaming; used by voicebox | Good |
| [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) | ~36k | MIT | Train VC model from **≤10 min** speech; convert existing audio | GPU |
| [debpalash/OmniVoice-Studio](https://github.com/debpalash/OmniVoice-Studio) | ~6k | Other | Desktop “ElevenLabs alternative”; dubbing + clone | Desktop app |
| [idiap/coqui-ai-TTS](https://github.com/idiap/coqui-ai-TTS) | ~35k+ | MPL | XTTS v2 **cross-lingual** clone; Python API | CPU/GPU |

Also see curated lists: [wildminder/awesome-ai-voice](https://github.com/wildminder/awesome-ai-voice).

---

## Recommended path for build-watch (Mac)

### Fastest UX: **voicebox** + Qwen3-TTS

1. Install [voicebox](https://github.com/jamiepine/voicebox) (MIT, supports MLX on M-series).
2. Record or import a **clean 10–60s** reference (single speaker, little reverb).
3. Create a voice profile; export test WAV.
4. Point build-watch at an external TTS command (see below).

### Fastest clone (no training): **OpenVoice**

1. Clone [OpenVoice](https://github.com/myshell-ai/OpenVoice), install deps.
2. Provide `reference.wav` + text → output `out.wav`.
3. Wrap in a shell script and set `BUILD_WATCH_TTS_CMD`.

### Best quality / more setup: **GPT-SoVITS**

1. Prepare 1–5 minutes of clean speech (or fine-tune with less).
2. Run WebUI training + inference.
3. Expose a small HTTP or CLI that reads text from stdin and writes AIFF/WAV; play via `afplay` or pipe to canvas.

---

## Wiring into build-watch

### Environment variables

| Variable | Purpose |
|----------|---------|
| `BUILD_WATCH_TTS_BACKEND` | `say` (default) or `external` |
| `BUILD_WATCH_TTS_CMD` | Shell command: receives text on stdin; must play audio or write file |
| `BUILD_WATCH_VOICE_REF` | Path to reference WAV for external cloner |
| `BUILD_WATCH_TTS_RATE` | Optional rate hint for external backend |

Example external command (you implement):

```bash
#!/bin/bash
# ~/.grok/skills/zai-wrap/scripts/tts_openvoice.sh
REF="${BUILD_WATCH_VOICE_REF:-$HOME/.build-watch/voices/my-voice.wav}"
TEXT="$(cat)"
# ... invoke your OpenVoice / Qwen3 CLI ...
afplay /tmp/bw-tts-out.wav
```

```bash
export BUILD_WATCH_TTS_BACKEND=external
export BUILD_WATCH_TTS_CMD="$HOME/.grok/skills/zai-wrap/scripts/tts_openvoice.sh"
export BUILD_WATCH_VOICE_REF="$HOME/.build-watch/voices/reference.wav"
build-watch on
```

Canvas **Listen** still calls `POST /api/tts`; the server uses `bw/tts.py`, which delegates to `external` when configured.

---

## “Scarlett Johansson–like” without cloning her

Prefer **voice design** (Qwen3-TTS / voicebox) with a text description, e.g.:

- “Warm, low female alto, calm and precise, American accent, slightly husky, conversational”

Do **not** use her name in prompts for commercial/public systems if the goal is impersonation. Tune with **your** licensed reference clips that merely match a *vibe*, not a specific performer’s extracted voice from films.

---

## Next implementation steps (zai-wrap)

1. [x] `test_api.py` — API smoke tests after server changes  
2. [x] `BUILD_WATCH_TTS_*` hooks in `bw/tts.py`  
3. [ ] Optional `tts_openvoice.sh` template once you pick a backend  
4. [ ] Canvas UI: voice picker → `settings.tts_voice` + `voice_ref` path in `.build-watch/settings.json`

Run tests:

```bash
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py
python3 ~/.grok/skills/zai-wrap/scripts/test_api.py --skip-grok
```