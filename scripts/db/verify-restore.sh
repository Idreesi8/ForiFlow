#!/bin/sh
# Restore a ForiFlow backup into a SCRATCH database and compare it with the
# live one. Read-only for the live database; the scratch copy is dropped at
# the end. Runs inside the db container (backup.bat / verify-restore.bat feed
# it), or anywhere psql/pg_restore can reach the server (PGHOST, PGPORT).
#
#   DUMP=/tmp/foriflow-restore.dump sh verify-restore.sh
#
# Prints one line per check and ends with "RESULT: PASS" or "RESULT: FAIL".
set -u
DUMP="${DUMP:-/tmp/foriflow-restore.dump}"
LIVE="${POSTGRES_DB:?POSTGRES_DB is not set}"
USER_NAME="${POSTGRES_USER:?POSTGRES_USER is not set}"
SCRATCH="${SCRATCH_DB:-foriflow_restore_check}"
TABLES="users borrowers credit_policies model_versions applications ews_tracking alerts audit_logs"
status=0

q() { psql -X -U "$USER_NAME" -d "$1" -Atc "$2"; }

if [ ! -s "$DUMP" ]; then
    echo "FAIL dump file missing or empty: $DUMP"; echo "RESULT: FAIL"; exit 1
fi
if [ "$SCRATCH" = "$LIVE" ]; then
    echo "FAIL scratch database name equals the live database"; echo "RESULT: FAIL"; exit 1
fi

echo "dump entries: $(pg_restore --list "$DUMP" | grep -c ';')"
dropdb -U "$USER_NAME" --if-exists "$SCRATCH" >/dev/null 2>&1
createdb -U "$USER_NAME" "$SCRATCH" || { echo "RESULT: FAIL"; exit 1; }
if ! pg_restore -U "$USER_NAME" -d "$SCRATCH" --no-owner --no-privileges --exit-on-error "$DUMP"; then
    echo "FAIL pg_restore reported an error"
    dropdb -U "$USER_NAME" --if-exists "$SCRATCH" >/dev/null 2>&1
    echo "RESULT: FAIL"; exit 1
fi
echo "restore: ok"

for table in $TABLES; do
    live=$(q "$LIVE" "SELECT COUNT(*) FROM $table" 2>/dev/null || echo "missing")
    copy=$(q "$SCRATCH" "SELECT COUNT(*) FROM $table" 2>/dev/null || echo "missing")
    if [ "$live" = "$copy" ]; then mark="ok"; else mark="DIFFERENT"; status=1; fi
    echo "rows $table: live=$live restored=$copy $mark"
done

live_v=$(q "$LIVE" "SELECT version_num FROM alembic_version")
copy_v=$(q "$SCRATCH" "SELECT version_num FROM alembic_version")
[ "$live_v" = "$copy_v" ] && mark="ok" || { mark="DIFFERENT"; status=1; }
echo "migration: live=$live_v restored=$copy_v $mark"

last="SELECT id || '|' || action || '|' || occurred_at FROM audit_logs ORDER BY id DESC LIMIT 1"
[ "$(q "$LIVE" "$last")" = "$(q "$SCRATCH" "$last")" ] && mark="ok" || { mark="DIFFERENT"; status=1; }
echo "newest audit entry identical: $mark"

triggers=$(q "$SCRATCH" "SELECT COUNT(*) FROM pg_trigger WHERE tgname IN ('audit_logs_no_change','audit_logs_no_truncate')")
[ "$triggers" = "2" ] && mark="ok" || { mark="MISSING"; status=1; }
echo "audit append-only triggers restored: $triggers/2 $mark"

if psql -X -U "$USER_NAME" -d "$SCRATCH" -c "DELETE FROM audit_logs" >/dev/null 2>&1; then
    echo "audit trail refuses deletion in the restored copy: NO"; status=1
else
    echo "audit trail refuses deletion in the restored copy: ok"
fi

dropdb -U "$USER_NAME" --if-exists "$SCRATCH"
echo "scratch database dropped: $SCRATCH"
if [ "$status" -eq 0 ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL"; fi
exit "$status"
