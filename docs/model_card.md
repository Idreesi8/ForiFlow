# ForiFlow credit model card

> **This model is a demonstration model trained on public consumer credit data. It is not validated for Pakistani SME lending and must not be used for autonomous credit decisions.**

| | |
|---|---|
| Model version | `ensemble-xgb-rf-credit_risk_shared-2026-10-08T17:36:16` |
| Release | ForiFlow 2.2.0 (training protocol 2.2.0) |
| Training date | 2026-10-08T17:36:16 (PKT) |
| Artifact fingerprint | `2b2b350c8a8a74ec9459005dc182236a28595f74345d361080dc426bae0d239d` (SHA-256 over `foriflow_model.pkl`, `scaler.pkl`, `shap_explainer.pkl`, `feature_names.json`, as computed by the API and stored in `model_versions`) |
| Dataset SHA-256 | `ce3c6d2167717bf1627d1c0c81cbccd28323cd4aa7b96d542599366d5ff6aac8` (`credit_risk_dataset.csv`) |
| Random seed | 42 |

All figures below come from `backend/ml/feature_names.json` (training run),
`backend/ml/model_evaluation.json` (final test, measured once) and
`backend/ml/data_quality_report.json`. The Model page and `GET /model/card`
show the same figures.

## 1. Model purpose

To rank loan applicants by estimated default risk and to explain each score
with per-feature attributions, as one input to a credit officer. The model
produces an assessment; the credit policy turns it into a recommendation; an
officer makes every decision (see section 23).

## 2. Intended use

- Demonstration and academic evaluation of an explainable credit-scoring
  workflow (assess, explain, recommend, human decision, monitor, audit).
- A pilot in which every recommendation is reviewed by a credit officer and
  the model is re-validated on the lender's own data before any reliance.

## 3. Out-of-scope use

- Autonomous approval, rejection or pricing of any loan.
- Any claim of accuracy for Pakistani SMEs, of bank-grade default prediction,
  of SBP validation or of production underwriting performance. None has been
  shown.
- Use on populations unlike the training file without re-validation.

## 4. Dataset

`credit_risk_dataset.csv`, the public "Credit Risk Dataset": 32,581 consumer
loans, 12 columns, outcome `loan_status`. **Public consumer credit data, not
Pakistani SME banking data.** Amounts are in the file's own currency; ForiFlow
uses ratios so no exchange rate is assumed.

## 5. Dataset limitations

- Consumers, not businesses. "Years in operation" is mapped from years of
  employment and "payment history" from a single prior-default flag.
- 165 exact duplicate rows (dropped before the split, see section 8).
- Missing values: `person_emp_length` 895 rows (2.7%), `loan_int_rate` 3,116
  (9.6%, not a model input).
- Implausible values: 5 ages above 100 and 2 employment lengths above 60
  years (clipped by the training-split percentiles, not removed).
- No gender, region, religion or ethnicity, so fairness on those cannot be
  analysed.
- Unknown sampling, time period and lender; default definition is the file's.

## 6. Target definition

`loan_status = 1` as recorded in the public file (the loan defaulted). The
exact delinquency definition and observation window are not documented by the
source. Default rate: 21.8% (7,108 of 32,581).

## 7. Features

The model reads three features, all built from intake fields:

| Feature | Built from | Training source |
|---|---|---|
| `loan_to_income` | loan amount / (12 × max(monthly digital payments, monthly cash flow)) | loan amount / annual income |
| `payment_history_score` | officer-entered 0-100, read as clean (above 52.5) or adverse | prior default on file: 80 clean, 25 adverse |
| `years_in_operation` | years trading | years of employment |

Collected but **not used** by this model: tenure, existing debt, inventory
turnover, order consistency, employees. The form marks them, using
`GET /model/feature-contract`. Identity and reporting fields (names, CNIC/NTN,
phone, sector) are never inputs. Age is deliberately not a feature.

## 8. Preprocessing

In this order (`backend/ml/pipeline.py`, version 2.2.0):

1. Drop exact duplicate raw rows (165), before any split.
2. Map onto the three features.
3. **Split** (section 13).
4. Median imputation, medians learned on the **training split only**
   (`loan_to_income` 0.148, `payment_history_score` 80, `years_in_operation` 4).
5. Clip to the training split's 1st / 99th percentiles
   (`loan_to_income` 0.02-0.50, `payment_history_score` 25-80,
   `years_in_operation` 0-18).
6. `StandardScaler` fitted on the training split.

Before 2.2 the medians and clip bounds were learned on the whole file before
the split. That leak is fixed; serving applies the stored training-split
bounds.

## 9. SMOTE methodology

