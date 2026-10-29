#!/bin/sh
# DESTRUCTIVE: replace the live ForiFlow database with a backup.
# Only restore.bat / scripts/restore.sh call this, after taking a safety
# backup, asking for confirmation and stopping the API. Runs in the db container.
#
#   DUMP=/tmp/foriflow-restore.dump CONFIRM=RESTORE sh restore.sh
set -eu
STAGE=before-drop
# Callers must distinguish a safe refusal from a possibly partial restore.
trap 'rc=$?; if [ "$rc" -ne 0 ]; then if [ "$STAGE" = before-drop ]; then echo "RESTORE: NOT STARTED - database unchanged"; exit 3; else echo "RESTORE: INCOMPLETE - leave the API stopped"; exit 4; fi; fi' EXIT
DUMP="${DUMP:-/tmp/foriflow-restore.dump}"
LIVE="${POSTGRES_DB:?POSTGRES_DB is not set}"
USER_NAME="${POSTGRES_USER:?POSTGRES_USER is not set}"
if [ "${CONFIRM:-}" != "RESTORE" ]; then
    echo "Refusing: CONFIRM=RESTORE was not given."; exit 2
fi
[ -s "$DUMP" ] || { echo "Dump file missing or empty: $DUMP"; exit 1; }
pg_restore --list "$DUMP" >/dev/null
# This script only accepts ordinary local database names. Never interpolate
# arbitrary environment text into the SQL below, or replace a system database.
case "$LIVE" in ''|*[!a-zA-Z0-9_]*) echo "Invalid database name"; exit 1 ;; esac
case "$LIVE" in postgres|template0|template1) echo "Refusing a system database"; exit 1 ;; esac

# Nobody may be connected while the database is replaced.
psql -X -U "$USER_NAME" -d postgres -Atc \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$LIVE' AND pid <> pg_backend_pid()" >/dev/null
STAGE=after-drop
dropdb -U "$USER_NAME" "$LIVE"
createdb -U "$USER_NAME" "$LIVE"
pg_restore -U "$USER_NAME" -d "$LIVE" --no-owner --exit-on-error "$DUMP"
revision=$(psql -X -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT version_num FROM alembic_version')
applications=$(psql -X -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT COUNT(*) FROM applications')
audits=$(psql -X -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$LIVE" -Atc 'SELECT COUNT(*) FROM audit_logs')
[ -n "$revision" ] || { echo 'Missing migration version'; exit 1; }
echo "migration: $revision"
echo "applications: $applications"
echo "audit entries: $audits"
echo "RESTORE: DONE"
