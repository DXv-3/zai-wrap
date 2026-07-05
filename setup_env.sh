#!/usr/bin/env bash
# setup_env.sh — zai-wrap environment bootstrap
# Source this file from your shell profile:
#   echo 'source ~/Projects/zai-wrap/setup_env.sh' >> ~/.zshrc
#
# Or run once for the current session:
#   source ~/Projects/zai-wrap/setup_env.sh

# ── Paths ─────────────────────────────────────────────────────────────────
# Detect the zai-wrap repo root (works whether sourced or executed)
ZAI_WRAP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

export ZAI_WRAP_PATH="$ZAI_WRAP_DIR"
export ZAI_WRAP_LOG_DIR="$HOME/.zai-wrap"
mkdir -p "$ZAI_WRAP_LOG_DIR"

# Add model_gateway.py to Python path so conductor can import ModelRouter
export PYTHONPATH="$ZAI_WRAP_DIR:${PYTHONPATH:-}"

# ── Sibling repo paths ────────────────────────────────────────────────────
# Adjust these to match your actual directory layout.
# Default assumes all repos live side-by-side in the same parent folder.
_PARENT="$(dirname "$ZAI_WRAP_DIR")"

export SIS_PATH="${SIS_PATH:-$_PARENT/self-improving-system-builder}"
export MATRIX_PATH="${MATRIX_PATH:-$_PARENT/MATRIX}"
export CONDUCTOR_PATH="${CONDUCTOR_PATH:-$_PARENT/conductor-protocol-v2}"
export BRAIN_MCP_URL="${BRAIN_MCP_URL:-http://localhost:8765}"
export CONDUCTOR_DB="${CONDUCTOR_DB:-$_PARENT/conductor-protocol-v2/conductor_state.db}"
export SKILL_SYNC_DB="${SKILL_SYNC_DB:-$_PARENT/self-improving-system-builder/skill_brain_sync.db}"

# ── Harmony bus ───────────────────────────────────────────────────────────
export HARMONY_HOST="${HARMONY_HOST:-localhost}"
export HARMONY_PORT="${HARMONY_PORT:-7700}"
export HARMONY_POLL_FILE="${HARMONY_POLL_FILE:-/tmp/harmony_events.jsonl}"
export ZAI_WRAP_HARMONY="${ZAI_WRAP_HARMONY:-1}"

# ── API keys (set from your secrets manager or .env — never hardcoded) ───
# These are no-ops if already set in the environment.
# Recommended: use `op` (1Password CLI) or `pass` to inject secrets.
: "${ANTHROPIC_API_KEY:?Please set ANTHROPIC_API_KEY}"
: "${XAI_API_KEY:=}"           # optional — Grok/Z.AI
: "${DEEPSEEK_API_KEY:=}"      # optional — Deepseek
: "${OPENAI_API_KEY:=}"        # optional — OpenAI fallback

# ── Verify ────────────────────────────────────────────────────────────────
echo "✅ zai-wrap env loaded"
echo "   ZAI_WRAP_PATH  = $ZAI_WRAP_PATH"
echo "   SIS_PATH       = $SIS_PATH"
echo "   MATRIX_PATH    = $MATRIX_PATH"
echo "   CONDUCTOR_PATH = $CONDUCTOR_PATH"
echo "   BRAIN_MCP_URL  = $BRAIN_MCP_URL"
echo "   PYTHONPATH     includes $ZAI_WRAP_DIR"
echo ""
echo "Run smoke test:  python \"$ZAI_WRAP_DIR/model_gateway.py\" --task fast"
echo "List models:     python \"$ZAI_WRAP_DIR/model_gateway.py\" --list"
