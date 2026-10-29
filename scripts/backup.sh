#!/usr/bin/env bash
# Back up the ForiFlow database (Linux/macOS). Same as backup.bat.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
file=$(mktemp "backups/foriflow-$(date +%Y%m%d-%H%M%S)-XXXXXX.dump")
check="/tmp/foriflow-backup-check-$(date +%s)-$$.dump"
complete=0
cleanup() {
    rc=$?
    trap - EXIT
    docker compose exec -T db rm -f "$check" >/dev/null 2>&1 || true
    if [ "$complete" -ne 1 ]; then rm -f "$file"; fi
    exit "$rc"
}
trap cleanup EXIT
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file"
[ "$(wc -c < "$file")" -ge 1000 ] || { echo "BACKUP FAILED"; rm -f "$file"; exit 1; }
docker compose cp "$file" "db:$check" >/dev/null
docker compose exec -T db pg_restore --list "$check" >/dev/null
complete=1
echo "Backup OK: $file"
