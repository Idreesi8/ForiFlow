# Feature engineering study — 28 October 2026

ForiFlow now has a reproducible research runner and an authenticated Model-page
view of measured results. No estimator or serving feature was replaced.
The intake guidance also explains the binary history encoding and the unvalidated
mapping from personal employment duration to business age.

## Question and protocol

Can algebraic feature expansion or categorical-aware resampling improve on the
current three-input ensemble recipe without collecting new measurements?

The candidate list and experiment settings were recorded in `protocol.json`
before the first fit. All four candidates used the same five stratified folds
within the existing **19,449 training rows**, seed 42. Original dataset SHA-256
and all three partition-membership hashes were checked against serving metadata.
The 6,483 validation and 6,484 previously evaluated final-test rows were excluded
from exploration, fitting, permutation checks and new metrics. The full source
file and labels are read only to reconstruct the original stratified partition;
excluded observations are discarded before research begins.

Every fold learns median imputation, 1st/99th percentile clipping and scaling
on its fit rows. Sampling is applied only to fit observations. Tree learner
hyperparameters and constraints are the existing recipe; `n_jobs=1` and a single
thread-pool limit bound laptop resource use. Software versions are recorded.
This is a new run of the recipe, not a re-evaluation of the exact saved estimator.

Candidates were fixed before seeing results:

1. Current ensemble recipe with SMOTE.
2. Same ensemble with SMOTENC, marking the history column categorical.
3. Logistic regression with the original three features and SMOTENC.
4. Logistic regression with SMOTENC and five fixed terms: `log1p(ratio)`,
   adverse-history indicator, `log1p(duration)`, log-ratio × adverse indicator,
   and log-ratio / (1 + duration).

For the engineered model, sampling happens **before** expansion. The original
fit-only scaler is inverted before computing terms, so units are correct and
the generated interaction terms remain algebraically consistent. The engineered
model has no guaranteed monotonicity and cannot inherit serving approval-path
guarantees. New formulas provide no new observed evidence.

## Actual results

Means over five shared training folds:

| Candidate | ROC-AUC | Fold SD | PR-AUC | Brier |
| --- | ---: | ---: | ---: | ---: |
| Current ensemble recipe | 0.774416 | 0.007331 | 0.568628 | 0.185590 |
| Ensemble, categorical sampling | 0.774379 | 0.007357 | 0.568632 | 0.185575 |
| Linear logistic, categorical sampling | 0.761917 | 0.005890 | 0.533153 | 0.192060 |
| Engineered logistic, categorical sampling | 0.764294 | 0.006348 | 0.538958 | 0.193316 |

Expansion changed logistic ROC-AUC by **+0.002377**, while Brier worsened by
**+0.001256**. The categorical ensemble differed from the current recipe by
**−0.000037 ROC-AUC**. These comparisons provide no basis for replacing the
serving model. ROC-AUC is a ranking measure, not percentage accuracy. Brier here
uses uncalibrated, sampling-balanced probabilities and is not an absolute lending
risk estimate. Fold SD is not a confidence interval. Comparisons are exploratory;
fold fit sets overlap and no independent superiority claim is made.

Across the five fit folds, **both samplers generated 43,772 observations and zero
out-of-category history values**. The original SMOTE recipe could interpolate
categories in principle, but that suspected problem was **not observed here**.
Counts include overlapping fit observations and do not represent unique people.

## What the three inputs can distinguish

Shuffling each original input three times per fold's score rows reduced the
current recipe's ROC-AUC by these mean amounts:

| Input | ROC-AUC drop |
| --- | ---: |
| Facility / annual income proxy | 0.191812 |
| Binary repayment history | 0.056403 |
| Duration proxy | 0.014303 |

These values describe dependence of this fitted recipe under permutation, not
causal effects, proportions of default risk or recommendations for borrowers.

