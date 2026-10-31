# Assessment save recovery

31 October 2026, Pakistan time.

If a score request committed but its response was lost, clicking Save again
could previously create another borrower and assessment. A reproducible test
created two cases from the same intended submission. The save now has a durable
receipt, committed atomically with its borrower, assessment and audit entries.

## Officer workflow

Reviewing the form creates a new UUID submission reference in that tab. Saving
and every explicit retry send the same reference and the exact reviewed figures
and CSV. After a timeout, server failure or unmatched receipt, the review says
the server may already have saved the case, locks editing and offers **Recover
assessment result** beside the message and **Retry same assessment** below.
The result is accepted only when its case identity, reviewed name, business,
amount, tenure, score and explanation have a usable matching shape.

Recovery returns the original saved case, or completes the original save if its
transaction rolled back. No automatic POST retries are introduced. A definite
validation rejection keeps **Back to editing** available. Once a save is
uncertain, a later rejection does not silently unlock its original inputs.

After success, **View saved assessment** focuses that result without posting.
Whitespace and equivalent numeric spelling do not turn it into a new save.
Changing figures requires another review; **Start new assessment** clears the
completed form and result. It does not delete the saved case. Decision reasons
retain their existing independent protection. Narrow-screen action buttons wrap
and the intake grid can shrink instead of forcing horizontal page overflow.

The reference and the reviewed form stay only in the current mounted page.
Navigation warns explicitly that leaving an uncertain save loses its retry
reference and does not cancel an already committed save. This is not draft
storage or recovery after a crash, reload, sign-out or session expiration. After
losing that reference, check the application register before submitting again.

## API contract

`POST /score` accepts optional `Idempotency-Key: <UUID>`:

- The unique identity is `(authenticated user id, canonical UUID)`. Existing
  authentication, disabled-account and role checks still apply on every retry.
- A SHA-256 digest covers versioned, parsed applicant inputs, the exact CSV text
  if present, and `include_explanation`. Normalized numeric/whitespace inputs
  match; changing inputs or the explanation flag returns HTTP 409.
- First success and matching replay both return HTTP 201 with
  `Idempotency-Replayed: false` or `true`. Replay returns the original response,
  including original policy and pending-decision snapshot. Fetch the application
  detail for its current officer decision; the UI already does this separately.
- A conflicting insert waits for the first database transaction. Commit exposes
  its complete receipt; rollback releases the reference for the retry to save.
  Replay does not score again, supersede another case, or add audit entries.
- Invalid UUIDs return HTTP 422 before writes. Omitting the header preserves the
  legacy contract: each successful POST creates a separate assessment.

Migration `0011_score_submissions` adds an owner-scoped receipt table and one
`migration.applied` audit entry. It leaves existing assessments and accounts
unchanged. Receipts contain the existing score-response snapshot and a payload
hash; raw statement CSV is not copied into this table. Receipt data must remain
with the assessment when backing up or migrating. The SQLite-to-PostgreSQL copy
script includes the table when present and still accepts older source schemas.
Deploy the backend migration and API before serving the new frontend. Downgrade
drops retry receipts, so retain a current backup before rolling back schema.

## Verification

Focused native checks passed: 41 scoring/receipt/schema tests and 28 PostgreSQL
concurrency, migration, security and copy tests (the two schema tests overlap).
Coverage includes same-key replay, changed-input conflicts, independent officers,
legacy requests, rollback, disabled accounts, changed decisions/models, rescoring,
and three genuinely overlapping PostgreSQL transaction outcomes. A nonempty
SQLite receipt survives copy and replays identically on PostgreSQL. The migration
preserves prior records and appends exactly its own audit entry. All 121 frontend
unit checks and the production build pass.

Browser verification uses a separate loopback preview, fictional officers and
fictional businesses. Lost and malformed responses are simulated after the real
test transaction commits; explicit retry returns the same assessment. Evidence,
request identities, counts, screenshots and deployment fingerprints are retained
privately under `archive/assessment-save-recovery-2026-10-31/`.

This improves save integrity and usability. It does not train a new model,
validate the existing demo model for Pakistani SME lending, or automate officer
decisions.