SMOTE (k = 5, seed 42) is applied to the scaled **training** rows only, and
inside each cross-validation fold to that fold's training part only
(`imblearn` pipeline). Validation and test rows are never resampled. Because
the model learns from 50/50 data, its raw probability runs high (mean 0.44
against a 0.22 default rate); it ranks well but is not a probability of
default without calibration.

## 10. Model architecture

Soft-voting ensemble: XGBoost (300 trees, depth 5, learning rate 0.08) and a
random forest (250 trees, depth 12, min 40 per leaf). Both are constrained to
be monotone: a larger facility against turnover never lowers risk, a clean
history and more years never raise it.

## 11. Ensemble weights

XGBoost 0.6, random forest 0.4. Fixed by design in an earlier release; not
tuned on any evaluation set.

## 12. Evaluation methodology

- 5-fold stratified cross-validation on the training split, everything
  (imputation, clipping, scaling, SMOTE, model) refitted per fold.
- Validation split: baseline comparison and calibrator choice and fit.
- Final test set: one measurement of everything, after all choices were fixed
  (`python -m ml.evaluate_model` refuses a second run for the same model).
- **Model evaluation threshold:** raw probability ≥ 0.5 for precision, recall,
  F1 and the confusion matrix. Fixed in advance (the natural cut for a model
  trained on 50/50 data), never tuned. It is not a credit policy threshold.
- Score bands in the evaluation tables use 40 / 70 (the demo policy v1.0
  values) for comparability; they describe the evaluation, not the policy in
  force.

## 13. Final test set

Stratified split, seed 42: 20% final test first, then 25% of the rest as
validation. Training 19,449 rows, validation 6,483, final test 6,484 (default
rates 21.87% / 21.87% / 21.87%). Row-id fingerprints of each set are stored in
the metadata and checked before the final evaluation runs. The final test set
was not used to choose hyperparameters, thresholds, the calibrator, policy
bands, features, the preferred model or any fairness threshold.

One residual: the choice of this dataset over two other public files was made
in release 1.x by cross-validation over each whole file, before this protocol
existed. That dataset-level choice is not re-run.

## 14. Metrics

Final test set, raw ensemble probability (threshold 0.5):

| ROC-AUC | PR-AUC | Precision | Recall | F1 | Brier | Accuracy |
|---|---|---|---|---|---|---|
| 0.7748 | 0.5671 | 0.493 | 0.623 | 0.551 | 0.1845 | 0.778 |

Confusion matrix: 884 defaulters caught, 534 missed, 909 good payers flagged,
4,157 passed. Cross-validation on the training split: ROC-AUC 0.7743 ± 0.0073.
Validation: 0.7798.

**Before and after the protocol fix.** The 2.1 model reported hold-out
ROC-AUC 0.7731 (PR-AUC 0.5645, F1 0.5464, raw Brier 0.1852) and CV 0.7752,
with leaked preprocessing and a reused hold-out. The 2.2 final-test figures
are of the same size; the leak did not materially inflate the figures, but
the 2.2 figures are the ones that can be defended.

**Baselines** (same split and preprocessing; final test):

| Model | ROC-AUC | PR-AUC | F1 | Brier (raw) | CV AUC (train) | CV paired p vs ensemble |
|---|---|---|---|---|---|---|
| Logistic regression | 0.7630 | 0.5329 | 0.515 | 0.190 | 0.7619 ± 0.0059 | 0.001 |
| XGBoost alone | 0.7744 | 0.5652 | 0.549 | 0.177 | 0.7737 ± 0.0068 | 0.14 |
| Random forest alone | 0.7732 | 0.5635 | 0.534 | 0.206 | 0.7719 ± 0.0083 | 0.03 |
| **Ensemble (served)** | **0.7748** | **0.5671** | **0.551** | **0.185** | **0.7743 ± 0.0073** | — |

Reading: the ensemble beats logistic regression by about 0.012 AUC, a clear
but modest gap. Against XGBoost alone it is ahead by 0.0004 on the final test
set and the cross-validation difference is not significant: **the ensemble
adds no meaningful value over XGBoost alone** on this data. It is kept because
it was the existing served model and changing it is out of scope for 2.2.

## 15. Calibration

- Raw probability: Brier 0.1845, expected calibration error 0.225, mean 0.443.
- Chosen method: **isotonic regression over bins of 250 loans**, chosen
  against Platt (sigmoid) scaling by 5-fold out-of-fold Brier within the
  validation split (isotonic 0.13033, sigmoid 0.13034, none 0.18654: the two
  methods are practically equal), then fitted on the whole validation split
  (6,483 rows).
