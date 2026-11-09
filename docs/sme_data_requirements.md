# Data readiness: what an SME model would need

| | Dataset | Status |
|---|---|---|
| **Current demo dataset** | Public consumer credit dataset (`credit_risk_dataset.csv`, 32,581 consumer loans) | In use. Trains the demonstration model. Not SME data, not Pakistani data. |
| **Production / pilot dataset** | Pakistani SME lending data from a lender | **Required, not available.** No SME model exists until it is. |

ForiFlow does not train a model on transformed consumer data and call it an
SME model, and makes no claim of Pakistani SME accuracy, bank-grade default
prediction, SBP validation or production underwriting performance.

The fields below are **data requirements** for a future data partner, derived
from what ForiFlow's assessment, policy, decision and monitoring layers
already use. They are not a statement that the current model uses them: it
uses three features (see [model_card.md](model_card.md), section 7).

## Required fields

| Category | Fields | Why ForiFlow needs it |
|---|---|---|
| Borrower identity / reference | Stable borrower ID (pseudonymised), CNIC/NTN hash, business name | Link repeat applications and facilities without exposing identity; ForiFlow already keys borrowers this way. |
| Business tenure | Date business started, or years trading at application | The current model's `years_in_operation`, measured on real businesses. |
| Requested facility | Amount, tenure, product, purpose, application date | `loan_to_income` and affordability; the date allows a time-based test set. |
| Income / cash flow | Monthly turnover and net cash flow from bank statements or POS settlements, 6-12 months | Replaces the officer-typed turnover proxy; the strongest SME signal. |
| Repayment history | Prior facilities' payment records, days past due by month | Replaces the binary clean/adverse flag with a real history. |
| Existing obligations | Outstanding facilities, instalments due, lenders | Real debt service, not a balance divided by an assumed 36 months. |
| Inventory | Cost of goods sold and opening/closing inventory for the same period, with dates and valuation method | Supports a consistent turnover definition for stock-holding businesses. |
| Orders | Dated order IDs and cancellation status, with explicit months of complete coverage | Counts orders once and distinguishes an empty month from a missing month. |
| Headcount | People working in the business, including working owners, measured as of a specified date | Separates the headcount definition from jobs retained, jobs created and full-time equivalents. |
| Bureau information | ECIB report fields at application (exposure, overdues, enquiries) | Bureau signals, with the lender's permission and SBP rules on use. |
| Facility history | Disbursement date, limits, utilisation, restructurings, write-offs | Defines exposure and monitoring periods; feeds the EWS with real months. |
| Default / outcome label | Whether the facility reached a defined default (e.g. 90+ days past due, restructuring, write-off) within a fixed window, and when | The target. Without it nothing can be trained or validated. |
| Decision record | Approved / rejected, by whom, policy in force | Measures reject-inference bias: outcomes exist only for approved loans. |

## Public data used for the additional fields

ForiFlow shows the measured results under **Model Performance → Data for the
additional fields → What the public data showed**. These are separate studies
with separate populations and targets. Only aggregate results are published.

