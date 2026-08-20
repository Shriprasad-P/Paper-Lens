#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
PYTHON="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "Missing $PYTHON; create the project virtual environment first." >&2
  exit 1
fi

"$PYTHON" -m PyInstaller \
  --noconfirm --clean --onefile --name paperlens-backend \
  --paths "$ROOT_DIR" \
  --collect-submodules backend.app \
  --add-data "$ROOT_DIR/alembic.ini:." \
  --add-data "$ROOT_DIR/migrations:migrations" \
  --add-data "$ROOT_DIR/backend/app/prompts:backend/app/prompts" \
  --distpath "$DESKTOP_DIR/src-tauri/resources" \
  --workpath "$DESKTOP_DIR/.build/pyinstaller" \
  --specpath "$DESKTOP_DIR/.build" \
  "$ROOT_DIR/backend/desktop_runner.py"

chmod +x "$DESKTOP_DIR/src-tauri/resources/paperlens-backend"
