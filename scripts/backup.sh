#!/usr/bin/env bash
# Back up the ForiFlow database (Linux/macOS). Same as backup.bat.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
file="backups/foriflow-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file"
[ "$(wc -c < "$file")" -ge 1000 ] || { echo "BACKUP FAILED"; rm -f "$file"; exit 1; }
docker compose cp "$file" db:/tmp/foriflow-backup-check.dump >/dev/null
docker compose exec -T db sh -c 'pg_restore --list /tmp/foriflow-backup-check.dump >/dev/null; rc=$?; rm -f /tmp/foriflow-backup-check.dump; exit $rc'
echo "Backup OK: $file"
