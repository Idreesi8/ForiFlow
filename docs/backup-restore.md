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
2. Writes `backups/foriflow-YYYYMMDD-HHMMSS.dump` (custom format, compressed).
3. Refuses a file under 1 KB and checks it is a readable archive
   (`pg_restore --list`). On failure the partial file is deleted.

The live database is only read. `backups/` is in `.gitignore`.

**Recommended routine:** daily during a pilot, and always before an update
(the `aa-update-*.bat` scripts already take `backups/before-<version>.dump`).
Copy each dump off the laptop to encrypted storage (BitLocker-encrypted USB
or the bank's backup share) and keep at least the last 7 daily and 4 weekly.

## Verify a backup (safe)

```
verify-backup.bat                         (newest backup)
verify-backup.bat backups\foriflow-20261009-213200.dump
scripts/verify-backup.sh [file]
```

Restores the file into a **scratch** database (`foriflow_restore_check`),
then compares it with the live database and drops the scratch copy:

- row counts of `users`, `borrowers`, `credit_policies`, `model_versions`,
  `applications`, `ews_tracking`, `alerts`, `audit_logs`;
- the Alembic migration version;
- the newest audit entry (id, action, time) is identical;
- the audit append-only triggers exist in the copy, and a `DELETE` on the
  copy's audit trail is refused.

It ends with `RESULT: PASS` or `RESULT: FAIL` (Windows writes
`verify-backup-log.txt`). A fresh backup verified straight away should match
exactly; an older one shows fewer rows where work happened since.

## Restore (destructive)

```
restore.bat backups\foriflow-20261009-213200.dump
scripts/restore.sh backups/foriflow-20261009-213200.dump
```

1. Asks you to type `RESTORE`; anything else cancels.
2. Takes a safety backup of the current database (`backup.bat`). If that
   fails, nothing is restored.
3. Stops the API and dashboard.
4. Ends any remaining connections, drops and recreates the database, restores
   the dump (`pg_restore --exit-on-error`), and prints the migration version,
   application count and audit-entry count.
5. Starts the API and dashboard. The API applies any newer migrations on
   start, so restoring an older backup into a newer release upgrades it.

Afterwards: sign in, open Applications and the newest borrower, and (as admin)
check the audit trail. Everything recorded after the backup was taken is not in
the restored database; the safety backup from step 2 still has it.

Run `verify-backup.bat` on a file before you restore from it.

## Tested

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
