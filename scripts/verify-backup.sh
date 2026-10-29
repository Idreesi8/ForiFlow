#!/usr/bin/env bash
# Restore a backup into a scratch database and compare (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:-$(ls -t backups/*.dump 2>/dev/null | head -1)}"
[ -n "$file" ] && [ -f "$file" ] || { echo "No backup file. Run scripts/backup.sh first."; exit 1; }
dump_in_db="/tmp/foriflow-verify-$(date +%s)-$$.dump"
trap 'docker compose exec -T db rm -f "$dump_in_db" >/dev/null 2>&1 || true' EXIT
docker compose cp "$file" "db:$dump_in_db" >/dev/null
docker compose exec -T db sh -c "test -s '$dump_in_db' && pg_restore --list '$dump_in_db' >/dev/null"
docker compose exec -T -e DUMP="$dump_in_db" db sh -s < scripts/db/verify-restore.sh