- Final test: calibrated Brier **0.1304** (no-skill 0.1709), ECE 0.014, mean
  0.214 against 0.219 observed. ROC-AUC 0.7746 (calibration is monotone and
  does not reorder applicants; the small change comes from ties).
- **Display only.** The score stays `100 × (1 − raw probability)`, the bands
  and SHAP use the raw probability, and the calibrated figure is labelled
  "Calibrated PD (display only)" in the dashboard. It is calibrated to the
  public file's 21.9% default rate, not to any Pakistani portfolio.

## 16. SHAP methodology

- One interventional TreeSHAP explainer per member in probability space,
  combined with the voting weights, so contributions add up to the
  ensemble's raw probability; × −100 gives score points.
- **Model reference baseline** (the SHAP base value): the ensemble's
  expected score over a 50-row random sample of the SMOTE-balanced training
  rows, 47.97 points. It is not the average of a bank portfolio or of the
  public file.
- Additivity is verified: at training (max error 1.7e-7 on validation rows)
  and at every score, where each member's attributions must add up to its own
  prediction within 1e-6. 2.2 fixes a case where an input exactly on a split
  threshold (for example 0.5 years) was explained against the neighbouring
  leaf (an error of up to 0.11 score points); see
  `tests/test_ml_protocol.py::test_shap_reproduces_every_member_and_the_ensemble_exactly`.
- Displayed contributions are rounded to 0.01 points, so the displayed sum
  can differ from the score by a few hundredths.
- Reason codes R01-R03 are derived from these contributions.

## 17. Known limitations

- Consumer data, three features, binary repayment history, mapped proxies.
- Turnover is estimated from officer-entered digital receipts or cash flow.
- No bureau, bank or POS integration; no live ECIB connector.
- No time-based validation (the file has no dates), so stability over time
  is unknown.
- The ensemble adds nothing measurable over XGBoost alone.
- Drift is measured against the public training file (reference / demo
  distribution), not a bank portfolio.
- EWS monitoring in a pilot uses officer-entered or demo data.

## 18. Fairness / subgroup analysis

"Subgroup Performance Analysis" on the final test set, for attributes the
model does not read: age band, income quarter (cut on the training split),
housing and loan purpose. Per group: count, default rate, ROC-AUC, precision
and recall at the evaluation threshold, calibrated against observed default
rate. Groups under 100 loans, or with under 10 defaults or non-defaults, are
marked "Insufficient sample size" (housing "Other", 18 loans). Observations:
ROC-AUC ranges from 0.65 (mortgage holders) to 0.86 (business-venture loans);
discrimination is weakest among the highest-income quarter (0.66) and
mortgage holders. These are descriptive. Similar figures would not show the
model is fair, and the file has no gender, region or religion.

## 19. Version

`ensemble-xgb-rf-credit_risk_shared-2026-10-08T17:36:16`, ForiFlow 2.2.0.
It is registered as a new row in `model_versions` with its provenance
(dataset hash, split fingerprints, seed, preprocessing version, calibration
method, configuration). The 2.1 model's row, its fingerprint, its metrics and
every application it scored are unchanged.

## 20. Training date

2026-10-08T17:36:16 (PKT).

## 21. Dataset hash

SHA-256 `ce3c6d2167717bf1627d1c0c81cbccd28323cd4aa7b96d542599366d5ff6aac8`.

## 22. Model artifact hash

Combined fingerprint `2b2b350c8a8a74ec9459005dc182236a28595f74345d361080dc426bae0d239d`.
Files: `foriflow_model.pkl` `0a596a02…`, `scaler.pkl` `04bf59cc…`,
`shap_explainer.pkl` `a89e5047…`, `feature_names.json` `906e8fb0…`.

## 23. Decision-policy separation

- **Model**: score and probabilities (this card).
- **Policy**: configurable, versioned cut-offs (demo v1.0: decline ≤ 40,
  manual review ≤ 70) and approval authority, on the Credit Policy page. Each
  application stores the policy snapshot it was assessed under. The cut-offs
  were not derived from or optimised on these results.
- **Human**: an authorised officer approves, rejects or escalates every
  application with a written reason.
- The model page shows "Model Evaluation Thresholds" and "Current Credit
  Policy Thresholds" side by side and never presents one as the other.

## 24. SME deployment requirements

Before any use on Pakistani SMEs: a data-sharing agreement with a lender,
historical SME loans with outcomes, retraining under the same protocol,
validation on a time-separated test set, a fairness review on attributes the
lender holds, calibration to the lender's portfolio, and independent model
risk review. The data needed is listed in
[sme_data_requirements.md](sme_data_requirements.md).
