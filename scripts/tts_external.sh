#!/usr/bin/env bash
# Template: external TTS for build-watch (wire up OpenVoice, Qwen3-TTS, GPT-SoVITS, etc.)
# Usage:
#   export BUILD_WATCH_TTS_BACKEND=external
#   export BUILD_WATCH_TTS_CMD="$HOME/.grok/skills/zai-wrap/scripts/tts_external.sh"
#   export BUILD_WATCH_VOICE_REF="$HOME/.build-watch/voices/reference.wav"
#
# Reads text from stdin. Replace the middle section with your cloner CLI.

set -euo pipefail
REF="${BUILD_WATCH_VOICE_REF:-}"
TEXT="$(cat)"
OUT="${TMPDIR:-/tmp}/bw-tts-$$.wav"

if [[ -z "$TEXT" ]]; then
  exit 0
fi

# --- Replace this block with your local TTS / clone command ---
# Example placeholders (not installed by default):
#   openvoice-cli --ref "$REF" --text "$TEXT" -o "$OUT"
#   python -m qwen_tts --ref "$REF" --text "$TEXT" -o "$OUT"

if [[ ! -f "$REF" ]]; then
  echo "tts_external: set BUILD_WATCH_VOICE_REF to a reference WAV" >&2
  exit 1
fi

echo "tts_external: install a cloner and edit this script (see references/VOICE_CLONING.md)" >&2
echo "  ref=$REF" >&2
echo "  text_bytes=${#TEXT}" >&2
exit 1
# --- end replace ---

# afplay "$OUT"
# rm -f "$OUT"