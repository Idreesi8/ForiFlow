# Officer Action Desk — 24 October 2026

ForiFlow now brings pending credit reviews, open EWS follow-ups and incomplete
monitoring records into one officer worklist. The dashboard shows the first
three tasks; **Action Desk** in the sidebar opens the complete, searchable list.

## Behavior

The authenticated `GET /portfolio/action-desk` endpoint reads the complete
portfolio using three SELECT queries. Search and pagination do not silently
restrict coverage to the application's first 200 rows. Totals distinguish
tasks from distinct application cases because one facility can need more than
one kind of work. Counts describe the complete portfolio, while the list shows
the matching page.

The published order is overdue open alert actions, other critical alerts,
other open alerts, escalated assessments, pending assessments, monitoring gaps,
unknown recorded payment amounts, then approved facilities without monitoring
records. Within each group, the oldest recorded date and stable case reference
break ties. This is workflow ordering, not a new credit score or prediction.
Deadline comparisons and displayed snapshot times use Asia/Karachi.

Every task states the recorded reason and supporting evidence. Completed or
superseded assessments produce no review task; closed alerts produce no alert
task. Monitoring uses active observations only. A later recorded month cannot
hide an earlier gap, and an unknown payment amount remains unknown. The desk
does not infer delinquency from missing records, generate payment demands or
change any decision, alert or observation.

Opening a monitoring task selects the right facility and, when appropriate,
the first missing month. A focused facility is fetched separately if it falls
outside the monitoring selector's first 200 rows. Alert tasks open a focused
follow-up view; review tasks open the existing assessment. Existing server-side
decision and correction permissions still apply.

Officers can filter by task type or priority, search by business/case/owner,
refresh the snapshot and copy the current page's briefing. The copied text
states its page coverage. Loading failures hide stale tasks and disable copying;
cancelled earlier requests cannot replace a more recent filter result.

## Verification

- 24 new backend cases cover priority ordering, Pakistan midnight boundaries,
  authenticated access and officer roles, closed/superseded rows, active-only
  corrections, unknown amounts, onboarding without invented deadlines,
  pagination/search beyond 200 rows and exactly three read-only queries.
- The Windows regression selection completed on 22 October: **165 passed**,
  including authentication, EWS, statements, reminders and portfolio checks.
  One existing Starlette test-client deprecation warning remains.
- The same **165 checks passed in the newly built Linux image** on 24 October
  in 58.88 seconds. That disposable container had no network access, no live
  database credentials or database volume, and only synthetic statement samples
  mounted read only. Two existing library deprecation warnings remain.
- **31 frontend unit tests passed**, including safe case links, missing-month
  navigation, Pakistan snapshot dates and page-specific briefings.
- The production frontend build passed. Its main entry is 254.46 kB
  (85.85 kB gzip); Action Desk is a separately loaded page.
- Chrome checks resumed on 24 October and passed priority order, evidence,
  pagination, filters, copying, desktop/390px layouts, server-error recovery,
  late-response cancellation, empty search, focused monitoring outside the
  first 200 facilities, missing-month prefill and the dashboard preview.
  These checks used 110 real API responses generated from isolated synthetic
  data; no browser exceptions, missing fixture requests or write requests
  occurred. The fixture snapshot itself was generated on 22 October.

Private logs, synthetic screenshots and browser evidence are retained in
`archive/action-desk-2026-10-22/`. No borrower data or credentials are included
in the synthetic browser fixture. Serving models and credit policy thresholds
were not changed or retrained. The worklist scans relevant portfolio rows in
memory; larger deployments should measure this read path before scaling it.

## Docker recovery and safety backup

On 24 October the same inaccessible `dockerInference` runtime socket failure
returned before deployment. The installed per-user Docker Desktop 4.86.0
reported Windows error 1920. The guarded
[`scripts/repair-docker-runtime.ps1`](../scripts/repair-docker-runtime.ps1)
confirmed stopped Docker, a recent matching error and only zero-byte socket
entries, previewed the exact target directories with `-WhatIf`, then preserved
and recreated those two runtime directories. The recovery manifest is retained
under `archive/docker-runtime-recovery/20261024-172032-99cff02c/`.
Docker's 29.7.2 engine then started with the existing containers and volumes.
The script's refusal while Docker is running was also verified. This remains
a targeted workaround, not a permanent fix to Docker Desktop.

Before the Action Desk deployment, a new backup was created:
`backups/foriflow-20261024-172254-000c87beb10b4233972bad61d3676692.dump`
(52,049 bytes). Actual PostgreSQL verification restored it into a new scratch
database, matched every row-content fingerprint in all ten tables and the
migration, checked the audit deletion guard, then removed only the scratch
database: **PASS**. The live database was not restored.

Original images were preserved as
`foriflow-backend:before-action-desk-20261024-172507` and
`foriflow-frontend:before-action-desk-20261024-172507`.

## Deployed application

The tested backend and frontend images were started with Compose's health wait;
the database service and volume were retained. All three main containers are
running and healthy. Readiness through the dashboard proxy reports production
configuration, a reachable PostgreSQL database and the trained ML engine serving.

Before the live sign-in verification, **all ten tables' complete content
fingerprints and counts matched the fresh verified backup**, including users,
borrowers, applications, policies, model versions, EWS history, alerts and
security/audit tables. No live database restore or schema change was needed.

A separate Chrome session then signed in successfully as the existing `Idreesi`
account, opened the dashboard preview and Action Desk against live PostgreSQL,
matched the rendered task count, checked the Pakistan timezone and 390px layout,
confirmed ML readiness, and signed out that verification session. The snapshot
contained five tasks across four cases. It served `index-BMrEbNqM.js`, matching
the new production build, with no browser exceptions. The only write requests
were the normal sign-in/sign-out requests; their audit and token-revocation
events are expected changes after the full-table preservation check. No borrower,
credit decision or monitoring record was changed by this verification.

The running page is <http://127.0.0.1:3000/action-desk>. Evidence includes
`linux-regressions.log`, `deployment.log`, `live-readiness.json`,
`live-containers.txt`, `post-refresh-content.json`, `content-verification.log`
and `live-browser-checks.json` in the private Action Desk evidence directory.
Docker and ForiFlow are left running for use.
