# Reviewed credit-policy changes — 29 October 2026

The policy workspace now supports comparing immutable versions before creating
a draft or activating a replacement. A current-run review found immediate
activation, draft defaults that differed from the active policy, a horizontally
scrolling mobile table, and unsaved entries lost on navigation. No pilot policy
was changed during that review.

## Officer workflow

1. **Read and compare.** Responsive version cards expose the cut-offs, manager
   limit, override restriction, recorded assessment count and activation history.
   Every officer can open a fresh read-only comparison with the active policy.
   A hypothetical score illustrates the configured boundaries using the existing
   dial helper. It calls no model, assesses no borrower and does not establish
   valid lending thresholds or expected default rates.
2. **Prepare a draft.** New entries start from active terms, with a blank new
   version, name and description. Invalid or nonfinite figures cannot enter
   review. The review refreshes versions and the officer account, checks duplicate
   identities and displays the exact proposed terms. Saving creates an inactive,
   immutable draft. Reset and navigation respect the existing unsaved-work
   protection; no draft survives a browser crash or is secretly stored locally.
3. **Review activation.** The admin sees current and selected terms, supplies a
   3–300 character reason, then confirms it in a separate step. Saved assessments
   keep their original policy and authority snapshots. Failed, malformed or
   conflicting reads withhold the action; failed saves require a fresh comparison
   and inspection before another attempt. Requests are not retried automatically.

## Server contract

The updated UI sends `POST /policy/versions/{id}/activate` with
`expected_active_id` and `reason`. The active ID is required in that body and
may explicitly be null only when no policy is active. Wrong types, extra fields
and blank/overlong reasons are rejected. A different current active ID returns
409 before changing policy or recording an activation.

Activation uses the same transaction lock as account role/status changes. The
actor's enabled-admin authority is refreshed after acquiring it and before
locking the target policy. Simultaneous activations of different targets are
therefore serialised; the second reviewed request encounters the changed active
version. Retirement, activation and their audit entries commit together. The
reason is included on both transition events; no schema migration is required.

For compatibility, clients that omit the **entire body** retain their earlier
activation contract. Those calls receive the fresh authority/transaction lock
but do not supply the new stale-review expectation or reason. The new UI always
uses the reviewed body. This is not a claim that every legacy API client now
performs a review.

## Verification and limits

- Native policy/account regressions: 119 passed, one PostgreSQL-dependent case
  skipped. Includes stale expectations, strict body validation, stale cached
  authority, audit-failure rollback and the existing decision/snapshot contracts.
- Frontend: 108 tests passed and the production build passed.
- Browser checks use a separate loopback server, a fictional officer and an empty
  case database. They cover draft preservation, save failures, stale activation,
  malformed/failed reads, fresh non-admin restrictions, keyboard return and
  320-pixel layouts. Actual overlapping PostgreSQL transactions have a dedicated
  test using CI's guarded disposable account-test database.
- Local screenshots, request records, backup and deployment checks are retained
  under ignored `archive/policy-review-2026-10-29/`. They are not part of a fresh
  public checkout. Full accessibility certification is not claimed.

The serving credit model and pilot policy values are unchanged by this feature.
No real loan, account authority or policy activation is used as a browser test.
