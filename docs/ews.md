# Early Warning System (2.1)

The Early Warning System (EWS) watches approved facilities month by month and
tells an officer which ones need attention, why, and what to consider doing.

**What it is:** deterministic, rule- and trend-based monitoring of figures an
officer records each month. Every conclusion can be traced to the stored
figures that produced it.

**What it is not:** a model that predicts default. Nothing in the EWS was
trained, fitted or validated on SME loan outcomes. Its thresholds are
monitoring rules chosen for this project. It never approves, rejects, freezes,
restructures or classifies a facility, and it never changes a credit decision.
It recommends; the bank's own process decides.

Code: `backend/services/ews_engine.py` (pure rules), `backend/routers/ews.py`
(API), `backend/services/ews_service.py` (the monthly score). Thresholds are
served by `GET /ews/methodology`; the dashboard hard-codes none of them.

## The monthly observation

An officer records, for one approved facility and one reporting month (months
since disbursement):

| Field | Notes |
|---|---|
| `installment_status` | On Time, Late 1-29, Late 30-59, Late 60-89, Default |
| `days_late` | Optional. Must fit the status bucket (On Time 0, Default 90+) |
| `bureau_balance` | Typed from a bureau extract. ForiFlow has no live ECIB feed |
| `pos_cash_balance` | The month's POS settlement inflow |
| `amount_paid_pkr` | Optional; feeds the collection figures |
| `observation_date` | When the figures were observed; today if omitted, never in the future |
| `data_source_primary` | Which typed source dominated |

The server adds who recorded it, when, the request id, the score and where the
score came from, and the EWS assessment as of that month.

### History is never overwritten

One active row per facility and month (a partial unique index in the
database). Recording a month that is already on file returns `409`. A wrong
month is corrected with `POST /ews/observations/{id}/correct` by a manager or
admin, with a reason: a new row is added, the original keeps every figure and
is marked `superseded`, and the two rows point to each other. Superseded rows
are shown in the history and never used by the trend, state or alerts. The
only change ever made to a recorded row is that status and link.

### Where a score comes from

| `score_source` | Shown as | Meaning |
|---|---|---|
| `origination_assessment` | ForiFlow Assessment (origination) | The baseline: the score the model gave the application |
| `ews_rule_adjusted` | EWS rules applied to the ForiFlow origination assessment | The baseline minus fixed penalties for the month's repayment bucket, bureau leverage and POS shortfall. Not a new model score |
| `officer_override` | Officer Override | A manager or admin typed the score, with a reason. The rule score it replaced is kept beside it |
| `latest_foriflow_assessment` | ForiFlow Assessment | Reserved. This release does not re-run the model on monitoring data |
| `legacy_unknown` | Unknown (recorded before 2.1) | Before 2.1 it was not stored whether a score was typed or derived |

An override needs a manager or admin and a written reason (database check), is
audited with the before (rule score) and after values, and is drawn as a
distinct point on the chart. An analyst's attempt is refused (`403`) and the
refusal is audited.

The rule penalties are unchanged from earlier releases: 0 / 6 / 14 / 26 / 45
points by repayment bucket, up to 12 for a bureau balance above the facility
amount, up to 15 for POS inflow below the underwritten monthly cash flow.

## Trend

From the facility's active observations, oldest month first:

- **Baseline**: the origination score.
- **Latest** and **previous**: the last two recorded months.
- **Total deterioration** = baseline − latest. **Recent deterioration** =
  previous − latest. Positive means the score fell.
- **Slope**: ordinary least squares of score on month number, over the
  monthly observations only (the baseline is the reference, not a point of
  the line). Reported only from **3** observations.
- **Direction**: slope ≤ −1 point a month is *Deteriorating*, ≥ +1 is
  *Improving*, otherwise *Stable*. With fewer than 3 observations it is
  *Insufficient Data*, and the dashboard says "Insufficient history for
  multi-month trend". One bad month is never called a deteriorating trend.

## Signals

Computed on the latest month against the month before it (for the first
month, against the facility at origination: On Time, balance equal to the
facility amount, POS equal to the underwritten cash flow).

| Code | Fires when |
|---|---|
| `PAYMENT_DELAY_INCREASED` | Repayment bucket is later than the month before, or the same bucket with more days late |
| `BALANCE_INCREASED` | Bureau balance more than 5% above the month before |
| `POS_CASH_FLOW_DECLINED` | POS inflow more than 20% below the month before |
| `RISK_SCORE_DECLINED` | Total deterioration above 15 points |
| `RISK_TREND_DETERIORATING` | The trend direction is Deteriorating (needs 3 months) |
| `MULTIPLE_NEGATIVE_SIGNALS` | Two or more of the above at once |

Each signal carries a sentence of evidence and the figures compared.

## States

Kept apart from the credit risk bands (High / Medium / Low Risk) and from any
credit decision. The worst condition met decides:

| State | When |
|---|---|
| CRITICAL | Latest month Late 60-89 or Default, or total deterioration of 30 points or more |
| WARNING | Total deterioration above 15, latest month Late 30-59, a deteriorating trend, or several signals at once |
| WATCH | Latest month Late 1-29, or any single signal |
| NORMAL | None of the above |

The 15-point line is the one the EWS has used since 1.0; 30 is twice it, where
the EWS has advised escalation since 1.0. The 5%, 20% and 1-point-a-month
lines are new in 2.1 and, like the others, are not calibrated on outcomes.

## Alerts

- Raised when a facility reaches **WARNING** or **CRITICAL**. A WATCH facility
  is listed on the dashboard but not alerted.
