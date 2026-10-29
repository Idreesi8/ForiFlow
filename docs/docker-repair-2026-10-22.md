# Docker Desktop recovery — 22 October 2026

**24 October update:** the socket error recurred and was recovered again with
a guarded, repeatable script. See the [Action Desk deployment report](action-desk-2026-10-24.md#docker-recovery-and-safety-backup)
for that recovery and the new verified backup. The procedure below was a
successful local workaround, not a permanent upstream fix.

Docker Desktop's startup failure was traced to inaccessible Windows runtime
sockets. The screenshot identifies `dockerInference`; the secrets-engine
socket was affected too. With Docker fully stopped, only the two runtime
parent directories were renamed and recreated. Docker then started and its
29.7.2 engine answered successfully.

This follows the narrowly scoped workaround recorded in the matching
[Docker Desktop issue](https://github.com/docker/desktop-feedback/issues/554).
It is a local recovery, not an upstream software fix. If the same failure
returns, verify the affected sockets and stopped processes before repeating
the procedure; do not apply a general data-directory cleanup.

## Preserved data and recovery options

- The Docker data disks, settings, containers and volumes were not deleted or
  reset during the repair. No factory reset, reinstall or WSL unregister was used.
- Both original runtime directories remain alongside their replacements:
  `run.stale-20261022-181332-c825f9b3` under `%LOCALAPPDATA%\Docker`, and
  `docker-secrets-engine.stale-20261022-181332-c825f9b3` under `%LOCALAPPDATA%`.
- The existing main and QA stacks returned after Docker started. The QA stack
  was left unchanged.
- Before rebuilding the main application, a fresh logical backup was created:
  `backups/foriflow-20261022-181708-13de5cb16fb94464a5f7b9f6e8cd0e41.dump`.
  Actual Docker/PostgreSQL verification restored it into a new scratch database,
  compared all ten tables' complete content fingerprints and migration version,
  tested the audit deletion guard, then removed the scratch database: **PASS**.
  The live database was not restored.
- Original application images were tagged for local rollback:
  `foriflow-backend:before-local-refresh-20261022-181852` and
  `foriflow-frontend:before-local-refresh-20261022-181852`.
- Backend image contexts now exclude `.env` and `.env.*`; runtime credentials
  belong in the runtime environment rather than an image layer.

Private evidence is retained in `archive/docker-repair-2026-10-22/`, including
the repair manifest, rollback image identities, backup verification and build
logs. These contain local operational details and are not release assets.

The earlier [native PostgreSQL report](database-verification-2026-10-22.md)
records the 656-test Windows run performed before this Docker repair. A failed
manual service-start attempt was an earlier observation; recovery of the
runtime directories subsequently allowed Docker to start its engine normally.
No Windows service configuration or boot settings were changed.

## New application image checks

Both main application images built successfully from the current local source.
The frontend production entry is `index-CNhYeRUB.js`, 253.23 kB (85.43 kB gzip).
The backend build confirmed the trained artifacts were included; the installed
Python dependencies were recorded in the private evidence directory.

The new backend image ran **573 passing tests, three skipped, zero failures**
in 539.35 seconds using Python 3.12.15. Coverage includes the 300-applicant
approval-path stress check, model loading and SHAP reconstruction, API and
authentication boundaries, statements, reminder coverage, EWS and audit logic.
Two skipped checks require raw training data intentionally excluded from the
serving image; one requires a PostgreSQL test URL. Those checks were included
in the earlier complete 656-test Windows run. PostgreSQL test modules and the
host backup-wrapper module were explicitly excluded from this isolated run;
their earlier verification and the actual-container backup verification above
remain separate evidence, not extra Linux passes.

The container had no network access, no live database credentials or database
volume, and only the synthetic sample-statement directory mounted read only.
An initial unrestricted test run was interrupted for excessive CPU usage; the
completed run used two CPU cores and one math-library thread. A 90-second
diagnostic traceback during the stress check was informational; that check
completed and passed in 217.67 seconds. Two library deprecation warnings remain
(Starlette's test client and passlib's Python `crypt` import).

## Running application verification

The main backend and frontend were recreated from those tested images using
Compose's health wait. The database service and its persistent volume were
kept running; the QA stack was not redeployed. All three main containers are
running and healthy. The local dashboard is available at
<http://127.0.0.1:3000>.

| Check | Result |
| --- | --- |
| Backend `/health/ready` | 200, ready, production configuration, database reachable, ML engine serving |
| Dashboard `/api/health/ready` | 200 through the nginx proxy |
| Anonymous `/api/score/applications` | 401 |
| Backend `/docs` and dashboard `/api/docs` | 404 |
| Actual served JavaScript entry | `index-CNhYeRUB.js`, matching the new build |
| Fresh Chrome browser | Desktop and 390px mobile login checked; no page exceptions or horizontal overflow |
| Protected browser route | Requires sign in |
| Saved database records after refresh | All ten table fingerprints and counts identical to the verified pre-refresh backup |

The preservation check includes users, borrowers, policies, model versions,
applications, EWS history, alerts, audit records, login attempts and revoked
tokens. No officer account was used and no synthetic application was written
to the live database for these browser checks. Authenticated workflows were
tested in the isolated API suite; the earlier synthetic browser reports cover
the new statement and reminder screens.

Private evidence includes `deployment.log`, `live-readiness.json`,
`live-http-checks.json`, `live-containers.txt`, `post-refresh-content.json`,
`live-browser-checks.json` and desktop/mobile screenshots. Docker and the main
application are left running for use. The earlier Docker-build/startup test gap
is now closed for this local source and recorded image set.

An older backup still requires the signing-key/session-reset procedure in
[backup and restore](backup-restore.md) when restored to a live system. This
runtime repair does not change that behavior or the model's predictive accuracy.