| Field | Source and use | Limit for the pilot |
|---|---|---|
| Inventory turnover | [UCI Polish Companies Bankruptcy](https://doi.org/10.24432/C5F600), Sebastian Tomczak (2016), CC BY 4.0. Tests whether inventory days (Attr47) add predictive value on the one-year bankruptcy cohort. | The ratio uses inventory and cost of products sold. The outcome is corporate bankruptcy in Poland. ForiFlow needs consistent inventory accounting and linked loan outcomes. |
| Order consistency | [UCI Online Retail](https://doi.org/10.24432/C5BW33), Daqing Chen (2015), CC BY 4.0. Tests distinct invoice counts on a 1,000-line sample for one UK retailer. | The sample covers part of one day. Measuring regularity requires full months and linking the order series to the facility requires separate loan data. |
| Tenure | [Li, Mickel and Taylor’s SBA teaching dataset](https://doi.org/10.1080/10691898.2018.1434342). Tests recorded term and employee count against eventual charge-offs in a historical California real estate and rental cohort. | A post-outcome extract from resolved loans can describe historical associations. The term recorded at origination, comparable observation windows and transport to Pakistani SMEs require separate verification. |
| Outstanding debt and headcount | [Federal Reserve 2003 Survey of Small Business Finances](https://www.federalreserve.gov/PUBS/oss/oss3/ssbf03/ssbf03home.html). Profiles outstanding principal (S1, USD) and employees including working owners (A_TOTEMP). The Polish study also tests the liabilities/assets ratio (Attr2). | The historical US survey has no prospective repayment label. A ratio of liabilities to assets cannot supply an outstanding principal balance or instalment schedule. |

The Polish study uses the published one-year file only. It uses the same
complete-case sample for all three models, discards conflicting duplicate
predictor vectors and retains one copy of other duplicate vectors. A fixed,
stratified 25% test set gives an internal comparison. The file supplies neither
entity IDs nor calendar dates, which prevents verification of independent firms
or later-time performance.

The SBA study uses one teaching cohort containing only paid-in-full and
charged-off loans. It checks that the provided label agrees with reported
status, then uses the same valid-amount, valid-term and valid-headcount rows
for all models. The baseline uses approved amount. The model is fitted on
1989–2005 disbursements and scored on 2006–2010 disbursements. This is a
retrospective split by disbursement year. Outcomes for earlier loans may have
become known after later disbursements, and the supplied term may reflect
revisions. The report counts cases where term is within one calendar month
of the elapsed time to charge-off as a check for direct duplication of that
elapsed time. It cannot establish when the term value became available.

Both studies fit logistic regression and its scaler on training rows only.
They report ROC AUC and average precision on the same test cases for each
feature set. Interpret a small metric difference as a descriptive result.
Neither study estimates a Pakistani SME default probability.

The retail analysis uses the available 1,000-line extract from the morning
of December 1, 2010. It excludes cancellation codes and lines with
nonpositive quantity or price, and counts each eligible invoice once.
The survey profile takes one of the five
imputed copies, then uses only reported or edited values as marked by the
[survey codebook](https://www.federalreserve.gov/pubs/oss/oss3/ssbf03/codebook/index.html).
Survey summaries are unweighted and describe the observed sample.

To reproduce the report, run the following from the repository root with
NumPy, pandas, scikit-learn and a `gzip` executable that reads `.Z`
files. On Windows, pass the executable path with `--gzip` if needed.

```text
python scripts/fetch_sme_datasets.py --sources polish sba_loans retail_orders ssbf ssbf_layout
python scripts/benchmark_sme_fields.py
```

The benchmark script verifies the cached source fingerprints, including the
pinned SBA and retail mirrors, and writes
`backend/ml/sme_dataset_benchmarks.json`. The raw files stay in
`.local/datasets/sme-field-research`.

## Planning requirements for a first credible pilot model

- Sufficient mature SME facilities, default/non-default events and subgroup
  coverage for the intended model complexity and statistical precision. Determine
  counts from an evaluation design; no fixed count certifies readiness.
- Originations and follow-up spanning the agreed outcome window and a later-time
  evaluation period. Duration depends on the product and event definition.
- A written default definition and observation window agreed with the lender.
- A data-sharing agreement covering privacy, retention and permitted use.

## What happens when the data arrives

1. Run the same 2.2 protocol (`backend/ml/pipeline.py`): data-quality report,
   split before learning anything, train-only preprocessing, SMOTE on training
   rows only, calibrator on validation, one final test.
2. Prefer a time-based final test set (latest originations) over a random one.
3. Re-run the baseline comparison; keep the simplest model that is not
   clearly worse.
4. Subgroup analysis on the attributes the lender holds, reviewed by the
   lender's own risk and compliance functions.
5. Register the result as a new model version; earlier versions and every
   application they scored stay as they were.
