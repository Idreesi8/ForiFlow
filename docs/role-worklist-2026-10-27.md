# Action Desk: tasks the current officer role can act on

The Action Desk now offers **Tasks my role can act on**. An analyst can focus
on recording missing monitoring months; managers also see credit reviews,
alert actions and recorded-month corrections; admins additionally see escalated
reviews. These categories follow the existing action permissions.

The filter is optional and starts off. It is role eligibility, not personal
assignment or approval of every possible action. A manager's facility approval
limit and all existing API permissions still apply when an action is attempted.
Nothing about a loan, decision, model, alert, user or monitoring record changes
when this list is read.

## API and interface

`GET /portfolio/action-desk` accepts `actionable_only=true`. The endpoint reads
the authenticated user's current database role; no role from the browser or
token determines eligibility. The response includes `officer_role`,
`actionable_only` and `actionable_tasks`. The last is a complete-portfolio count
for that role, before other filters. Existing portfolio totals and category
counts continue to describe all roles.

Role, search, task and priority filters combine before pagination. Changing
role scope resets the page. Clear filters restores all roles. The count and
copied briefing state which scope was used. Failed or superseded requests do
not expose a stale list as the current result; copying is disabled while the
requested view is unavailable. Empty results explain how to broaden the view.

## Verification

- 192 Windows backend workflow checks passed, including 33 Action Desk cases,
  authentication, security, credit review, portfolio and EWS behavior. The
  Action Desk checks cover all three roles, stale token claims, a role change
  without a new token, ignored browser role claims, permission enforcement,
  filtering before pagination beyond 200 cases, unchanged complete counts,
  invalid parameters and three SELECT-only builder queries. One existing
  Starlette test-client deprecation warning remains.
- 63 frontend unit checks passed; the isolated production build passed.
- 10 browser scenarios passed against actual API responses generated from
  isolated synthetic data for three roles and 11 query variants per role.
  They cover page reset, totals, copied scope, empty results, clear, cancellation,
  error/retry, combined filters, manager/admin paging and keyboard operation at
  390px. No browser exceptions, missing fixture requests or write requests occurred.
  Desktop and mobile screenshots were visually inspected.
- A broader 806-case Windows run stopped progressing and was interrupted. It
  is not reported as passed; the successful 192-case selection above is the
  completed workflow regression. No model training or evaluation change is
  part of this work.

Local verification evidence is under `archive/role-worklist-2026-10-27/`.
The database backup was validated with `pg_restore --list`; this verifies the
archive is readable and is not a claim of a new scratch-restore verification.
Serving images were tagged for rollback before rebuilding.

## Local deployment completed: 28 October 2026, PKT

The newly built Linux backend passed all 33 Action Desk checks in a disposable,
read-only container with no network, live database credentials or database
volume. Two existing library deprecation warnings remain. Both application
images were then deployed locally; backend, frontend and the retained database
are healthy. The serving dependency check reports no broken requirements.

Live HTTP checks through nginx verified readiness with the trained ML engine,
the frontend's role-filter bundle, current database roles, scope and total
counts, invalid-parameter rejection and unauthenticated rejection. Only the
existing active admin account was available for this live check; analyst and
manager behavior was verified with isolated synthetic accounts above. QA tokens
were created inside the container with a 60-second lifetime, never printed or
saved. No officer's role or password was changed and no new account was created.

Before/after row-content fingerprints match for all ten database tables. The
database image is unchanged and all four serving pickle-file hashes match the
previous image. No credit model was retrained or credit policy changed.

The pre-update backup is
`backups/foriflow-20261027-234233-a7cf9bacc9024b1eb3fe5600a285e2dc.dump`
(53,475 bytes), SHA-256
`3e2147e8b7784dd2d4f6a62ed784ffdc0356c234cccdfb4700e8d98ace92bd9e`.
Rollback image tags are `foriflow-backend:before-role-worklist-20261027-234233`
and `foriflow-frontend:before-role-worklist-20261027-234233`.

The serving frontend entry is `index-y0cPwIAh.js`, with
`ActionDeskPage-CHv2fwWv.js`. The read-only live results, data fingerprints,
model hashes, build logs and deployment records are retained alongside the
synthetic browser evidence in the local archive named above.
