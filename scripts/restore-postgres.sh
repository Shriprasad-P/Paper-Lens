#!/usr/bin/env bash
set -euo pipefail

: "${PAPERLENS_RESTORE_DATABASE_URL:?Set PAPERLENS_RESTORE_DATABASE_URL to a separate restore database}"
backup_path="${1:?Usage: restore-postgres.sh /path/to/backup.dump}"
if [[ ! -f "$backup_path" ]]; then
  echo "Backup does not exist: $backup_path" >&2
  exit 1
fi
pg_restore --clean --if-exists --no-owner --dbname="$PAPERLENS_RESTORE_DATABASE_URL" "$backup_path"
psql "$PAPERLENS_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'select count(*) as papers from papers;'
echo "Restore verification completed against the separate restore database"
