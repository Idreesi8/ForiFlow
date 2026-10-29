# Officer access management — 29 October 2026

Team & Roles now supports changing an existing officer's role, with a fresh
account check, an explicit review and an audit reason. The account list also
has username search, combined role/status filters, enabled-admin counts and
per-officer access history. Responsive cards replace the wide action table.

## User workflow

1. An enabled admin opens Team & Roles and finds the officer.
2. **Change role** reads the current account and admin authority from the API.
3. Select Analyst, Manager or Admin and enter a 3–300 character reason.
4. **Review change** shows the officer, current and proposed roles, permissions,
   account status and exact reason. **Edit change** returns to editing.
5. **Confirm access change** saves the change and audit entry together.

Role/status changes to one's own account are blocked. Ask another enabled
admin. Changing a disabled account's role leaves it disabled. No past loan
assessment, recommendation, decision or evidence is rewritten.

Disable/re-enable now uses the same accessible review dialog instead of a
browser prompt. The UI requires a reason for either action. A failed save keeps
the review and reason; **Refresh account and review again** reloads current
authority before another attempt. Unfinished new-account forms and access
changes participate in the workspace's unsaved-work protection. New accounts
still use the existing password policy; no password-reset feature was added.

## Permissions and session behaviour

Only an enabled admin can list/manage accounts or read account access history.
The API re-reads the role from the database on every authenticated request;
the role in the existing JWT cannot grant higher authority. A role change thus
affects the next request without requiring a new token. Already-running requests
outside the account-management flow are not retroactively cancelled.

The interface refreshes its account on route navigation, window focus, return
to a visible tab and each 60-second account check while visible. Menus are a
display hint; the API is authoritative. A same-tab event updates account displays
when a fresh role differs from the stored role. A temporary fetch failure does
not falsely grant authority; protected API requests still enforce current access.

Disabling refuses sign-in and subsequent requests from existing sessions.
Re-enabling restores access to the current role. It does not un-revoke signed-out
tokens; other unexpired, unrevoked tokens can work again. This preserves the
existing disable/re-enable contract; it is not an all-session token revocation.

## Transaction and stale-edit protection

`PATCH /auth/users/{id}/role` requires `role`, `expected_role` and a nonempty
reason. Unknown roles, extra fields, whitespace-only reasons and overlong reasons
are rejected. A changed expected role returns 409 instead of overwriting another
admin's edit. A matching request that makes no change adds no audit entry.

Role changes, status changes and account creation share a PostgreSQL
transaction-scoped advisory lock. SQLite uses its write reservation for local
tests/fallback. After acquiring the lock, the actor's enabled-admin authority is
re-read with fresh ORM values. This protects simultaneous cross-admin demotions
and disables: the losing request cannot continue using its earlier authority.
Explicit checks also forbid self changes and removal of the last enabled admin.
Status changes optionally accept `expected_is_active`; the new UI sends it to
detect stale edits while existing API clients remain compatible.

The actual transition and append-only audit record commit in one transaction.
Role events include the actor, target account, old/new role, time and reason.
An audit failure rolls back the account change. No schema migration is required.

## Access history

`GET /auth/users/{id}/access-history` returns the latest 50 account creation,
role, disable and enable events, newest first with an ID tie-breaker. It excludes
sign-in events, network addresses, request IDs and password hashes. Seeded or
older accounts may have no recorded creation event. The existing full audit
trail remains unchanged and can contain older events beyond this view.

## Verification

Evidence is recorded in `archive/team-access-2026-10-29/verification.md`.
The pilot account roles are not changed as part of testing. Fictional browser
fixtures use a separate empty SQLite database; overlapping transactions use a
dedicated disposable PostgreSQL database with no published ports. The live
database and serving model artefacts are fingerprinted before and after deployment.
