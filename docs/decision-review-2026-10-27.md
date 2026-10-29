# Reviewing a credit action before recording it — 27 October 2026

Previously, clicking Approve, Reject or Escalate after typing a reason immediately
submitted the action. A final credit decision is immutable, so an officer needs
an opportunity to check the specific case, amount and reason before that write.

## Behavior

- The initial action opens a review dialog without recording a decision. It
  rereads the selected case and the signed-in account through authenticated GET
  requests. Confirmation stays disabled until both reads succeed. The dialog
  shows the business/applicant, case and borrower references, requested amount
  with paisa, term, current status, recorded policy/recommendation, current officer
  and intended action. The trimmed reason shown is the exact reason submitted.
- A final approval/rejection is clearly distinguished from an escalation. A
  decision against an explicit Approve/Decline recommendation is highlighted.
  Manager limits, escalated-case authority and account-role restrictions follow
  the current server-reported facts. The backend still enforces all authority
  and immutable-decision rules when the officer explicitly confirms.
- A closed, superseded or newly escalated case, reduced authority, failed account
  lookup, mismatched case identity or unavailable approval authority blocks the
  relevant confirmation. Refreshed case facts update the underlying review panel.
  The typed reason stays available even if the case closed or the role changed.
- Escape and **Back to reason** cancel without a decision request and retain the
  reason and focus. Enter on the initially focused heading does not submit an
  action. Cancelled preview reads are aborted and their late replies ignored.
  **Refresh details** rereads the preview without writing.
- Confirmation uses an immediate in-flight latch, protecting against two click
  events before React rerenders. While recording, close/confirmation controls
  and Escape cannot dismiss the pending save. The existing lost-response and
  conflict recovery rereads the case, retains the typed reason and does not
  retry a decision POST automatically.
- The dialog keeps controls visible on mobile, scrolls the case/reason content
  and contains keyboard focus. Existing unsaved-work protection also covers
  browser Back while the confirmation is open.

The dialog is a point-in-time check, not a reservation or case lock. Another
officer can act after the preview; the existing server transaction resolves that
race and returns a conflict where appropriate. The preview does not add a server
draft or persistent browser draft. The reason remains tab-local until confirmed.

## Reading supporting evidence

SHAP reports and credit memos now use the backend's existing **GET /explain/{id}**
read endpoint rather than its generation POST. Opening these pages therefore
does not store/regenerate an explanation record or create a generation audit
entry. The existing GET can calculate a response when stored evidence is missing;
this change does not add new scoring or explanation algorithms.

Both views abort obsolete requests, reject evidence belonging to another case
and ignore late replies. A newly selected case does not display the previous
case's explanation or memo while loading. These are frontend-only changes: the
API, database schema, model artifacts, policy and authority rules are unchanged.

## Verification

The **53 frontend tests pass** and the production build succeeds. New browser
checks use real API responses captured in isolated memory with synthetic
applicants, decisions, account roles and supersession. Every synthetic decision
request is intercepted and its exact body checked; none reaches the live service.
They cover approval/rejection/escalation, both officer roles, recommendation
overrides, read failures, stale status/authority, cancellations, duplicate clicks,
lost responses/conflicts, mobile focus/scroll and mismatched or delayed evidence.

The previous work-protection tests are adapted to explicitly confirm the action.
The full-register test now expects no explanation POST, and waits for the reset
response before injecting its refresh error, avoiding consumption by an earlier
request. Test scripts and private evidence are in
`archive/decision-confirmation-2026-10-27/`.

The completed browser run passes **30 new scenarios** and **89 existing
regressions**: 7 scoring/statement/memo, 12 Action Desk, 19 monitoring, 11 complete
register, 11 interface, 18 work protection and 11 Pakistan-time checks. No browser
exceptions or missing fixture routes occurred. Desktop and mobile review and
reason-scroll screenshots were visually inspected. Backend source was unchanged;
its test suite was not rerun for this frontend-only update.

## Backup

Before deployment, a fresh backup was verified through an actual restore into a
disposable database. All ten table-content fingerprints and the migration version
matched; the audit append-only guard was enforced and the scratch database dropped.

Backup: `backups/foriflow-20261027-001048-24cb7c737ed14d8487fd8d5d7bd4dc66.dump`.
SHA-256: `A920C21AF06B1DD7533E0B1C797B7CC9A0EE25FA2ABD15F062C7B147C5459A85`.
The previous frontend image is retained as
`foriflow-frontend:before-decision-review-20261027-001821`.

## Deployment and live verification

Only the frontend container was replaced. It serves `index-3AR9Pm-t.js` from
image `sha256:016e61fd62a092306ad6b308dec725931b9035d2cf4ef1b3e8971cbdec17fc4d`.
Backend and database image identities remained unchanged and all three services
are healthy. All ten live table-content fingerprints matched the verified backup
after deployment, before the final authentication checks.

A separate browser session verified Idreesi login and opened a real pending
case's approval preview. It checked the fresh officer identity, displayed reason
and mobile controls, then cancelled. The temporary reason remained available,
received focus and was cleared without saving. The complete case-response
fingerprint matched before and after the cancelled preview. The report and memo
both read their explanations with GET. The trained ML engine remained ready.

There were no browser exceptions. The only non-GET API requests were normal
login and logout; no real credit decision or monitoring entry was submitted.
Authentication audit/revocation records may change normally after those checks,
following the complete table-content comparison. The verification session was
signed out, and credentials/tokens were not written to evidence files. The
temporary preview process was verified by executable/command line and stopped.
The live application remains running.
