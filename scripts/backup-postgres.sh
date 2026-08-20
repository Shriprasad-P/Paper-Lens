#!/usr/bin/env bash
set -euo pipefail

: "${PAPERLENS_DATABASE_URL:?Set PAPERLENS_DATABASE_URL to a PostgreSQL URL}"
backup_path="${1:?Usage: backup-postgres.sh /path/to/backup.dump}"
mkdir -p "$(dirname "$backup_path")"
pg_dump --format=custom --no-owner --file="$backup_path" "$PAPERLENS_DATABASE_URL"
echo "Created PostgreSQL backup at $backup_path"
