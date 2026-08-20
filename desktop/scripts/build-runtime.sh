#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
FRONTEND_RESOURCES="$DESKTOP_DIR/src-tauri/resources/frontend"

"$DESKTOP_DIR/scripts/build-backend.sh"

(
  cd "$ROOT_DIR/frontend"
  npm ci
  npm run build
)

rm -rf "$FRONTEND_RESOURCES"
mkdir -p "$FRONTEND_RESOURCES/.next"
cp -R "$ROOT_DIR/frontend/.next/standalone/." "$FRONTEND_RESOURCES/"
cp -R "$ROOT_DIR/frontend/.next/static" "$FRONTEND_RESOURCES/.next/static"
if [[ -d "$ROOT_DIR/frontend/public" ]]; then
  cp -R "$ROOT_DIR/frontend/public" "$FRONTEND_RESOURCES/public"
fi

NODE_BINARY="${PAPERLENS_NODE_BINARY:-}"
if [[ -z "$NODE_BINARY" && -n "${NVM_BIN:-}" && -x "$NVM_BIN/node" ]]; then
  NODE_BINARY="$NVM_BIN/node"
fi
if [[ -z "$NODE_BINARY" ]]; then
  NODE_BINARY="$(command -v node)"
fi
if [[ ! -x "$NODE_BINARY" ]]; then
  echo "Node executable is missing: $NODE_BINARY" >&2
  exit 1
fi
if command -v otool >/dev/null 2>&1 && otool -L "$NODE_BINARY" | grep -q '@rpath/libnode'; then
  echo "Node executable depends on @rpath/libnode; set PAPERLENS_NODE_BINARY to a self-contained Node build." >&2
  exit 1
fi
echo "Bundling Node executable: $NODE_BINARY"
cp "$NODE_BINARY" "$DESKTOP_DIR/src-tauri/resources/node"
chmod +x "$DESKTOP_DIR/src-tauri/resources/node"
