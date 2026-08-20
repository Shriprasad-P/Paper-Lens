#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"

"$DESKTOP_DIR/scripts/build-runtime.sh"
(
  cd "$DESKTOP_DIR"
  npm exec tauri build
)

APP_PATH="$DESKTOP_DIR/src-tauri/target/release/bundle/macos/PaperLens.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Expected app bundle was not produced: $APP_PATH" >&2
  exit 1
fi
echo "PaperLens.app: $APP_PATH"
