#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
DATA_DIR="${PAPERLENS_DESKTOP_DATA_DIR:-$HOME/Library/Application Support/PaperLens}"
BACKEND_PORT="${PAPERLENS_DESKTOP_BACKEND_PORT:-18000}"
FRONTEND_PORT="${PAPERLENS_DESKTOP_FRONTEND_PORT:-13000}"
TOKEN="${PAPERLENS_DESKTOP_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_hex(24))')}"
mkdir -p "$DATA_DIR/database" "$DATA_DIR/papers" "$DATA_DIR/artifacts" "$DATA_DIR/cache" "$DATA_DIR/logs"

export PAPERLENS_ENVIRONMENT=development
export PAPERLENS_DATABASE_URL="sqlite:///$DATA_DIR/database/paperlens.db"
export PAPERLENS_STORAGE_PATH="$DATA_DIR/papers"
export PAPERLENS_STORAGE_PROVIDER=local
export PAPERLENS_AUTO_CREATE_SCHEMA=false
export PAPERLENS_FRONTEND_ORIGINS="http://127.0.0.1:$FRONTEND_PORT"
export PAPERLENS_FRONTEND_ORIGIN="http://127.0.0.1:$FRONTEND_PORT"
export PAPERLENS_BACKEND_PUBLIC_URL="http://127.0.0.1:$BACKEND_PORT"
export PAPERLENS_AI_PROVIDER=none
export EMBEDDING_PROVIDER=none
export PAPERLENS_DESKTOP_TOKEN="$TOKEN"
export PAPERLENS_BACKEND_PORT="$BACKEND_PORT"
export PAPERLENS_DESKTOP_DEV=1
export PAPERLENS_DESKTOP_BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
export PAPERLENS_DESKTOP_FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"

cd "$ROOT_DIR"
"$ROOT_DIR/.venv/bin/python" -m alembic upgrade head
"$ROOT_DIR/.venv/bin/uvicorn" backend.app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$DATA_DIR/logs/backend.log" 2>&1 &
BACKEND_PID=$!
(cd "$ROOT_DIR/frontend" && npm run dev -- --hostname 127.0.0.1 --port "$FRONTEND_PORT") >"$DATA_DIR/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
cleanup() {
  kill "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$DESKTOP_DIR"
npm exec tauri dev
