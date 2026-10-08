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
| Bureau information | ECIB report fields at application (exposure, overdues, enquiries) | Bureau signals, with the lender's permission and SBP rules on use. |
| Facility history | Disbursement date, limits, utilisation, restructurings, write-offs | Defines exposure and monitoring periods; feeds the EWS with real months. |
| Default / outcome label | Whether the facility reached a defined default (e.g. 90+ days past due, restructuring, write-off) within a fixed window, and when | The target. Without it nothing can be trained or validated. |
| Decision record | Approved / rejected, by whom, policy in force | Measures reject-inference bias: outcomes exist only for approved loans. |

## Minimum for a first credible pilot model

- Several thousand SME facilities with outcomes, including enough defaults
  (hundreds, not dozens) to estimate discrimination and calibration.
- At least two years of originations, so the final test set can be
  later in time than the training data.
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