Training-only information audit: 12,776 unique effective input vectors;
9,257 rows occur in repeated vectors; **3,712 rows** belong to 689 vectors with
both outcome labels. These are different raw observations with identical
effective model inputs, not necessarily bad labels or duplicate borrowers.
The three observed features cannot distinguish all such cases. There is no
borrower identifier to establish entity independence in this public file.

Of the training rows, 541 employment-duration values are missing and median
imputed. Facility-ratio clipping affects 184 low and 172 high observations;
duration clipping affects 132 high observations. No unknown prior-default flags
were found. This run does not change existing missing-value handling or clips.

## User-facing changes and safeguards

- Model → **Feature engineering: measured results** shows candidate comparisons,
  feature dependence, sampling checks and explicit study limitations.
- `GET /model/feature-study` requires a session and returns `Cache-Control:
  no-store`. It performs no inference, registration, assessment save or decision.
- A completed report must match the loaded credit artefact fingerprint. Missing,
  incomplete, nonfinite or incompatible results are withheld with a retry path.
- The offline publisher checks all six original artefact hashes before publishing
  and refuses to overwrite an existing research record.
- Intake no longer calls the officer history estimate an “ECIB-oriented” scale.
  It explains identical effects within each binary category. Business-age guidance
  and input inspection disclose the employment-duration mapping.
- The feature contract now includes original training definitions and semantic
  gaps for the three served features. Inventory, debt, headcount and other
  operating fields remain outside this credit model.

## Reproduce

From `backend`, with the recorded dependency versions and original local CSV:

```powershell
python -m ml.feature_engineering --output ../archive/feature-engineering-new-run
```

The output must be a **new directory outside `backend/ml`**. This writes a
protocol and results, never an estimator or serving artefact. Explicit offline
publication is separate:

```powershell
python -m services.feature_study ../archive/feature-engineering-new-run/report.json
```

An existing published report must first be deliberately archived; the publisher
does not overwrite it. The original measured report is
`archive/feature-engineering-2026-10-28/run-01/report.json`; the published copy is
`backend/ml/feature_engineering_report.json`. The Model page serves a validated
summary, not raw records, row identifiers or financial documents.

Future credit features need consistent definitions, measurement timestamps,
evidence provenance and prospectively timed SME outcomes. Source personal income
is not SME digital receipts/net cash flow, and employment duration is not business
age. This experiment does not validate those transfers or Pakistani SME lending.

## Verification and deployment

- 62 Windows backend checks passed (research, report/API and existing ML protocol).
- 72 checks passed in the final Linux image, with network disabled, a read-only
  root filesystem and no pilot credentials or database mounted. These include
  33 research/report checks also run on Windows and 39 input-check regressions:
  **101 distinct backend checks** across the two runs, not 134 unique checks.
- 84 frontend unit checks and the final production build passed.
- 13 browser checks passed: measured candidate/permutation/sampling content,
  failed-request retry, incomplete-response withholding and keyboard recovery,
  desktop/mobile layout, deployed results and live intake guidance.
- The final live stack is ready and serving the ML engine. Fingerprints of all
  10 database tables and all six serving model artefacts match their pre-update
  values. The deployed backend research/contract files match local source hashes.
  No live assessment or officer decision was created or modified.
- Existing frontend/backend images were tagged before rebuilding. A new database
  dump was made and its archive contents validated using `pg_restore --list`;
  this check is not a full scratch-database restore.
- Temporary QA helpers used a new empty local database and were stopped after
  testing. The live Model summary is left open with normal browser sizing.

Detailed logs, fingerprints, the original protocol/results, the browser check
record and `live-feature-study.jpg` are retained in
`archive/feature-engineering-2026-10-28/`. This local evidence directory is ignored
by Git; the measured report and research implementation belong to the project.

Method references: [SMOTENC's categorical/continuous contract](https://imbalanced-learn.org/stable/references/generated/imblearn.over_sampling.SMOTENC.html),
[fit-only preprocessing and leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage),
and [permutation importance and its interpretation](https://scikit-learn.org/stable/modules/permutation_importance.html).
