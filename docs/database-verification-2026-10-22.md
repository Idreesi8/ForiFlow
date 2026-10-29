# ForiFlow database and recovery verification — 22 October 2026

**Later update:** Docker was subsequently recovered from stale runtime sockets.
See the [Docker recovery report](docker-repair-2026-10-22.md) for actual
container backup verification and the later application build. The Docker
startup observations below describe the earlier Windows test round.

The previously skipped PostgreSQL integration checks now run on this Windows
laptop. Recovery scripts also fail closed on failed service stops, failed
copies, unreadable archives and incomplete restores. Changes are local and
unreleased; no pilot database was restored, migrated or edited for this work.

## Isolated PostgreSQL on Windows

Docker Desktop could not bring up its engine. Windows refused this session's
attempt to start `vmcompute`; no system settings, boot options or Windows
services were reconfigured. There was no laptop reboot.

A portable PostgreSQL 16.15 runtime was obtained from the
[official EDB binary distribution](https://www.enterprisedb.com/download-postgresql-binaries),
linked by the [PostgreSQL Windows download page](https://www.postgresql.org/download/windows/).
It lives under the ignored `.local/postgresql-16.15/` directory. Only server,
client, library and shared-data files were extracted, omitting bundled GUI
tools: 1,635 files, 128,073,989 bytes uncompressed. Resumable byte-range
downloads were used because the full archive transfer stalled. Every selected
member passed ZIP CRC verification; core executable SHA-256 hashes and the
source URL were recorded. This was not a full-archive SHA-256 verification.

`scripts/test-postgres.ps1` uses that runtime or an explicit `-BinaryDirectory`.
It initializes a new UUID-named cluster with a random password and SCRAM auth,
binds `127.0.0.1:55432`, creates a disposable database and supplies only that
test URL to pytest. It restores its process environment, stops the private
server, saves logs under `archive/postgres-tests/`, then removes only the
invocation's generated data after shutdown. An unconfirmed shutdown retains
the test data for investigation. No Windows PostgreSQL service is installed.

The first isolated run executed all **51 previously skipped PostgreSQL
tests**, all passing. They cover SQLite/PostgreSQL parity, migrations and
legacy data, decision-policy bands, officer workflow, immutable EWS history,
model provenance, authentication and database audit guards. The final combined
run passed all **656 tests with zero failures, errors or skips**, in 544.10
seconds. One existing Starlette/httpx TestClient deprecation warning remains.
This used PostgreSQL 16.15 on Windows; it is not a Linux/container test of the
Compose file's PostgreSQL 16.6 image.

## Recovery changes

- Backup filenames and temporary container paths include a unique suffix;
  same-second or parallel operations do not reuse a selected dump.
- Restore checks the stop result and confirms the API/dashboard are no longer
  running. A successful copy must also be non-empty and a readable archive.
- The database restore script returns 3 for refusal before destructive work and
  4 when dropping might have started. Callers restart after a safe refusal but
  leave services stopped after a possibly partial restore. Failed restart is
  not reported as success.
- Restored migration, application and audit queries must succeed. A readable
  non-ForiFlow archive cannot be declared a completed application recovery.
- Backup verification creates a new scratch database; it never first drops a
  database with that name. Its cleanup only drops a database it created.
- Verification compares all row contents using sorted SHA-256 row digests,
  their combined digest and row counts, covering the credit/EWS/audit tables
  and security-state tables. A balance/account change with identical counts
  cannot slip through a count-only comparison. Missing queries and cleanup
  failures fail the verification.
- Verification checks enabled audit triggers on `public.audit_logs` and tests
  that deletion is refused in the scratch copy. The live database is read only.

The current logical restore still restores security state from the snapshot;
it does not automatically force a new global login epoch or rotate JWT keys.
Signing-key rotation and container recreation must be part of a live recovery
procedure when older revocation state is restored. That session-reset behavior
was not added or claimed by this patch. No live recovery was attempted.

## Executed verification

Windows batch files execute under `cmd.exe`; Bash wrappers execute under Git
Bash. A compiled test-only Docker stub injects failures. These tests exercise
actual control flow, rather than looking for guard words in the source. Real
PostgreSQL cases create additional UUID-named databases on the disposable test
server and invoke the real `pg_dump`, `pg_restore`, `psql`, `createdb` and
`dropdb` tools. No existing backup/customer file is restored into a live target.

| Check | Result |
| --- | --- |
| Previously skipped PostgreSQL cases | 51 passed |
| First wrapper failure/success run | 22 passed before additional restart coverage |
| First real backup/restore run | 5 passed before additional incomplete-schema coverage |
| Final combined full suite | 656 passed; zero skipped, failed or errored |
| Recovery regressions in final suite | 24 Windows/Bash wrapper cases + 6 real PostgreSQL cases passed |
| Shell and PowerShell syntax | Passed |
| Existing data/configuration/backups/model preservation | 51 protected files checked; all hashes unchanged |

The final combined suite includes added cases for failed restarts and readable
archives without a complete application schema. Evidence is retained in the
private archive. The frontend was unchanged in this round; its previous 27
tests, production build and production-preview checks remain the latest UI
verification.

Final suite log: `archive/postgres-tests/afb84e281243487b8b09d49aadc80b1c/pytest.log`.
The private server shut down successfully and its generated cluster data was
removed. Download scratch archives were removed after extraction; the useful
portable runtime remains available for future test runs. Supplemental evidence
is in `archive/deployment-verification-2026-10-22/`.

This closes the PostgreSQL test gap. It does not verify Docker Compose image
builds or container startup on this laptop, certify deployment security, or
change model predictive accuracy.
