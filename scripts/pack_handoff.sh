#!/usr/bin/env bash
# Pack zai-wrap + build-watch for LLM download (handoff tarball).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="2.0.0"
OUT="${1:-$HOME/Downloads/zai-wrap-handoff-${VERSION}.tar.gz}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

NAME="zai-wrap-handoff-${VERSION}"
DEST="$STAGE/$NAME"
mkdir -p "$DEST"

copy_tree() {
  local src="$1" rel="$2"
  if [[ -d "$ROOT/$src" ]]; then
    mkdir -p "$DEST/$rel"
    rsync -a --exclude '__pycache__' --exclude '.build-watch' --exclude '*.pyc' \
      "$ROOT/$src/" "$DEST/$rel/"
  fi
}

copy_file() {
  local src="$1" rel="$2"
  [[ -f "$ROOT/$src" ]] || return 0
  mkdir -p "$(dirname "$DEST/$rel")"
  cp "$ROOT/$src" "$DEST/$rel"
}

copy_tree handoffs handoffs
copy_tree prompts prompts
copy_tree references references
copy_tree scripts scripts
copy_tree static static
copy_file SKILL.md SKILL.md
copy_file handoffs/MANIFEST.md README-DOWNLOAD.md

# Drop pycache if rsync missed nested
find "$DEST" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

(
  cd "$STAGE"
  tar -czf "$OUT" "$NAME"
)

echo "Packed: $OUT"
echo "Size: $(du -h "$OUT" | awk '{print $1}')"
echo ""
echo "LLM quick start — extract and read:"
echo "  1. handoffs/zai-wrap.AGENT.md"
echo "  2. handoffs/zai-wrap.HANDOFF.md"
echo ""
echo "Install from bundle:"
echo "  mkdir -p ~/.grok/skills && cp -r $NAME ~/.grok/skills/zai-wrap"
echo "  # then symlink build-watch + zai-wrap per HANDOFF"