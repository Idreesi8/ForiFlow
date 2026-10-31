# Review an assessment before saving

28 October 2026, Pakistan time.

The later [save recovery update](assessment-save-recovery-2026-10-31.md) adds
server idempotency and replaces the network-loss behavior described below.

The intake form previously saved and scored immediately after validation. It now
offers **Review assessment**, followed by an unsaved, read-only summary of every
field in the submitted payload. **Save and score assessment** is a separate,
explicit action. A credit decision still requires the existing officer workflow.

The review shows full PKR figures, including fractional rupees, rather than
compact lakh/crore values. Omitted optional fields say “Not recorded.” Each Edit
link restores the form and focuses that field. Editing or replacing the form or
statement requires another review. The confirmation checks the complete field
and CSV reference, revalidates, and submits the reviewed payload. Enter on the
review heading cannot confirm a save. A synchronous request guard and disabled
controls prevent duplicate clicks during that request.

Turnover evidence identifies manual figures, a statement whose suggested
turnover matches, or edited turnover. Attached statement dates, coverage and
warnings remain visible; matching does not assert verified income or source
authenticity. The comparison follows the backend's existing digital receipts
and cash-flow equality checks. The API independently rereads the CSV when saved.
The optional model-input check remains separate and is not an approval gate.

Frontend validation now checks finite numbers, listed select options and the
API's CNIC/NTN digit counts (13 for CNIC, 7 or 8 for NTN). The backend continues
to enforce identity rules and permissions. Existing unsaved-work navigation and
decision-note protection remain active. A failed request keeps the review and
entries. A successful request restores editing and focuses the saved result.
Network loss remains an ambiguous save: the existing error asks officers to
check the register before trying again. This update does not introduce server
idempotency or recover drafts after a browser crash.

## Verification

All 75 frontend unit checks passed, including eight new validation, payload,
reference, evidence and precision cases. The production frontend and Docker
image builds passed. The browser checks use the in-app browser and isolated
synthetic responses for save failures, statement summaries and saved results;
they do not validate a new model or replace backend credit tests.

Sixteen browser checks passed: validation/focus, exact amounts, edit navigation,
identifier correction, unsaved navigation protection, 390px reflow, keyboard
evidence editing, matched and edited statements, in-flight controls, one request
after a double click, retained failed-save entries, explicit retry success,
evidence removal, and the deployed review against the live service. The fixture
recorded exactly two score requests (one deliberate failure, one explicit retry)
and no unexpected writes or missing responses. These are UI scenarios, not a
complete accessibility audit. The live sample remained unsaved and was cleared.

Browser checks, accepted screenshots, synthetic request logs and deployment
snapshots are retained in `archive/assessment-review-2026-10-28/`. Capture helpers
were updated to follow both steps but were not run against the live database.
The backend test suite was not rerun for this frontend change.

## Local runtime

Docker was initially stopped and repeated the known inaccessible
`dockerInference` runtime-socket error. The existing guarded repair verified that
condition and preserved the stale runtime folders under unique sibling names
before recreating empty runtime folders. It did not reset Docker or remove data
volumes. Evidence is under
`archive/docker-runtime-recovery/20261028-123651-a9387b83/`.

Before the frontend build, both serving images received rollback tags and a
custom-format database backup was validated with `pg_restore --list`. This is an
archive readability check, not a new scratch restore exercise. See the deployment
snapshots for exact paths, image identities and content fingerprints.

The frontend was deployed with backend and database images unchanged. All three
main services are healthy; readiness reports the ML engine serving. Before/after
fingerprints match for every row across all ten database tables. The temporary
fixture server was stopped. The model, its measured accuracy and credit policy
were not changed by this intake update.
