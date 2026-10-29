# Workday navigation and relevant next actions

28 October 2026, Pakistan time.

An interaction audit of the running application confirmed a practical problem:
an officer could filter the worklist, open a case, then return to a reset list.
The dashboard's task preview also used the complete worklist rather than the
current officer's role. This update connects those existing screens without
adding new routes or changing credit decisions.

## What changed

Action Desk stores the applied task type, priority, role scope, search and page
in its URL, following the existing application-register pattern. Refresh,
browser Back and Forward, and case return preserve that view. A filter change
starts at page one; an out-of-range page is replaced by the last valid page.
Only bounded, known controls reach the request. Applied search is part of the
address; no task records or credentials are saved in navigation state.

Opening a review, alert or monitoring task carries a **Back to worklist** link.
Its destination is always the local Action Desk, reconstructed from validated
controls. Selecting another case in the report or another facility in monitoring
retains the return context. Direct case links without that context keep their
existing behavior. Existing unsaved-work protection still intercepts the return
link; no note, observation, decision or alert action is automatically submitted.

Dashboard **Next actions** starts with **Your role**, offers **All roles** and
retains complete-portfolio totals. Each task names its required authority.
**Open next task** follows the existing workflow priority and carries the same
return context. A failed or superseded request hides its old task actions;
refresh and retry are available. Role eligibility is distinct from assignment,
and case-specific approval limits still apply.

Dashboard copy now says **Recorded approved facilities** instead of implying
model approval, and **No open alerts recorded** instead of certifying stability.
The model, database schema, API permissions and credit policy are unchanged.

## Verification

- All 67 frontend unit checks passed. New cases cover view round-tripping,
  escaped search text, bounded query values, invalid pages, filter/page behavior
  and a fixed local return destination. The production build passed.
- Nineteen browser scenarios were verified through the in-app browser. They
  include refresh, browser Back, explicit return and case refresh, preservation
  of an unsaved note after Stay here, an analyst preview, second-page navigation,
  filtering from page two, empty results, errors/retry, an observed delayed scope
  change, mobile keyboard controls and reflow at 390px, monitoring case/month
  navigation and the deployed dashboard/case round trip.
- Read-only checks used the live local app and a preview against its existing
  backend. Pagination, analyst scope and failure/delay checks used a separate
  loopback fixture server backed by isolated synthetic API responses. No live
  users, roles or borrower records were created for those tests. The fixture
  server recorded no unexpected writes or missing API fixtures.
- Accepted screenshots and the step-by-step local audit are retained under
  `archive/workday-navigation-2026-10-28/`. Screenshot and keyboard checks do
  not constitute a complete accessibility audit or WCAG certification.

Only the frontend was rebuilt and deployed. All three main services are healthy;
production readiness reports the ML engine serving. Before/after content
fingerprints match across all ten database tables. Backend and database image
identities are unchanged. No model training or claimed accuracy improvement is
part of this navigation update. The backend regression suite was not rerun for
this frontend-only change.

## Backup and rollback

The validated pre-deployment database archive is
`backups/foriflow-20261028-004043-95a172b731404d6f9cd80700ba589918.dump`
(53,593 bytes), SHA-256
`ba9aec883829669e8dc29dab094dad3df52af5dc0eda22ce1cfe34e8482ac4d8`.
`pg_restore --list` verified archive readability; a new scratch restore is not
claimed. Earlier failed preservation attempts left their valid database dumps
in the private backup folder; no live database restore was performed.

Docker's image store no longer resolved the previous frontend image reference
after rebuilding its mutable tag. An original-image tag and container commit
therefore failed before deployment. The working frontend's complete static
files and three nginx configuration files were copied from its running
container. A rollback runtime was reconstructed using the same pinned official
nginx base; hashes of all 35 serving/configuration files match the running
original. This is a verified reconstruction, not an identical original image.

Rollback tags are `foriflow-frontend:before-workday-navigation-20261028-004043`
and `foriflow-backend:before-workday-navigation-20261028-004043`. The latter
preserves the unchanged original backend image. Preservation/deployment logs,
row fingerprints and the rollback files remain in the private local archive.
