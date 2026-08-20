#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
(
  cd "$DESKTOP_DIR"
  npm exec tauri info
)
(cd "$ROOT_DIR" && "$ROOT_DIR/.venv/bin/python" -m unittest discover -s "$ROOT_DIR/backend/tests" >/dev/null)
echo "desktop checks: toolchain and backend regression suite passed"
