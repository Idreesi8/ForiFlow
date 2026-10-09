#!/bin/sh
# DESTRUCTIVE: replace the live ForiFlow database with a backup.
# Only restore.bat / scripts/restore.sh call this, after taking a safety
# backup, asking for confirmation and stopping the API. Runs in the db container.
#
#   DUMP=/tmp/foriflow-restore.dump CONFIRM=RESTORE sh restore.sh
set -eu
DUMP="${DUMP:-/tmp/foriflow-restore.dump}"
LIVE="${POSTGRES_DB:?POSTGRES_DB is not set}"
USER_NAME="${POSTGRES_USER:?POSTGRES_USER is not set}"
if [ "${CONFIRM:-}" != "RESTORE" ]; then
    echo "Refusing: CONFIRM=RESTORE was not given."; exit 2
fi
[ -s "$DUMP" ] || { echo "Dump file missing or empty: $DUMP"; exit 1; }
pg_restore --list "$DUMP" >/dev/null

# Nobody may be connected while the database is replaced.
psql -X -U "$USER_NAME" -d postgres -Atc \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LIVE' AND pid <> pg_backend_pid()" >/dev/null
dropdb -U "$USER_NAME" "$LIVE"
createdb -U "$USER_NAME" "$LIVE"
pg_restore -U "$USER_NAME" -d "$LIVE" --no-owner --exit-on-error "$DUMP"
echo "migration: $(psql -X -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT version_num FROM alembic_version')"
echo "applications: $(psql -X -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT COUNT(*) FROM applications')"
echo "audit entries: $(psql -X -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT COUNT(*) FROM audit_logs')"
echo "RESTORE: DONE"
