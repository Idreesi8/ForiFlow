# Repayment evidence for future model learning

7 November 2026, Pakistan time.

ForiFlow stores assessments and monitoring records, but an officer previously
had to inspect histories individually to find out whether an outcome window
had enough evidence for future validation. A new section on Model Performance
shows coverage across the complete approved portfolio, with a paged facility
list and links to each facility's monitoring records.

## Reading the report

Select the first 3, 6 or 12 reporting months. The window is measured from the
recorded officer approval, using monthly anniversaries clamped to month-end.
Approval is a proxy: ForiFlow does not store an independent disbursement date.
The report uses today's Pakistan calendar date and UTC recording timestamps.

Every approved facility belongs to exactly one status:

- **Approval record needed:** officer approval or its date is missing, is in
  the future, or is a legacy automatic decision. A recommendation is not an
  approval anchor.
- **Shorter than window:** the facility's tenure is shorter than the selected
  window. This is a different observation period, not a negative outcome.
- **Window still open:** the final anniversary has not arrived.
- **Records need attention:** the window elapsed but one or more selected
  months are missing or incomplete.
- **Window covered:** each selected month has usable recorded evidence.

A usable month is an active observation dated on or after its approval-based
anniversary and no later than today, with a named recorder, a non-future
recording timestamp, non-legacy provenance, a finite nonnegative payment amount
and exact days late consistent with its installment-status bucket. Zero is a
known payment amount; NULL is unknown. Superseded corrections and months outside
the selected window are excluded. A later month cannot fill an earlier gap.

The covered-window count containing a recorded 30+ day delay is descriptive.
It is not a default rate, calibrated default probability, accuracy score or
causal estimate. This window uses reporting-month labels, not a lender-validated
default event within a disbursement-based calendar horizon. Entered evidence is
not independently verified. Complete coverage alone never enables training.

The borrower counts use actual database links. Shared names or phone numbers
do not create relationships. Repeat facilities are flagged because a future
validation protocol must keep related borrowers together. Rejected and
undecided cases have no observed facility outcome here; treating those as
non-defaults would create unsupported labels and selection bias.

## Interface and API

`GET /model/outcome-evidence?horizon=3&limit=10&offset=0` requires the current
authenticated account. `horizon` accepts 3, 6 or 12; `limit` accepts 1–100;
`offset` is nonnegative. Optional `status_filter` accepts the five status IDs
in `outcome_schemas.py`. Counts always cover the complete approved portfolio;
`total` and `rows` follow the selected filter. Pages have stable case-ID order.

Responses carry `Cache-Control: no-store`, a capture time, an as-of date,
explicit method/limits and `training_ready: false`. The two database reads do
not change a case, decision, audit, model, policy or schema. No model inference
is needed. Changing filters cancels outdated requests and hides old-query data;
inconsistent counts are withheld. Failures offer an explicit retry. Evidence
remains available if the separate static evaluation fails to load.

## Next development steps

1. Agree a default definition and observation window with a data partner, add
   independently sourced disbursement/outcome dates and permitted-use records,
   and collect representative SME histories with positive and negative outcomes.
2. Design borrower-grouped, chronological validation before fitting feature
   selectors, imputation, resampling or hyperparameter searches. Keep the final
   test separate from every research decision; compare simple baselines first.
3. Run a bounded offline challenger study (feature selection or AutoML) on
   approved research data. Compare discrimination, calibration, stability and
   subgroup performance; a successful search does not promote a model by itself.
4. Investigate GNNs only when genuine relationship edges and an appropriate
   task/labels exist. Investigate reinforcement learning only with consented
   action/outcome logs, a justified reward, controlled comparisons and human
   oversight. Repayment rows alone are neither of these training datasets.

The validation design follows [scikit-learn's guidance on grouped and time
series cross-validation](https://scikit-learn.org/stable/modules/cross_validation.html).
The feedback inventory is consistent with the monitoring and evaluation
principles in the [NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/);
this is a design reference, not a compliance certification.
