# ForiFlow lender pilot: draft specification and evidence contract

Status: a reviewable proposal, not an activated lending policy, regulatory
approval, production model, data-sharing agreement or live pilot. No lender
partner or lender outcome dataset is established by this document.

## Decisions required from the lender

| Decision | Required specification | Current state |
| --- | --- | --- |
| Intended population | SME segment, geography, eligibility and exclusions | Not agreed |
| Product | Working-capital/invoice/POS/etc.; repayment structure, fees and terms | Not agreed |
| Target | Exact event, threshold, cure/restructure/write-off handling and observation window | Not agreed |
| Decision use | Recommendation, limit, pricing or conditions; human authority and escalation | Existing app supports recommendations and human decisions; pilot mandate not agreed |
| Permitted data use | Collection/use authority, purpose, controller/processor roles, retention and withdrawal process | Source-reference register exists; lender legal/operational process not established |
| Pilot owners | Business, credit risk, data, compliance, security and independent validation | Not appointed |

For example, “ever reaches 90+ days past due within 12 months of disbursement”
is a possible research event/window pairing. It is **not selected** for
ForiFlow and is not a regulatory loan-classification rule. Contractual arrears,
research targets and regulatory classifications must remain distinct.

## Minimum evidence contract

1. **Identity/linkage:** stable pseudonymous borrower and facility identifiers.
   Repeated facilities must be linkable without exporting direct identifiers
   into modelling files. Do not infer identity from business names.
2. **Decision-time record:** application timestamp, product, requested amount,
   tenor, original features, feature-generation version, available-source
   cut-offs, model version, policy version and officer decision/override reason.
3. **Source authority and provenance:** permission/authority reference, terms,
   purposes and validity, source capture/event timestamps, document/version
   identifier, transformation history and review actor. The new case register
   is an after-assessment reference aid, not pre-ingestion enforcement.
4. **Contract:** recorded approval and actual disbursement dates, contractual
   due dates/amounts and documented changes. The current repayment calendar
   records officer assertions and explicit allocations, not bank reconciliation.
5. **Repayment events:** actual event and recording timestamps, stable receipt
   reference, amount in integer paisa, allocation, reversals/corrections and
   reconciliation state. Missing payments are unknown evidence until the
   source is reconciled; they cannot automatically become default labels.
6. **Outcome coverage:** observation start/end, event date and definition
   version, completeness, censoring, cures, restructures and write-offs. A
   “no default” label needs adequate follow-up, not simply no event on file.

Consent/authority for lending does not imply permission for research/training.
External source access, retention and transfers require the lender's approved
arrangements; no new connector or data-access right is created by this draft.

## Evaluation design before training

- Freeze the intended use, target/window and feature-availability cut-offs.
  Exclude information learned after the assessment from its predictor set.
- Design chronological evaluation around actual originations and mature
  outcomes. Keep repeat borrowers together where required by the intended
  test question; explicitly distinguish new-borrower generalisation from
  repeat-borrower monitoring. Do not silently discard overlaps to improve a
  reported score.
- Fit WOE/binning, imputers, clipping, feature selection, resampling and model
  tuning on training data only. Fit calibration on disjoint development data.
  Keep an untouched later-time evaluation sample.
- Compare a logistic baseline and a constrained tree model on the same
  protocol. Evaluate discrimination, precision-recall, calibration curves,
  uncertainty and lender-defined costs/capacity. AUC alone is insufficient.
- Set sample and event-count requirements from the desired precision,
  confidence intervals, model complexity and subgroup coverage. There is no
  universal “two years/thousands of loans” minimum that certifies readiness.
- Officer approvals/overrides are decisions, not repayment ground truth.
  Rejected applicants have unobserved loan outcomes in this book; do not
  label them good/bad or claim unbiased performance on all applicants.
- Evaluate applicable subgroup risks using lawfully available, controlled
  evaluation attributes. Excluding protected fields from model inputs does
  not establish fairness. Sparse groups remain inconclusive.

## Pilot release gates

1. **Data gate:** scope/target agreed; data-use arrangements approved;
   pre-ingestion controls implemented; sources reconciled; histories sufficiently
   mature and complete. The current app does not satisfy this gate by itself.
2. **Validation gate:** independent review of reproducibility, leakage,
   calibration, subgroup limitations, operating thresholds and documented
   acceptance/stop criteria. Current consumer-data benchmarks are not SME
   lending validation.
3. **Security/operations gate:** verified encryption and key management,
   least-privilege access, retention/deletion processes, incident response,
   restore/rollback and third-party review appropriate to deployment.
4. **Shadow gate:** capture predictions against the agreed prospective protocol
   without automated lending action; compare to reconciled later outcomes.
   Define monitoring owners, escalation, disabling and model-promotion authority.

These are completion criteria, not a calendar promise. Outcome maturation and
external reviews may dominate engineering time. FastAPI, React, PostgreSQL and
the existing model registry remain the current stack; additional orchestration,
identity or deployment platforms need a specific operational justification.

## Offline linkage and evaluation

