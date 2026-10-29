# Monitoring calendar and safe editing — 24 October 2026

The EWS monitoring workspace now shows the reporting months of the selected
approved facility. Officers can see active records, earlier gaps, unknown
payment amounts and retained correction versions before entering figures.

## Behavior

- A new facility starts at its first unrecorded month. Later observations do
  not hide earlier gaps. A fully recorded term does not wrap around to month 1
  as a new-entry suggestion or invent a month beyond the facility term.
- The grid covers the recorded tenure, up to the existing 84-month limit.
  These are reporting periods since disbursement, not a contractual due-date
  calendar. Missing records are not treated as missed payments; a recorded
  zero payment is distinct from an unknown amount.
- Recorded months open as stored evidence. Managers/admins explicitly choose
  **Prepare correction** to load the stored figures, original data source and
  any existing score override. A written correction reason remains required.
  Analysts can inspect records and add new months, but cannot correct history.
- Correction submission now checks the form's required fields. An empty
  bureau/POS field cannot silently become zero through an out-of-form button.
- Switching month or facility with unsubmitted figures asks whether to keep
  editing or clear those figures. Values are never copied into another case.
  Refresh/closing the browser warns about unsubmitted figures. This does not
  provide persistent drafts or promise recovery after navigating away.
- A successful new record clears its input values and selects the next
  unrecorded month. A successful correction opens the corrected stored month.
- Loading failure, inconsistent case references, duplicate active observations
  or invalid history block entry until history can be verified. A concurrent
  HTTP 409 refreshes history without silently turning an attempted new record
  into a correction. A lost save response is reconciled through a fresh read;
  no automatic write retry occurs.
- Late responses cannot replace the selected facility's calendar, history,
  alert feed or overview. Existing backend authority and immutable-history
  checks remain authoritative.

No backend API, model artifact, model metric, credit policy, database schema or
contractual repayment calculation changed in this work.

## Verification and evidence

The final frontend unit suite passes **49 tests**, including 18 new coverage,
correction-preparation and dirty-form checks. It covers zero versus unknown
amounts, active-only corrections, a complete term, invalid/out-of-term history,
duplicate identifiers and preserving zero values and existing score overrides.
The frontend production build passes; the EWS workspace remains lazily loaded.

Browser fixtures were generated through real API calls using an isolated
SQLite test client and synthetic borrowers. Four API snapshots cover an initial
corrected history, a further correction, a new zero-payment month and a
concurrent duplicate. Browser POST bodies are compared with the actual API
inputs used for those snapshots. Original observation amounts remain on file
after correction.

An initial fixture helper imported the database model before pinning its test
configuration. Its API dependency used isolated storage, but startup could read
non-test configuration. The import order was corrected, storage and engine are
now pinned before imports, and a SQLite-only assertion prevents recurrence.
The helper was rerun successfully. Read-only fingerprints of all seven live
account/model/policy/borrower-data tables matched the previously verified
baseline, and the live trained-model registry remained unchanged. Logs of this
check and the pre-fix run were retained; no live recovery was required.

Private test logs, synthetic screenshots and fixture evidence are retained in
`archive/monitoring-calendar-2026-10-24/`.

The final browser runs passed **19 monitoring checks** and **12 existing Action
Desk checks**, with no browser exceptions or missing fixtures. They include
required-field validation, exact write payloads, late responses, concurrent
changes, lost save responses, read-only analyst corrections and an 84-month
calendar at a 390-pixel viewport. Desktop and mobile screenshots were inspected.
Cold-start route waits allow 30 seconds for loading; ordinary assertions retain
their short timeout. The production build passes and serves
`index-RAmmtzvI.js`; the EWS chunk is 41.96 kB (11.81 kB gzip).

## Local deployment

Only the frontend container was rebuilt and replaced. The backend and database
remained running and all three services report healthy. The frontend image is
`sha256:70af029805234a4faea85964441a578c231fe1b469313c4aa03cae4e005fb6f6`.
The previous image is retained as
`foriflow-frontend:before-monitoring-calendar-20261024-192725`.

Before deployment, the fresh backup
`backups/foriflow-20261024-192642-ba2f9da3b76f4a01929caa60b8267797.dump`
was restored into a disposable database. All ten table contents matched,
migration version matched, and the audit append-only guard was enforced. The
scratch database was dropped after verification. Backup SHA-256:
`CC1828D05DB3D80A81B8A8779B6E54FF5D9AD6F11104EA70CABA500422AA3537`.

A read-only comparison after deployment again found all ten table contents
identical. A separate browser session then verified the existing Idreesi account,
the live calendar against stored facility tenure and active observations,
read-only recorded-month display, mobile width, and trained-model readiness.
There were no browser exceptions. Its only write requests were normal login and
logout; no borrower, monitoring, policy or decision was changed. Credentials and
tokens were not saved to evidence files. This verification session was signed
out without signing out other sessions. Normal authentication audit/revocation
records can change following this login, after the full-content comparison.
