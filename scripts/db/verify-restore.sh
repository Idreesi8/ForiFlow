#!/bin/sh
# Restore only into a newly created scratch database; live data is read only.
set -eu
DUMP="${DUMP:-/tmp/foriflow-verify.dump}"
LIVE="${POSTGRES_DB:?POSTGRES_DB is not set}"
USER_NAME="${POSTGRES_USER:?POSTGRES_USER is not set}"
SCRATCH="${SCRATCH_DB:-foriflow_verify_$(date +%s)_$$}"
TABLES="users borrowers credit_policies model_versions applications ews_tracking alerts audit_logs login_attempts revoked_tokens"
created=0
cleanup() {
    rc=$?
    trap - EXIT HUP INT TERM
    if [ "$created" -eq 1 ]; then
        if dropdb -U "$USER_NAME" "$SCRATCH"; then
            echo "scratch database dropped: $SCRATCH"
        else
            echo "FAIL scratch cleanup; remove only this run's database: $SCRATCH"
            rc=1
        fi
    fi
    if [ "$rc" -eq 0 ]; then echo "RESULT: PASS"; else echo "RESULT: FAIL"; fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
fail() { echo "FAIL $1"; exit 1; }
q() {
    output=$(psql -X -v ON_ERROR_STOP=1 -U "$USER_NAME" -d "$1" -Atc "$2") || return $?
    # Native Windows psql emits CRLF even when invoked from Git Bash.
    printf '%s\n' "$output" | tr -d '\r'
}

[ -s "$DUMP" ] || fail 'dump file missing or empty'
[ "$SCRATCH" != "$LIVE" ] || fail 'scratch name equals the live database'
case "$SCRATCH" in ''|*[!a-zA-Z0-9_]*) fail 'invalid scratch database name' ;; esac
case "$SCRATCH" in postgres|template0|template1) fail 'system database name' ;; esac
pg_restore --list "$DUMP" >/dev/null || fail 'dump is not a readable archive'
# Never drop a pre-existing database, even if a caller supplies its name.
createdb -U "$USER_NAME" "$SCRATCH" || fail 'could not create a new scratch database'
created=1
pg_restore -U "$USER_NAME" -d "$SCRATCH" --no-owner --no-privileges --exit-on-error "$DUMP" || fail 'pg_restore reported an error'
echo 'restore: ok'

# 0011 receipts are durable business state. Older matching schemas may omit
# them, but a current backup must preserve both their presence and contents.
live_receipts=$(q "$LIVE" "SELECT to_regclass('public.score_submissions') IS NOT NULL") || fail 'cannot inspect live receipts'
copy_receipts=$(q "$SCRATCH" "SELECT to_regclass('public.score_submissions') IS NOT NULL") || fail 'cannot inspect restored receipts'
[ "$live_receipts" = "$copy_receipts" ] || fail 'assessment receipt table presence differs'
if [ "$live_receipts" = t ]; then TABLES="$TABLES score_submissions"; fi

for table in $TABLES; do
    # Hash every row, sort row hashes (including duplicates), then hash the
    # sequence. Counts alone cannot detect edited balances or earlier audits.
    query="SELECT count(*) || ':' || encode(sha256(convert_to(COALESCE(string_agg(h, '' ORDER BY h), ''), 'UTF8')), 'hex') FROM (SELECT encode(sha256(convert_to(row_to_json(t)::text, 'UTF8')), 'hex') AS h FROM public.$table t) rows"
    live=$(q "$LIVE" "$query") || fail "cannot read live $table"
    copy=$(q "$SCRATCH" "$query") || fail "cannot read restored $table"
    if [ "$live" = "$copy" ]; then
        echo "content $table: identical ($live)"
    else
        fail "content differs for $table (backup may be older than live data)"
    fi
done
live_v=$(q "$LIVE" 'SELECT version_num FROM alembic_version') || fail 'cannot read live migration'
copy_v=$(q "$SCRATCH" 'SELECT version_num FROM alembic_version') || fail 'cannot read restored migration'
[ -n "$live_v" ] && [ "$live_v" = "$copy_v" ] || fail 'migration version differs or is empty'
echo "migration: identical ($live_v)"

triggers=$(q "$SCRATCH" "SELECT COUNT(*) FROM pg_trigger WHERE tgrelid = 'public.audit_logs'::regclass AND tgname IN ('audit_logs_no_change','audit_logs_no_truncate') AND tgenabled = 'O'") || fail 'cannot inspect audit triggers'
[ "$triggers" = 2 ] || fail 'audit triggers missing or disabled'
if q "$SCRATCH" 'DELETE FROM audit_logs' >/dev/null 2>&1; then
    fail 'restored audit trail permits deletion'
fi
echo 'audit append-only deletion guard: enforced'
