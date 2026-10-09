#!/usr/bin/env bash
# DESTRUCTIVE: replace the live database with a backup (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:?Usage: scripts/restore.sh backups/file.dump}"
[ -f "$file" ] || { echo "File not found: $file"; exit 1; }
echo "This REPLACES the live ForiFlow database with $file."
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
scripts/backup.sh
docker compose stop backend frontend
docker compose cp "$file" db:/tmp/foriflow-restore.dump >/dev/null
status=0
docker compose exec -T -e DUMP=/tmp/foriflow-restore.dump -e CONFIRM=RESTORE db sh -s < scripts/db/restore.sh || status=$?
docker compose exec -T db rm -f /tmp/foriflow-restore.dump >/dev/null 2>&1 || true
docker compose up -d backend frontend
exit "$status"
