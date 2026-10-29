# Protecting work in progress — 26 October 2026

Assessment inputs, monitoring figures and typed decision reasons could be lost
when moving to another workspace. Monitoring already protected month/facility
switches, but sidebar links and browser Back did not use that check. Statement
reads could also finish out of order, overwrite a later selection, or repopulate
a cleared form. A failed replacement removed the previous valid statement.

## Behavior

- Assessment, monitoring and decision-reason editors register unsaved changes
  and operations in progress with one shared navigation guard. Sidebar links,
  workspace search, case links and browser Back/Forward between app routes use
  the same guard. It identifies the editor and offers **Stay here** or an
  explicit discard. Existing monitoring month/facility guards remain in place.
- Sign-out asks for the discard choice before revoking the session. Cancelling
  leaves both entries and the session intact. During an active save or statement
  read, the in-app discard action is disabled. Staying on the page lets the
  officer check the result or cancel the statement read.
- A saved assessment establishes a clean baseline. Editing its values or attached
  CSV makes the form unsaved again. Successful saves do not create a misleading
  leave warning. The CSV is compared separately from small field values, so it
  is not JSON-copied on every keystroke.
- The browser's native unload warning protects refresh and tab closure after
  user interaction. Entries remain in component memory only; no persistent
  browser draft, crash recovery or server draft was added. Choosing to leave,
  forcing the browser closed or a crash can still discard unsaved work. Other
  editors, such as policy and team forms, are outside this guard's current scope.
- A typed or pending inline decision reason prevents a new score or form clear
  from unmounting that review on the same page. This also covers an already-open
  clear confirmation. A shortcut returns focus to the reason.
- Statement reads expose progress and cancellation. Financial fields pause during
  a read, while selecting another file cancels the earlier read. Both local file
  reading and HTTP replies are checked against the current request. Clear,
  confirmed sample replacement, remove and unmount invalidate pending replies.
  An invalid replacement retains the earlier valid statement and figures.
- While scoring, the statement picker and removal action are disabled. While a
  decision is being saved, its reason cannot be edited underneath the submitted
  request.
- A lost decision response or HTTP 409 triggers a read of the current case,
  without automatically retrying the decision write. Errors remain visible even
  when the fetched case is now closed. The typed reason remains available for
  comparison and deliberate clearing. **Check current record** performs another
  read. If that read fails, the reason stays in memory and further decision
  controls stay unavailable until the case can be loaded.

The implementation uses the installed router's data-router navigation blocker.
Workspaces remain lazily loaded; shared JavaScript grows from 262.25 kB / 88.02 kB
gzip to 322.99 kB / 107.46 kB gzip to support the router and guard. No dependency
version, backend API, database schema, model, scoring calculation, approval
authority or credential changed.

## Verification

The **49 frontend tests pass** and the production build succeeds. **18 new browser
scenarios pass** against isolated real-API snapshots with synthetic data. They
cover menu/search/Back cancellation, an actual browser reload dismissed through
its native dialog, explicit discard, in-progress operations, clean saves,
sign-out timing, same-page review protection, mobile monitoring, delayed CSV
replies, slow file reads, cancellation, invalid replacement and four decision
recovery outcomes (accepted, conflict, lookup failure and still pending). Exact
score and decision POST bodies are checked. No browser exceptions occurred.

Existing browser regressions also pass: **7 scoring/statement/explanation/memo**,
**12 Action Desk**, **19 monitoring**, **11 complete-register** and **11 interface**
checks. Desktop and mobile guard screenshots were inspected. Synthetic writes
were intercepted by the browser; no live credit or monitoring decision was
performed during these tests.

Private fixtures, screenshots and test logs are retained in
`archive/work-protection-2026-10-26/`.

## Deployment and live verification

Only the frontend container was rebuilt and replaced. Backend and PostgreSQL
remained running, and all three services report healthy. The deployed page serves
`index-D6yWpGx0.js` from frontend image
`sha256:f21b71fe3d1324cf102fcaeb3ad50ae79e57b745feb3db85842e719d08b34c8b`.
The prior image is retained as
`foriflow-frontend:before-work-protection-20261026-003603`.

The fresh backup
`backups/foriflow-20261026-003448-e8d275737a064cc98e54eb002b79d558.dump`
was restored into a disposable database. All ten table contents and the migration
version matched, and the audit append-only guard was enforced. The scratch
database was dropped. Backup SHA-256:
`63B8473999FA1BF13691D0C414B6C1954346BF6A1531EDE9351E0FA74823FF93`.
All ten live table fingerprints again matched after deployment, before login
verification.

A separate browser session verified Idreesi login, retained temporary assessment
text after Stay, cancelled sign-out without a logout request, mobile navigation
protection, deliberate discard and the requested register opening. The temporary
text was never submitted as an assessment. There were no browser exceptions, and
the only write requests were normal login and logout. No credit or monitoring
decision, borrower, policy or model was changed. Readiness confirmed the trained
ML engine remained serving. Authentication audit/revocation events can change
after this login, following the full-content comparison. The verification session
was signed out; credentials and tokens were not written to evidence files. The
temporary preview was stopped, and ForiFlow remains running.
