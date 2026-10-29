# Workspace usability update — 24 October 2026

ForiFlow now groups tools around the officer's workday and makes common tasks
available directly from the dashboard. This is a frontend update; scoring,
policy rules, permissions, models and the database schema are unchanged.

## What changed

- A clearer dashboard introduces the available next steps, with direct links
  to assessments, case lookup, monitoring and reminder preparation. Portfolio
  figures continue to come from the existing API. Compact mobile tiles put
  the action list within easier reach.
- Navigation is grouped into Your workday, Lending, Monitoring and Governance.
  The current page and document title identify the workspace. Desktop navigation
  stays available while scrolling, with its own scrolling on shorter screens.
- **Find a workspace**, also available with Ctrl/Cmd+K, searches page names,
  descriptions and synonyms locally. It explicitly points case searches to
  Applications. It does not search or store borrower information.
- Native modal dialogs support keyboard focus containment, Escape, focus
  restoration, background scroll locking and mobile menu closure after resizing
  to desktop. A skip link, visible focus indicators, larger controls and reduced
  motion support improve keyboard and mobile use.
- Sign-in has a clearer layout, password visibility toggle, Caps Lock message,
  expired-session explanation and account-access guidance. Authentication keeps
  the requested page's path, query and anchor. Existing session and lockout rules
  are retained; no account or credential is changed.
- The assessment form has three section shortcuts, a count of filled required
  fields, explicit optional labels and linked validation errors. A filled field
  is not presented as validated. Invalid submissions focus the error summary;
  its links focus the affected field.
- Loading a sample or clearing populated entries requires an explicit choice.
  Sample profiles explain that scoring creates a saved assessment. Previously
  saved results remain labelled as the last saved assessment when inputs change.
  No persistent browser drafts or automatic submissions were introduced.
- Connection errors give practical guidance without showing server addresses or
  terminal commands. A failed save asks the user to check the record before
  trying again.

## Verification

The existing **49 frontend tests pass**, and the production build succeeds.
The main entry is 262.15 kB (88.01 kB gzip); workspaces remain lazily loaded.

Browser verification uses private synthetic fixtures and covers 11 usability
scenarios: dashboard access, search and empty state, keyboard navigation,
mobile focus containment and resize, form progress and error links, guarded
replacement/clearing, validation, responsive layouts and password visibility,
plus preserving a requested route through sign-in. Screenshots were inspected
at desktop and mobile sizes; viewport checks include 320, 390, 768 and 1024 pixels.

Existing regression checks also pass: **19 monitoring**, **12 Action Desk**,
and **7 scoring/statement/explanation/memo** checks. Monitoring writes and
scoring submissions were intercepted against synthetic fixtures. No borrower
data was written during these tests. Browser exceptions were absent.

Private evidence is in `archive/user-experience-2026-10-24/`.

## Local deployment and data preservation

Only the frontend container was rebuilt and replaced. Frontend, backend and
PostgreSQL report healthy. The deployed page serves `index-BISS06Yr.js` from
frontend image
`sha256:45dd74af9bcd7aa1aa8d85e01f54422560d1edee0be6dace0c7d700117cad009`.
The previous frontend is retained as
`foriflow-frontend:before-user-experience-20261024-194747`.

The fresh backup
`backups/foriflow-20261024-194719-e48783b9b04348c89541f7c00de249cb.dump`
was restored into a disposable database and verified against all ten live
tables, migration version and the audit append-only guard. The scratch database
was dropped. Backup SHA-256:
`E925DC575F93B99A42C94004CA8333150D7486D5370C4F170631D1E33611592B`.
All ten table-content fingerprints again matched after deployment.

A separate browser session then verified Idreesi login, workspace search,
assessment section focus, mobile navigation and focus restoration, and the live
monitoring calendar against stored facility tenure and observations. Readiness
confirmed the trained ML engine remained serving. There were no browser
exceptions. The only write requests were login and logout; no borrower,
monitoring, policy or decision was edited. Normal authentication audit and
revocation events follow this login, after the full-content comparison.
The verification session was signed out, with no credentials or tokens written
to evidence files. The temporary test preview was stopped; ForiFlow remains
running at `http://127.0.0.1:3000/`.
