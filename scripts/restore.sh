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
dump_in_db="/tmp/foriflow-restore-$(date +%s)-$$.dump"
cleanup() { docker compose exec -T db rm -f "$dump_in_db" >/dev/null 2>&1 || true; }
trap cleanup EXIT
abort_unchanged() {
    echo "RESTORE NOT STARTED. A prerequisite failed; the database was not replaced."
    docker compose up -d backend frontend || true
    exit 1
}
docker compose stop backend frontend || abort_unchanged
running=$(docker compose ps -q --status running backend frontend) || abort_unchanged
[ -z "$running" ] || abort_unchanged
docker compose cp "$file" "db:$dump_in_db" >/dev/null || abort_unchanged
docker compose exec -T db sh -c "test -s '$dump_in_db' && pg_restore --list '$dump_in_db' >/dev/null" || abort_unchanged
status=0
docker compose exec -T -e DUMP="$dump_in_db" -e CONFIRM=RESTORE db sh -s < scripts/db/restore.sh || status=$?
[ "$status" -ne 3 ] || abort_unchanged
if [ "$status" -ne 0 ]; then
    echo "RESTORE INCOMPLETE. The API and dashboard were left stopped. Recover using the safety backup."
    exit 1
fi
docker compose up -d backend frontend
exit "$status"
