# Unsaved model-input inspection

27 October 2026. Follow-up to the trained input-anomaly model and saved-case
[ML diagnostics](ml-diagnostics-2026-10-27.md).

## What an officer can now do

On **Credit Scoring**, enter loan amount, monthly digital payments, cash-flow
proxy, repayment-history score and years trading, then select **Check inputs
without saving**. Names and borrower identifiers can remain empty. The panel
shows the existing trained anomaly model's empirical percentile, credit-input
clipping and the actual repayment-history encoding. It creates no credit
score, recommendation, borrower, assessment, decision or audit record.

This is useful even when every saved case belongs to an older model version:
the check describes the current unsaved figures and current serving model.
The eight historical assessments keep their original model provenance and
saved-case diagnostics remain withheld where that source cannot be verified.
No historical case has been relinked or rescored.

The existing **Score application** action still validates the full intake,
stores its assessment and keeps the model link. Input checking is optional
and is not a new approval requirement. Anomaly typicality does not verify
financial evidence or establish creditworthiness.

## Backend contract

Authenticated `POST /model/input-checks` accepts exactly five finite numeric
fields. Missing fields, unknown fields, booleans, numeric strings, NaN,
Infinity and figures outside the intake limits are rejected. The request
contains no applicant identity, phone, borrower reference, statement or
policy. The response echoes the numerical inputs so the frontend can verify
which figures were checked and sets `Cache-Control: no-store`.

The endpoint supports the serving three-feature trained model. It uses the
canonical turnover source, zero-flow sentinel, credit clipping and history
encoding. The input descriptions are shared with saved-case diagnostics;
tests compare draft outputs against the full trained credit feature path.
No surrogate or different feature contract is presented as the supported ML
model. If the optional anomaly reference is missing, verified numerical
transformations remain available with explicit partial status.

The route calls neither credit scoring nor model registration, policy
evaluation or persistence. Tests forbid those calls and assert that all
database statements issued by the request are SELECTs. Repeated requests
leave every table unchanged. POST carries the numerical request body; it
does not mean the operation creates a record.

The existing 128-tree anomaly model, its training data, threshold and credit
artefacts are unchanged. The credit model's public consumer-data held-out
AUROC remains 0.7748; no new accuracy or Pakistani SME validation claim is
made. The credit fingerprint remains
`15a24f14f148b513bddf75c5eafb55f873af8d57f42988970fc51247686ff43d`.

## Freshness, privacy and usability

- Only the five numerical fields leave the form. Identity, documents and
  unused scoring fields are excluded; they remain in the officer's form.
- Each relevant numeric edit immediately hides the previous result. Restoring
  an earlier number still requires a fresh explicit check. Pure formatting
  changes with identical numerical meaning do not invalidate a result.
- An abort controller, request sequence and numeric-response comparison block
  stale and mismatched results. Repeated clicks start one request at a time.
- Cancellation, sample replacement, form clearing and statement-derived cash
  changes cannot be overwritten by an older response. Statement reading and
  submission pause the check; there is no automatic inference per keystroke.
- Errors preserve entered figures and identity fields. Missing/invalid figure
  guidance links directly to the relevant inputs.
- Repayment history is explained at its exact boundary: at or below 52.5
  adverse; above 52.5 clean. Zero cash remains zero; the substitute ratio of
  999 is explicitly labelled a sentinel rather than an observed ratio.
- The form contains its input table on mobile, including expanded reference
  fingerprints. A grid-width correction prevents a wide child table from
  expanding the page beyond a 390-pixel viewport.

## Invalid-value rejection fix

Testing found a pre-existing response problem: when Pydantic rejected a
non-finite number, the validation handler tried to echo the same non-finite
float in strict JSON and failed. Error payloads now render non-finite values
as strings, recursively, after the existing password/identifier redaction.
Input validation still rejects them. Both the new route and the existing
assessment endpoint are covered; valid scoring behaviour is unchanged.

## Verification

- Native backend: **377 passed**, including 39 new input-check/validation tests
  and the existing model, register, score, decision, policy, authentication,
  Action Desk and monitoring checks.
- Production Linux image: **375 passed, 2 skipped**. The serving image excludes
  the raw CSV, so two existing file-dependent training checks skip; those
  checks passed natively with the CSV present.
- Frontend: **62 passed**, including nine numerical privacy, validation,
  freshness-reference and response-verification checks; production build passed.
- New synthetic browser flow: **15 passed**, using responses from the actual
  trained model in an isolated in-memory database. Coverage includes all five
  edits, no identity submission, cancellation, stale responses, errors,
  statement updates, sample replacement, partial/unavailable models, clipping,
  exact fractional history boundaries and mobile layout.
- Existing browser regressions: **137 passed** across assessment, Action Desk,
  monitoring, register, navigation, unsaved work, Pakistan dates, decision
  confirmation and saved-case diagnostics. The unchanged model page's mobile
  width assertion waits for responsive charts to finish resizing.
- Live account: **10 checks passed**. Three real input-analysis POSTs contained
  exactly the five numeric fields, with no identity or document values. Normal,
  changed-loan and zero-flow results matched the live responses. Temporary
  figures were cleared afterward; no assessment was scored or saved.
- **All ten live database tables had identical content fingerprints before and
  after the input-check flow**, measured after sign-in and before sign-out in
  read-only database transactions. Only normal authentication actions created
  their expected audit/token records outside that comparison window.

Synthetic screenshots hide the sticky header only during element capture;
they contain no real customer records. Evidence and reproducible verification
scripts are under `archive/input-checks-2026-10-27/`.

## Backup and release

The pre-update backup was restored only into a new scratch database. All ten
table fingerprints, migration revision and the audit deletion guard matched;
the scratch database was dropped afterward.

- Backup: `backups/foriflow-20261027-013531-d1fb879bbfc846749eef97e6b6826ace.dump`
- Bytes: 53,206
- SHA-256: `606EBBAEA169729F81FFB07A676C9226FA693E7B557438B9F563A077A7F73D65`
- Backend rollback tag: `foriflow-backend:before-input-checks-20261027-013911`
- Frontend rollback tag: `foriflow-frontend:before-input-checks-20261027-013911`

Deployment, database-content and live-browser evidence are retained in the
same evidence folder. The database container and volume are retained.

After deployment, all ten table contents matched the verified backup before
live sign-in. Backend, frontend and database health checks passed. Deployed
images:

| Service | Image SHA-256 |
| --- | --- |
| Backend | `83a08ff3589b93312e1592cd7c9dab961370e882c561f1bf14286e61a6053181` |
| Frontend | `2a5e1747bb654bd339dde4b6dc10755ce4aaad27fceae35469361e4bb178d580` |
| Database, retained | `557fea37a744d5f4c8faab304b0a90858b53ab119735a88c131fd19dab802f36` |

The live dashboard serves `index-Da4TG_gN.js`. Verification credentials and
tokens were passed only in memory, not written to the evidence folder.