- **One open alert per facility** (a partial unique index). A later month that
  still breaches updates the open alert rather than opening another; nothing is
  written to the audit trail when the figures did not change.
- The alert always describes the latest active month: severity, reason codes,
  evidence (signals and the state rules that fired), baseline, previous and
  current score, deterioration, the observation it was raised on and the one
  it last rests on, and the recommended actions for its severity.
- **Severity only rises while the alert is open** (WARNING to CRITICAL is
  audited as an escalation). An improving month leaves the alert open for an
  officer to resolve.
- **Auto-close only on a correction**: if a manager corrects the month the
  alert rests on and the facility is no longer WARNING or worse, the alert is
  closed with a note saying so.
- A back-filled earlier month joins the history; the alert still describes the
  latest month.

### Lifecycle

```
Open -> Acknowledged -> Action Required -> Resolved
  \__________\_______________\__________-> Dismissed
```

| Step | Route | Who | Notes |
|---|---|---|---|
| Acknowledge | `POST /ews/alerts/{id}/acknowledge` | manager, admin | From Open only. Records who and when |
| Assign | `POST /ews/alerts/{id}/assign` | manager, admin | Any open status. To an existing officer account; optional due date |
| Due date | `POST /ews/alerts/{id}/due-date` | manager, admin | Not in the past |
| Action required | `POST /ews/alerts/{id}/action-required` | manager, admin | From Acknowledged. Needs the action text |
| Resolve | `POST /ews/alerts/{id}/resolve` | manager, admin | Any open status. Needs a note |
| Dismiss | `POST /ews/alerts/{id}/dismiss` | manager, admin | Any open status. Needs a note, e.g. raised on a typing error |

Resolved and Dismissed are final and stay listed. An open alert past its due
date is flagged overdue. Every step is audited with who, when, the previous
and new lifecycle fields, and the note. `GET /ews/alerts/{id}/history` returns
those entries. There are no notifications: nothing is emailed or sent.

### Recommended actions

| Severity / state | Recommended |
|---|---|
| NORMAL | Continue routine monthly monitoring |
| WATCH | Note the change; check the next POS and bureau figures |
| WARNING | Relationship manager contacts the borrower within 7 days; verify three months of POS and bank statement; obtain an updated bureau extract |
| CRITICAL | Refer to the bank's remedial or recovery unit within 48 hours; obtain an updated bureau extract; consider whether the bank's restructuring or classification process applies |

Recommendations only.

## Authorisation

| Action | Analyst | Manager | Admin |
|---|---|---|---|
| Read history, trend, state, overview, alerts, timeline | yes | yes | yes |
| Record a month (rule score) | yes | yes | yes |
| Override a month's score (with reason) | no (`403`, audited) | yes | yes |
| Correct a recorded month | no | yes | yes |
| Acknowledge, assign, due date, action required, resolve, dismiss | no | yes | yes |

Until 2.0 any officer could take an alert "In Review". Since 2.1 that is a
manager's step. Phase 2 credit-decision authority is unchanged.

## Timeline

`GET /ews/facilities/{id}/timeline` lists the facility's stored events in
order: audit-trail entries for the application, its observations and its
alerts. Rows from before the audit trail (added in 1.10) appear as "stored
record" events with the time the row kept, or none. Nothing is inferred.

## The Markov chain

`ml/ews_markov.py` fits a four-state chain on monthly repayment histories of
consumer card accounts (UCI, Taiwan 2005). Until 2.0 a three-month default
probability of 10% or more raised an alert on its own. The fitted
probabilities (about 0.1%, 2.7%, 30% and 100% for Current, Late 1-59,
Late 60-89 and Default) cross that line exactly at Late 60-89 and Default,
which the rules already mark CRITICAL, so the chain added no alert the rules
miss; and it describes card accounts, not SME loans. Since 2.1 it plays no
part in alerts. Its probability is still returned with a month as
`default_probability_3m`, labelled reference only, and its days-to-default
estimate is kept on the alert for compatibility. A test asserts that the
statuses it flagged are exactly the CRITICAL ones.

## Migration 0008

- Existing observations: kept, `score_source = legacy_unknown`,
  `record_status = active`; date, days late, author and request stay NULL.
- If a facility has two rows for one month, the newest stays active and the
  older ones are kept as superseded, with a note.
- Alert statuses renamed: Active to Open, In Review to Acknowledged (with
  `acknowledged_by` set to the officer who had taken it; the time was not
  recorded). Legacy alerts keep severity, reasons and evidence empty and are
  shown as "Legacy".
- The migration stops if a facility has more than one open alert, because
  choosing which to close is an officer's decision.
- One `migration.applied` audit entry records the counts. Downgrade is refused
  while corrections exist.
- A pre-2.1 SQLite file copied with `scripts/migrate_sqlite_to_postgres.py`
  gets the same markers.

## Limitations

- All monthly figures are typed by officers. There is no bureau, bank or POS
  integration, so the EWS is only as current and accurate as the entries.
- The thresholds are judgement, not calibration. They have not been tested
  against SME default outcomes, and a lender would set its own.
- The monitored score is the origination score minus rule penalties, not a
  fresh model assessment.
- A trend from three to six monthly points is a weak statistic; the slope is
  reported to show direction, not as a forecast.
- There is no disbursement record: an approved application is treated as the
  facility.
- States are computed live from the stored history, but alerts are evaluated
  only when a month is recorded or corrected. A facility whose pre-2.1 history
  now reads WARNING or CRITICAL has no new alert until its next month is
  recorded; the migration does not create alerts retroactively.
