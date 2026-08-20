#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="$ROOT_DIR/desktop/src-tauri/target/release/bundle/macos/PaperLens.app"
APP_EXEC="$APP_BUNDLE/Contents/MacOS/paperlens-desktop"
DATA_DIR="$HOME/Library/Application Support/com.paperlens.app"
MODE="${1:-run}"

usage() {
  cat <<'EOF'
Usage: ./script/build_and_run.sh [run|--verify|--logs|--telemetry|--debug]

Builds the standalone backend, bundled Next.js runtime, and local PaperLens.app.
EOF
}

if [[ "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$MODE" != "run" && "$MODE" != "--verify" && "$MODE" != "--logs" && "$MODE" != "--telemetry" && "$MODE" != "--debug" ]]; then
  usage >&2
  exit 2
fi

if [[ -d "$APP_BUNDLE" ]]; then
  /usr/bin/osascript -e 'tell application "PaperLens" to quit' >/dev/null 2>&1 || true
  /usr/bin/pkill -f "$APP_EXEC" >/dev/null 2>&1 || true
fi

(cd "$ROOT_DIR/desktop" && npm run desktop:build)

if [[ "$MODE" == "--debug" ]]; then
  exec env RUST_BACKTRACE=1 "$APP_EXEC"
fi

/usr/bin/open -n "$APP_BUNDLE"

if [[ "$MODE" == "--verify" ]]; then
  for _ in {1..60}; do
    if [[ -f "$DATA_DIR/logs/desktop.log" ]] && /usr/bin/grep -q 'desktop_ready' "$DATA_DIR/logs/desktop.log"; then
      echo "PaperLens desktop_ready"
      exit 0
    fi
    sleep 0.5
  done
  echo "PaperLens did not reach desktop_ready; inspect $DATA_DIR/logs/desktop.log" >&2
  exit 1
fi

if [[ "$MODE" == "--logs" ]]; then
  exec /usr/bin/tail -f "$DATA_DIR/logs/desktop.log"
fi

if [[ "$MODE" == "--telemetry" ]]; then
  echo "bundle=$(du -sh "$APP_BUNDLE" | awk '{print $1}')"
  echo "data_dir=$DATA_DIR"
  /bin/ps -axo pid,rss,etime,command | /usr/bin/grep -E 'paperlens-desktop|paperlens-backend|next-server' | /usr/bin/grep -v grep || true
fi
