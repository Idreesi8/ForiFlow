#!/usr/bin/env bash
# Restore a backup into a scratch database and compare (Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")/.."
file="${1:-$(ls -t backups/*.dump 2>/dev/null | head -1)}"
[ -n "$file" ] && [ -f "$file" ] || { echo "No backup file. Run scripts/backup.sh first."; exit 1; }
docker compose cp "$file" db:/tmp/foriflow-restore.dump >/dev/null
trap 'docker compose exec -T db rm -f /tmp/foriflow-restore.dump >/dev/null 2>&1 || true' EXIT
docker compose exec -T -e DUMP=/tmp/foriflow-restore.dump db sh -s < scripts/db/verify-restore.sh
