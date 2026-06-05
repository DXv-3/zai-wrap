#!/usr/bin/env bash
# Shared helpers for zai-wrap / build-watch
set -euo pipefail

ZAI_WRAP_ROOT="${ZAI_WRAP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

zai_project_cwd() {
  if [[ -n "${BUILD_WATCH_PROJECT:-}" ]]; then
    echo "$BUILD_WATCH_PROJECT"
    return
  fi
  local d="${PWD}"
  while [[ "$d" != "/" ]]; do
    if [[ -d "${d}/.build-watch" ]] || [[ -d "${d}/.git" ]]; then
      echo "$d"
      return
    fi
    d="$(dirname "$d")"
  done
  echo "${PWD}"
}

zai_watch_dir() {
  local cwd
  cwd="$(zai_project_cwd)"
  if [[ -n "${BUILD_WATCH_DIR:-}" ]]; then
    if [[ "${BUILD_WATCH_DIR}" = /* ]]; then
      echo "${BUILD_WATCH_DIR}"
    else
      echo "${cwd}/${BUILD_WATCH_DIR}"
    fi
    return
  fi
  echo "${cwd}/.build-watch"
}

zai_events_file() {
  echo "$(zai_watch_dir)/events.jsonl"
}

zai_port() {
  echo "${BUILD_WATCH_PORT:-8790}"
}

zai_watch_url() {
  echo "http://127.0.0.1:$(zai_port)"
}

zai_render_template() {
  local file="$1"
  sed \
    -e "s|{{BUILD_WATCH_URL}}|$(zai_watch_url)|g" \
    -e "s|{{EVENTS_PATH}}|$(zai_events_file)|g" \
    -e "s|{{PROJECT_ROOT}}|$(zai_project_cwd)|g" \
    -e "s|{{PROJECT_NAME}}|$(basename "$(zai_project_cwd)")|g" \
    "$file"
}

zai_python() {
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found" >&2; return 1; }
  python3 "$@"
}

zai_port_listener_pid() {
  lsof -n -iTCP:"$(zai_port)" -sTCP:LISTEN -t 2>/dev/null | head -1
}

zai_stale_pid_cleanup() {
  local pf="${1:-}"
  [[ -n "$pf" ]] || return 0
  if [[ -f "$pf" ]]; then
    local pid
    pid="$(cat "$pf" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$pf"
    fi
  fi
}