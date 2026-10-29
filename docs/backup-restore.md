# Backup, restore and migrations

For the Docker pilot stack (PostgreSQL 16 in the `foriflow-db` container).
Windows scripts sit in the repository root; Linux/macOS equivalents are in
`scripts/`. All of them need ForiFlow running (`start.bat` / `start.sh`).

Backups contain borrower names, phone numbers, CNIC/NTN numbers and every
credit decision. Treat a `.dump` file like the database itself.

## Backup

```
backup.bat                  (Windows)
scripts/backup.sh           (Linux/macOS)
```

1. Runs `pg_dump -Fc` inside the database container.
2. Writes `backups/foriflow-YYYYMMDD-HHMMSS-<unique-suffix>.dump` (custom format,
   compressed). Concurrent or same-second backups do not overwrite one another.
3. Refuses a file under 1 KB and checks it is a readable archive
   (`pg_restore --list`). On failure the partial file is deleted.

The live database is only read. `backups/` is in `.gitignore`.

**Recommended routine:** daily during a pilot, and always before an update
(the preserved historical release scripts are not the current deployment workflow).
Copy each dump off the laptop to encrypted storage (BitLocker-encrypted USB
or the bank's backup share) and keep at least the last 7 daily and 4 weekly.

## Verify a backup (safe)

```
verify-backup.bat                         (newest backup)
verify-backup.bat backups\foriflow-20261009-213200.dump
scripts/verify-backup.sh [file]
```

Restores the file into a **new, uniquely named scratch** database, then compares
it with the live database and drops only the copy it created. An explicitly
supplied `SCRATCH_DB` that already exists is refused; it is never dropped.

- counts and SHA-256 fingerprints covering every row of `users`, `borrowers`,
  `credit_policies`, `model_versions`, `applications`, `ews_tracking`, `alerts`,
  `audit_logs`, `login_attempts` and `revoked_tokens`;
- the Alembic migration version;
- enabled audit append-only triggers exist on the copy's audit table, and a `DELETE` on the
  copy's audit trail is refused.

It ends with `RESULT: PASS` or `RESULT: FAIL` (Windows writes
`verify-backup-log.txt`). A fresh backup verified straight away should match
exactly when no writes happened in between. An older backup can fail comparison
because content changed, even if row counts are identical. This comparison is
not a continuous-write snapshot of the live database. Missing tables, unreadable
archives and cleanup failures cannot produce a pass.

Each backup, verification and restore uses its own temporary container path.
File-copy success, non-empty content and archive readability are checked before
a verification or restore begins. Windows automation can suppress the final
pause with `verify-backup.bat <file> --no-pause`.

## Restore (destructive)

```
restore.bat backups\foriflow-20261009-213200.dump
scripts/restore.sh backups/foriflow-20261009-213200.dump
```

1. Asks you to type `RESTORE`; anything else cancels.
2. Takes a safety backup of the current database (`backup.bat`). If that
   fails, nothing is restored.
3. Stops the API and dashboard and confirms neither is still running. Copies
   the chosen file to a unique container path and validates that copy.
4. Ends any remaining connections, drops and recreates the database, restores
   the dump (`pg_restore --exit-on-error`), and prints the migration version,
   application count and audit-entry count.
5. Starts the API and dashboard only after successful restore and schema checks.
   A pre-destructive refusal leaves the database unreplaced and attempts to
   resume services. A failure once dropping may have begun leaves both services
   stopped; recover deliberately with the safety backup. A failed restart is
   reported as a failure. The API applies any newer migrations on
   start, so restoring an older backup into a newer release upgrades it.

Afterwards: sign in, open Applications and the newest borrower, and (as admin)
check the audit trail. Everything recorded after the backup was taken is not in
the restored database; the safety backup from step 2 still has it.

Run `verify-backup.bat` on a file before you restore from it.

Logical backups also restore account and revocation state as it existed at the
backup date. These scripts do not yet enforce a global session reset. Before
using an older backup in a live deployment, include JWT signing-key rotation
and container recreation in the recovery procedure so later-revoked tokens
cannot become usable again. This round tests data restoration on disposable
databases; it does not perform a live recovery or change the signing key.

Windows automation can suppress only the final pause with
`restore.bat <file> --no-pause`; typing `RESTORE` is still required.

## Tested

The [22 October database verification report](database-verification-2026-10-22.md)
records the current native Windows PostgreSQL tests and executed Windows/Bash
wrapper regressions. Docker engine startup remains a separate host limitation.

Release 2.3.0 was checked on a copy of the pilot database (24 applications,
20 borrowers, 160 audit entries, migration `0010_security_hardening`):
backup, verify (`RESULT: PASS`, all counts equal, triggers present, delete
refused), a destructive restore into a scratch target database (an extra row
added after the backup was gone afterwards; counts matched the backup), and
the API started against the restored database and served sign-in, scoring
and the audit trail. On the laptop the update script runs backup and
verify against the real database (read-only).

## Migrations

- Alembic owns the PostgreSQL schema (`backend/alembic/versions/`). The API
  applies `upgrade head` at start-up; SQLite (tests, development) uses
  `create_all`.
- Before any upgrade: `backup.bat`, then `verify-backup.bat`. The update
  scripts take the backup automatically and stop if it fails.
- Each migration writes a `migration.applied` entry to the audit trail.
- Downgrade (only with a backup in hand), from `backend/` with the database
  URL set: `alembic downgrade <revision>`. 0010 → 0009 drops `is_active`,
  `login_attempts` and `revoked_tokens`; no credit data is touched.
- Migrations that would rewrite or remove data must say so in their
  docstring and are released only with a tested downgrade or a documented
  restore path.

## Rotating the database password

1. `docker compose exec db psql -U <POSTGRES_USER> -d <POSTGRES_DB> -c "\password <POSTGRES_USER>"`
   (prompts twice; nothing is echoed or stored in history).
2. Put the same value in `POSTGRES_PASSWORD` in `.env`.
3. `docker compose up -d backend` so the API reconnects with it.
