# Source and permission evidence register

Open a saved case's review panel and choose **Source & permission evidence**.
The register attaches references to a specific assessment without changing its
financial inputs, score, recommendation, policy or officer decision.

## What is recorded

Any enabled officer can record a source type, document/declaration reference,
capture date, optional coverage period, linked financial fields and a short
review note. The server snapshots those fields from the saved assessment;
clients cannot supply replacement financial values through this API.

Permission evidence is explicitly missing, a referenced consent record, or a
referenced lender-authority record. Documented evidence needs its own reference
and date. Expiry is inclusive through the recorded Pakistan calendar date. No
expiry means unknown terms, not indefinite permission. Future capture or
permission dates are refused. Capture or permission dates later than the
assessment are flagged instead of rewriting its historical context.

Credit assessment, loan monitoring and model research/training are separate
purposes. Research is not selected by default or inferred from credit use.
Selecting research records an officer assertion about a reference; it does not
authorise training or establish source authenticity, subject identity, legal
authority, signature validity or the actual terms of a document.

The register is attached **after assessment**. It does not establish consent at
the original collection/scoring time, gate existing intake, fetch documents,
connect to providers, grant access or retroactively legitimise processing. A
real lender integration must enforce permitted use before collection and use.

## Corrections, withdrawal and integrity

Managers/admins can correct a record or record a withdrawal with a reason.
Each operation appends a revision. Earlier records are protected from update,
delete and (on PostgreSQL) truncate through database triggers. The database
owner can still remove guards; independent retention and audit controls remain
necessary for a lender deployment.

A source reference is unique within a case after Unicode/whitespace and case
normalisation. Its earlier revisions reserve that reference too. Open the
existing source for corrections instead of creating another stream to hide its
withdrawal. This detects reference duplication, not document identity fraud.
Correcting a withdrawn source with documented permission requires new evidence
dated on or after the recorded withdrawal. This does not verify renewed consent.

Writes recheck the actor inside the shared role-change lock and lock the case.
Stale revisions are refused. UUID save-intent keys recover unchanged retries
without duplicate records/audit events and reject reuse with different content.
Current-source counts exclude superseded revisions; history remains paged and
readable. Limits are 50 sources and 500 total events per case.

Withdrawal is a recorded restriction now, not automatic erasure, provider-side
revocation or a historical reconstruction of when a person actually withdrew.
Retention, outstanding obligations and further processing require the lender's
approved process. No automated source-use enforcement is claimed by this screen.

## Interpretation

Field coverage counts references, not data quality, consent completeness or
model confidence. There is no percentage-based readiness score. Every report
explicitly returns `training_authorised: false` and `data_access_granted: false`.
The research training-authorisation process is outside this register.

Source history evaluates expiry as of today; it does not label an old revision
as the permission status known at its creation time. The immutable event kind,
dates, actor, note and snapshot describe what was actually recorded.

Migration `0013_case_data_records` adds an empty table and one migration audit
entry. It does not backfill references or permissions for existing cases.
Backup verification includes its full contents and append-only guards.
