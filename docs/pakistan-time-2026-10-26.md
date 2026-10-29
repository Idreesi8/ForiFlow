# Pakistan calendar consistency — 26 October 2026

Action Desk already used Asia/Karachi, but observation defaults and validation,
alert overdue flags, deadline validation and reminder calculations used UTC or
the server's calendar. The shared display formatter used the device timezone.
Between midnight and 05:00 PKT, an overdue task could therefore disagree with
its alert, and an observation dated today could be rejected as future-dated.
An approval near UTC midnight could also anchor its indicative reminder schedule
to the wrong Pakistan calendar day.

## Behavior

- A shared backend calendar uses Asia/Karachi for observation defaults, future
  validation, the earliest observation date, alert deadlines, overdue flags,
  reminder age and approval-day anchors, and Action Desk dates. Naive SQLite
  timestamps are interpreted as UTC. Stored instants and authentication expiry
  semantics remain UTC; no schema or stored record was rewritten.
- The alert feed, overview, facility state and Action Desk agree at precisely
  19:00 UTC, Pakistan midnight. A deadline today is not overdue. Yesterday cannot
  be assigned as a new action deadline, even while UTC is still on yesterday.
- New observation dates cannot precede the Pakistan day on which the application
  was scored. Corrections may retain their original recorded date, including an
  older row accepted under the previous UTC rule. Changing the date still applies
  the new lower bound. An omitted correction date retains the original date.
- Shared timestamp displays use Pakistan time and show **PKT**. Date-only fields
  retain their calendar day rather than shifting with the device timezone.
  Invalid calendar dates are displayed as unknown. The footer states the timezone.
- Monitoring defaults and input limits use Pakistan today. Deadline fields have
  the same Pakistan lower limit and native form validation before submission.
  Open date limits update at midnight and on focus/visibility after laptop sleep,
  without replacing the officer's selected date or financial figures.
- Reminder schedules remain indicative, principal-only and subject to verification
  against the actual agreement and receipts. The approval anchor now uses PKT.
  Opening a page does not send a reminder or change a decision.

The frontend uses the device clock and the API uses the server clock. Both use
the same timezone rule; the API remains authoritative if a clock is incorrect.
Existing fetched alert/worklist snapshots still require refresh to show a new
overdue result. Updating input limits does not silently reload the worklist.
Legacy observation dates are retained as recorded; no historical date migration
was attempted. Windows installations explicitly require the IANA `tzdata` package.

## Verification

The focused backend tests cover exact midnight, month/year/leap boundaries,
offset-aware and naive timestamps, both observation endpoints, corrections,
legacy date retention, each alert-deadline action, agreement across four read
views, and approval-based reminder anchoring. Additional API regressions cover
scoring, decisions, roles, security, whole-register access and reminders.

The **53 frontend tests pass**. **11 new browser scenarios pass** with synthetic
responses captured from the real API in isolated memory. They verify UTC,
America/Los_Angeles, Pacific/Kiritimati and Asia/Karachi device settings, exact
request bodies, future-date and past-deadline validation without writes,
midnight updates, a laptop-wake clock jump, retained entries and a 390px layout.
There were no browser exceptions or missing fixture routes. The mobile rendering
was visually inspected.

Existing browser regressions also pass: **7 scoring/statement/memo**, **12 Action
Desk**, **19 monitoring**, **11 complete register** and **11 interface** checks.
Private test fixtures, logs and deployment evidence are retained under
`archive/pakistan-time-2026-10-26/`.

The final Windows run passed **314 backend tests** (71 focused and 243 broader
regressions). A separate private PostgreSQL cluster passed **12 integration
tests**, then was stopped and its generated data removed. The existing **18
work-protection browser checks** also pass, bringing this frontend verification
to **89 browser scenarios** in total. This is a selected regression run, not a
claim that the entire repository test suite was rerun.

Docker dependency resolution initially selected newer FastAPI, Starlette and
certificate-package versions. That intermediate image was never deployed.
`backend/constraints-linux.txt` now records all 56 non-pip distributions in the
previously serving Linux Python 3.12 runtime; Docker installs requirements subject
to these exact constraints. Deliberate dependency upgrades must update this file
and repeat the relevant regression and trained-model readiness checks.
The final image's package inventory matches the prior running image exactly:
**57 distributions including pip**, with no version or package-count differences.
The same **314 backend tests pass in the final Linux Python 3.12 image**, with
networking disabled and only the public sample CSV directory mounted read-only.
The first attempt lacked that sample mount and stopped during collection; it
performed no tests or live writes. The corrected run passed in 116 seconds.

## Runtime recovery and backup

Docker Desktop initially failed with the previously documented inaccessible
`dockerInference` socket. The guarded recovery script confirmed Windows error
1920 and the recent matching log, previewed its exact targets, then preserved
the two socket-only runtime directories and recreated them. It did not reset
Docker, change settings, delete volumes or touch database disks. Recovery manifest:
`archive/docker-runtime-recovery/20261026-154352-64b77ac2/runtime-folder-repair.json`.

Before deployment, backup
`backups/foriflow-20261026-155016-c8b3e5bec1a84a089a0b686ffd926032.dump`
was restored into a disposable database. All ten table-content fingerprints and
the migration version matched, the audit append-only guard was enforced, and
the scratch database was dropped. Backup SHA-256:
`BFF2EE0A284ACB588FBC82C6C1EF6553D798312CB874F6F7613338963A4DB3F0`.
Both running application images were tagged before the rebuild; rollback tags
and original image IDs are recorded in `deployment-baseline.json`.

## Deployment and live verification

Only the backend and frontend application containers were replaced. PostgreSQL
was left running. All three services are healthy. The deployed images are:

- Backend: `sha256:8168ff0e004b4c4d042ec16b40bf815219952d342977df2ec41e6d34d3cbfc16`
- Frontend: `sha256:679413211af28352edb7f8817e5df2556e576d2cf314c498b6f8940f74599daa`

The page serves `index-DZF2aiDc.js`. The previous application images remain as
`foriflow-backend:before-pakistan-time-20261026-155423` and
`foriflow-frontend:before-pakistan-time-20261026-155423`.

All ten live table-content fingerprints matched the verified backup both before
and after deployment, before the final login verification. A separate browser
session then verified the existing Idreesi account, read-only selection of a real
facility's unrecorded month, the Pakistan observation default/maximum, explicit
timezone guidance and a 390px mobile layout with the device set to UTC+14. The
trained ML engine passed readiness. There were no browser exceptions; the only
write requests were `/api/auth/login` and `/api/auth/logout`. No assessment,
credit decision, observation, alert action, policy, account or model was changed
by the verification. Authentication audit/revocation records can change normally
after that final login, following the complete-content comparison.

The verification session was signed out. Credentials and tokens were not written
to evidence files. The temporary preview process was checked by executable and
command line, then stopped; the live application and Docker Desktop remain running.