Use `python -m ml.pilot_validation` from `backend` for a lender-approved export
of **one Pakistani SME product**. The tool reads local files and prints
aggregate counts. With `--fit` it also prints candidate evaluation metrics.
Its scope is offline validation. A lender must confirm the product, authority,
data definitions and extraction before files are used. Keep the pseudonym
mapping and source documents with the lender.

### Protocol file

Provide a JSON object with these keys:

| Keys | Value |
| --- | --- |
| `schema_version`, `country`, `product_code` | Version `1`, country `"PK"`, and the one approved lender product code. |
| `target_definition_ref`, `training_authority_ref` | Opaque references to the approved definition and documented scope. These references need human review. |
| `snapshot_at` | Exclusive freeze timestamp for the data and outcomes. |
| `horizon_days`, `event_dpd` | Positive integers selected by the lender. The event is any reconciled end-of-day DPD at or above the threshold on days 1 through the horizon after disbursement. |
| `minimum_per_class` | Pre-agreed minimum number of distinct borrowers with each outcome in **each** cohort, with a software floor of 2. Choose the actual minimum from the evaluation's precision and risk requirements. |
| `train`, `calibration`, `test` | Objects with `first` and `last` calendar dates in `YYYY-MM-DD`. The disbursement-date windows are inclusive, ordered and disjoint. Leave enough time for each earlier cohort's labels to mature before the next starts. |

Timestamps use an ISO time including seconds and an offset, for example
`2025-01-03T09:00:00+05:00`. Calendar comparisons use Pakistan time.
Choose the product, target, cutoffs, required precision and review criteria
before inspecting later cohort metrics.

### Facility export

One row per actually disbursed facility. The CSV requires these columns:

```text
facility_id,borrower_id,country,product_code,assessed_at,disbursed_at,evidence_available_at,source_review_ref,requested_amount_pkr,annual_turnover_pkr,payment_history_score,years_in_operation,tenure_months,existing_debt_pkr,inventory_turnover,order_consistency,num_employees
```

- Use stable, lender-issued pseudonyms. Facility IDs use `fac_` followed by 32 lowercase hex characters. Borrower IDs use `brw_` and the same format. Keep all repeats for a borrower under one pseudonym. Omit names, contact details, government identifiers and other direct identifiers.
- `evidence_available_at` is the latest time any input and its verification were available. It must be at or before `assessed_at`, which must precede or equal the actual `disbursed_at`. The `source_review_ref` points to an evidence record supporting all inputs.
- Use verified requested principal and annual turnover, a consistent 0–100 repayment-history definition, and years in operation as of assessment. The baseline uses requested amount divided by turnover, repayment history, and business age. It is fitted on this dataset.
- The additional fields use requested term in months, outstanding principal in PKR at application, annual cost of goods sold divided by average inventory, the defined 0–100 order count stability from complete order-ledger months, and headcount including working owners. Align definitions and periods with the approved protocol. Enter a blank for unavailable or inapplicable values.

### Daily DPD export

The lender derives this export from reconciled repayment and schedule records
for newly disbursed facilities. The tool rejects DPD that predates
disbursement. Keep rebooked or restructured balances with inherited arrears
outside this protocol.
Provide one row per facility and Pakistan calendar day, sorted by
`facility_id` and `observation_date` ascending.

```text
facility_id,observation_date,available_at,days_past_due,reconciled
```

Use the timestamp when the value was actually available, including corrections,
and `yes` or `no` for reconciliation. Blank DPD is allowed for an unreconciled
row. A genuine observed zero requires a reconciled row. To receive a label,
a facility needs every calendar day in the target window reconciled and
available by its cutoff. That applies even if an early event was recorded.
Training labels must be available before calibration starts, and calibration
labels before test starts. An assessment must also fall on or after the start
of its disbursement cohort so an earlier application cannot benefit from labels
that were only available when the later cohort opened. Test outcomes use the
snapshot cutoff. Exports with
early closure or missing days need a lender-agreed coverage treatment before
they can be counted. Review the effect of those exclusions separately.

### Run

```text
python -m ml.pilot_validation --protocol protocol.json --facilities facilities.csv --daily-dpd daily-dpd.csv
python -m ml.pilot_validation --protocol protocol.json --facilities facilities.csv --daily-dpd daily-dpd.csv --fit
```

The first command checks linkage, missing evidence, mature windows, outcome
balance and borrower overlap. Exit status `3` means cohort blockers, and
`2` means invalid input or a processing error. Fit only after the authorised
protocol and input snapshots are frozen. Keep any local reports within the
approved environment.

The second command evaluates a logistic baseline, one candidate per additional
field, and one using all five. Every candidate uses the same complete-case
rows. Preprocessing and fitting use only training data. Sigmoid calibration
uses the separate calibration cohort. Results include test ROC AUC and average
precision on model scores, calibrated Brier score, a calibration direction
check, and a paired borrower-resampled ROC AUC interval for the full candidate.
The interval measures sampling variation in that test cohort. Check excluded
populations, subgroup performance, stability, operating thresholds and shadow
outcomes in the independent review before any decision about live scoring.
