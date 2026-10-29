# Alert follow-up integrity

The alert workflow had three reproducible gaps: assignments accepted disabled
accounts; an old form could overwrite newer ownership or close newly updated
evidence; changing or closing an inline form discarded its note without warning.

## Implemented behavior

- Every alert action opens a responsive draft dialog, including acknowledgement.
  Preparing a draft does not save anything. A separate review fetches the current
  alert, account and enabled officer directory before confirmation.
- Current ownership, deadline, score and recorded evidence appear beside the
  proposed action. If the alert changed since opening, the officer must explicitly
  acknowledge reviewing the latest state. Editing, retrying a read or refreshing a
  review preserves the draft.
- Cancellation and Escape require a discard choice. Existing unsaved-work guards
  cover navigation, sign-out and browser unload. Drafts exist only in the tab;
  they are not persistent saved drafts or crash recovery.
- A synchronous submission guard prevents duplicate saves. Any failed or
  unverified save blocks another attempt until a fresh review. Requests are not
  automatically retried, including an uncertain response after a committed save.
- `GET /ews/assignees` requires manager/admin access and returns only enabled
  officers' usernames and roles. Analysts may own follow-up; managers/admins
  remain the only roles permitted to change alert lifecycle.
- Every alert response includes `review_token`, a SHA-256 digest of the returned
  stored alert evidence and lifecycle. It excludes the display business name
  and derived flags, including the date-dependent overdue flag.
- Lifecycle requests optionally accept `expected_review_token`. The server
  reloads and locks the alert, then compares the token before changing it. A
  mismatch returns 409 without an alert change or success audit event. New
  monitoring evidence also invalidates the earlier token.
- The existing account-change transaction mutex now supports explicit allowed
  roles. Alert writes acquire it before the alert row lock, recheck enabled
  manager/admin authority and validate any newly selected assignee. Concurrent
  account disabling cannot slip between that check and commit. No permission
  is granted by the token or the directory.
- Reaching the queue's load limit displays a warning that filters and counts
  apply only to loaded alerts.

## Compatibility and limits

No schema migration, model change, rescoring or automatic credit decision is
introduced. Existing tokenless API clients remain compatible and do not receive
stale-review protection; clients should send the token returned by their review.
The administrative mutex serializes protected alert and account writes across
the portfolio. This favors correctness at the current scale; larger deployments
should measure contention before replacing it with more granular coordination.

The queue still has a bounded read limit and needs server-side paging/filtering
for larger portfolios. Full accessibility compliance, screen-reader behavior,
real bank integration and SME model validity are not established by these fixes.

## Verification

Isolated backend tests cover all six stale lifecycle steps, changed monitoring
evidence, fresh saves/replays, disabled assignees, minimal directory exposure,
stale in-session authority and malformed guards. Existing monitoring, policy and
team regressions are included. PostgreSQL tests exercise overlapping reviewed
assignments and account-disable transactions on an explicitly guarded disposable
database. Frontend tests cover payload boundaries, current authority, validation
and withholding success on unrelated/incomplete save responses.

Private browser evidence and deployment fingerprints stay under the ignored
`archive/alert-integrity-2026-10-29/` directory and are not published to GitHub.
