# Complete application register — 26 October 2026

Previously, Applications downloaded at most 200 assessments and searched and
sorted only that list. An older case could appear absent despite being on file.
The empty-result message also suggested scoring a new application even when
the cause was simply an active search or filter.

## Builder and officer perspectives

The Applications workspace now searches all saved assessments through the
authenticated, read-only `GET /score/register` endpoint. Names, borrower
references and exact case IDs are supported; SQL wildcard characters in search
text are treated literally. Officer-decision filters include Pending, Escalated,
Approved, Rejected and Superseded, with an Awaiting decision shortcut for Pending
and Escalated together. A model recommendation never becomes an officer decision.

Sorting runs over the whole matching set, with a stable case-ID tie-breaker.
Pages have an explicit size and total, and table headings and sort controls use
the same server order. Counts include retained superseded assessments: they are
counts of saved assessments, unlike dashboard totals that exclude replaced cases.
Page contents can change when other officers add or decide cases; this endpoint
does not lock the portfolio. Refresh reads the current register.

Search, filters, sort and page live in the URL. Returning from a report with the
browser Back button restores the search. Changed filters start at page one;
out-of-range pages reconcile to the last available page. Pending searches, failed
requests and late responses cannot present an earlier result set as current.
No-match guidance offers resetting filters; an actually empty register offers a
new assessment.

Mobile users see case cards with separate recommendation and decision labels,
the facility, score and an explicit case-opening action. Desktop users can open
the business name directly without scrolling to the report column. An older
deep-linked case is included in the report selector even when outside its recent
200-case list, which is now labelled as a recent-case list with a link to the
complete register.

The register query reads only columns used by the list, with two SELECT statements
in addition to the existing authentication reads.
It excludes phone numbers, statement evidence, review notes and internal policy
payloads from its list response. Authentication remains the existing officer
authentication. Page sizes, search length, sort keys, direction and offset are
validated. Existing list and detail APIs, scoring rules, model artifacts,
authority rules and database schema are unchanged.

## Verification

- **237 backend regression tests pass** on native Windows and in the new Linux
  container image without network access or live database connection, including 27 new
  register checks, existing scoring, human decisions, security, Action Desk and
  EWS routes.
- A separate **private PostgreSQL check passes**, covering literal text search,
  borrower references, exact IDs, global sorting, status counts and retrieval
  beyond 200 cases. The temporary server was stopped and its generated data
  removed by the guarded test runner.
- **49 frontend tests pass**, and the frontend production build succeeds.
- **11 register browser scenarios pass** against 214 isolated synthetic cases.
  The older assessment and its stored explanation were created through the real
  API in memory. Cases cover paging, Back navigation, older-case review, search,
  status semantics, sorting, failures, delayed replies, mobile cards at 320/390
  pixels and out-of-range pages. Screenshots were visually inspected.
- Existing **12 Action Desk** and **7 scoring/CSV/explanation/memo** browser
  checks pass. No browser exceptions occurred. No live credit or monitoring
  decision was exercised by these tests.

Work started on 25 October and continued on 26 October. Private fixtures,
verification logs and screenshots remain in
`archive/case-register-2026-10-25/`.

## Deployment and live checks

Backend and frontend were rebuilt and deployed after both platform test runs;
PostgreSQL remained running. All three services are healthy. The dashboard serves
`index-CAQUoGe5.js`. Deployed images:

- Backend: `sha256:34c21969f8cf90584cbc5052eb73dd8ca7a4cd3dc383be6dc8c6133fe69a2376`.
- Frontend: `sha256:e643a7a474966e8081a8340f14e34d038d8bb26dbc0e7fe2e2c35d783a2c5562`.

Previous images are retained as
`foriflow-backend:before-complete-register-20261026-000350` and
`foriflow-frontend:before-complete-register-20261026-000350`.

The fresh backup
`backups/foriflow-20261026-000254-e862fa44a85542739e514f5e5d55706e.dump`
was restored into a disposable database. All ten table contents and the migration
version matched, and the audit append-only guard was enforced. The scratch
database was dropped. Backup SHA-256:
`0E71ABD58784B1683510F0D12FA86DD169323BD272FC0B534D62D3A56E270867`.
After deployment, all ten live table-content fingerprints again matched the
verified backup.

A separate session verified Idreesi login, the live PostgreSQL register, counts,
an existing case lookup, the awaiting-decision filter, mobile cards and no
horizontal overflow at 390 pixels. Readiness confirmed the trained ML engine
remained serving. No browser exceptions occurred. The only write requests in
this live check were login and logout; no case, monitoring, decision or policy
was changed. Authentication audit/revocation records can change following that
login, after the full-content comparison. The test session was signed out without
changing other sessions; credentials and tokens were not saved to evidence files.
The temporary preview was stopped, and the deployed app remains running.
