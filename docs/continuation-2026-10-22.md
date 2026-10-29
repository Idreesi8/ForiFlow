# ForiFlow follow-up reliability review — 22 October 2026

The later [database verification report](database-verification-2026-10-22.md)
supersedes the PostgreSQL test skips recorded here. Docker startup remains
separately unverified.

This round fixes an operational omission in reminders and adds recovery from
page loading failures. It follows the earlier [improvements](improvements-2026-10-22.md).
All changes are local and unreleased.

## Reminders preserve missing months

Previously the next installment was `latest recorded month + 1`. Recording
month 3 could therefore hide missing months 1 and 2; for a three-month facility
it could remove the reminder entirely. The API now finds the first month
without an active EWS record, within the facility's tenure.

For an approval recorded on 31 January 2026 and an evaluation on 15 March:

| Active months recorded | First missing installment | Indicative due date | Result |
| --- | --- | --- | --- |
| 3 | 1 | 28 February | Overdue; explicit recording-gap warning |
| 1, 3 | 2 | 31 March | Not yet inside the seven-day reminder window |
| 1, 2, 3 | None | None | No unrecorded-installment reminder |

Dates always use the original approval-day anchor. February's clipped day does
not move March's due date to the 28th. A latest recorded status of Default still
goes to remedial management, outside ordinary reminders.

Each reminder includes `latest_recorded_month`, `has_recording_gap` and
`recorded_months_without_amount`. Only active observations count. A corrected
record does not double its month or amount; its superseded original remains
history. Portfolio totals and the recorded-amount rounding tolerance are
unchanged. Coverage and statuses use two portfolio-wide queries without a query
per facility.

Unknown amounts remain unknown and are excluded from arrears arithmetic;
missing EWS months do not become fabricated payment records. The UI explicitly
states that an EWS record alone does not prove payment. For example, a missing
month 1 with a recorded month 3 shortfall now refers to that shortfall as
unpaid in recorded installments, avoiding the incorrect claim that month 3
was earlier than month 1.

The displayed schedule is indicative: principal divided by tenure, monthly
from recorded approval. Interest and fees are excluded, and no separate
contractual disbursement date is stored. Officers must check agreed dates,
actual amounts and receipts before sending any draft. ForiFlow still sends no
messages. English and Roman Urdu drafts now retain paisa, matching the API's
displayed installment amount.

## Page recovery

React error boundaries wrap the page content and the entry routes. A failed
page download or render produces a plain recovery message with a Reload page
button. The officer navigation stays available for a page-level failure, and
changing route resets that page boundary. Reload fetches a fresh document and
retries a cached failed dynamic import. Normal loading remains inside the
persistent officer workspace.

Chrome verification intentionally returns HTTP 503 for a production page
chunk. It checks the recovery message, working navigation, boundary reset and
successful reload. It then checks real API-generated synthetic reminder
fixtures at desktop and 390-pixel widths. The API responses in this browser
test are intercepted; separate backend regressions exercise persistence,
month gaps, month-end dates, unknown amounts, shortfalls, defaults and
corrections in an isolated SQLite database.

## Windows startup

`start.ps1 -NoBuild` now passes `--no-build` to Compose; previously the switch
was accepted but had no effect. The launcher no longer advertises `/docs` in
production, where documentation endpoints are disabled. Its background Docker
Desktop launch requests a hidden window. PowerShell syntax validation passes;
actual Docker startup remains unverified because the engine was unavailable.
The backend guide also now describes fractional policy boundaries and officer
decisions on every application, including manager authority and escalation.

## Verification

The final full native Windows backend run completed with **575 passed,
51 skipped, zero failures and zero errors** in 147.45 seconds. The existing
Starlette/httpx TestClient deprecation warning remains.

| Check | Result |
| --- | --- |
| Complete backend suite | 575 passed, 51 PostgreSQL tests skipped; 626 collected |
| Focused reminders / portfolio / monitoring run | 68 passed before the additional correction regression |
| New reminder regressions | Seven cases included in the final full suite |
| Frontend tests | 27 passed |
| Production build | Passed; main JavaScript entry 253.23 kB / 85.43 kB gzip |
| Chrome production preview | Injected chunk-failure recovery and reminder desktop/mobile checks passed |
| PowerShell syntax | Passed |

Browser screenshots were visually reviewed. Evidence and synthetic fixtures
are kept under the ignored `archive/continuation-2026-10-22/` directory.

The model, predictive metrics, policy thresholds and decision authority are
unchanged. No production migration, deployment or real customer-data change
was performed. PostgreSQL-specific tests still need a configured PostgreSQL
instance; passing SQLite tests do not verify those behaviors on PostgreSQL.
