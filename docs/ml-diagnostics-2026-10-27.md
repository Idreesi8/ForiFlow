# Trained input-anomaly model and saved-case ML diagnostics

27 October 2026. Frontend and backend implementation, training evidence and
verification records: `archive/ml-diagnostics-2026-10-27/`.

## Delivered behaviour

The saved-assessment review now includes **Model checks & what-if**, loaded
only when the officer selects **Inspect model behaviour**. It shows an
additional trained input-anomaly result, actual XGBoost / random forest
disagreement, input transformations and 25 model sensitivity scenarios. The
Model Performance page exposes the new model's purpose, training facts,
descriptive validation flag rate and reference fingerprint.

These are read-only analyses computed now, not retrospectively stored evidence
from the original assessment. The recorded loan, score, policy snapshot and
officer decision remain authoritative. No schema migration, credit assessment,
credit decision or monitoring write is needed to use the new panel.

## Actual training and its limits

The new estimator is scikit-learn **IsolationForest**, 128 trees, 256 samples
per tree, seed 42 and one inference/training worker. It was fitted in the
existing pinned Linux runtime, offline with no database access, on **19,449
original training rows**. No SMOTE rows or outcomes were used. Original
training-split medians fill missing inputs; loan ratio and years are not clipped
for this detector. Repayment history retains the original binary encoding,
25 adverse / 80 clean.

The trainer checks the original public CSV's SHA-256 and the identities of
all three retained splits. It reads training and validation feature values;
final-test row identities are matched only. Final-test features/outcomes are
not used to train, select, tune or evaluate this addition. No existing credit
artefact or recorded evaluation file was rewritten.

Anomaly score is negative `score_samples`, so higher means more unusual. The
flag threshold is fixed at the **95th percentile of training anomaly scores**,
not Isolation Forest's default prediction cutoff. Empirical percentiles count
training scores less than or equal to the case score, including ties.

| Recorded fact | Value |
| --- | --- |
| Training timestamp UTC | 2026-10-26T19:34:55.370732+00:00 |
| Training rows | 19,449 |
| Validation rows | 6,483 |
| Training flags | 973 |
| Validation flags | 314 (4.84%) |
| Anomaly-score threshold | 0.6120657018602961 |
| scikit-learn runtime | 1.8.0 |
| Model file SHA-256 | `e138b87e72890944abd9d124ac10db8f3bac0f7b868a7ea00f16750e5a366b91` |
| Model + manifest reference SHA-256 | `89d87a271d10a846ee4d9ea4cf98dce3a8cea60521d3ecd2cfc889fc2f3c2612` |
| Public CSV SHA-256 | `ce3c6d2167717bf1627d1c0c81cbccd28323cd4aa7b96d542599366d5ff6aac8` |

**4.84% is a descriptive flag rate, not detection accuracy.** No labelled
anomaly evaluation or validation on Pakistani SME outcomes has been performed.
Being typical relative to public consumer inputs does not establish suitability
for an SME loan. A flag is neither default probability nor evidence of fraud
or a data error. Isolation Forest identifies unusual inputs; the method and
score direction are documented in the
[official estimator reference](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html).
Learning preprocessing and thresholds from training rows follows the
[scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage).

The original three-feature XGBoost / random forest credit model is unchanged.
Its retained consumer-data final-test AUROC remains **0.7748**, with no claim
of improved underwriting accuracy. Its serving artefact fingerprint remains
`15a24f14f148b513bddf75c5eafb55f873af8d57f42988970fc51247686ff43d`.
Real SME validation still requires lender data and repayment outcomes described
in [the SME data requirements](sme_data_requirements.md).

## Provenance and failure behaviour

Authenticated `GET /model/applicability` returns public summary facts, excluding
the internal training-score array. The locally trusted estimator file is hashed
before deserialization. Serving verifies the model/manifest pair, credit
fingerprint and version, dataset/split identities, feature order, imputation,
runtime version and finite reference statistics. A second reference fingerprint
binds **both** model bytes and manifest bytes; it differs from the model-file
SHA-256 above.

Authenticated `GET /model/applications/{id}/diagnostics` requires an ML-assessed
case, its retained model-version row and an exact match to the serving credit
artefacts. It also recomputes the recorded score before returning diagnostics.
Unverifiable historical cases, surrogate assessments, invalid inputs and score
mismatches receive explicit unavailable results with no invented scenarios.

An unavailable anomaly reference yields a partial result when the ensemble
source and baseline can still be verified. It does not silently replace the
credit engine. Missing retained policy cutoffs produce model scores without
recommendations; today's policy is never substituted. HTTP errors, a mismatched
case ID or late cancelled responses cannot replace the current case's display.

## Interpretation of the interactive scenarios

Five loan factors and five receipts factors, each 80%, 90%, 100%, 110%, 120%,
produce 25 actual batch predictions from the same trained ensemble. Both
monthly digital receipts and the cash-flow proxy scale together. All other
recorded fields remain fixed. The existing mapper still uses their maximum as
its turnover proxy; zero stays zero. Credit clipping and binary history
encoding are identical to the verified baseline.

Selecting scenarios in the browser uses the returned predictions locally, with
no extra inference request or write. The panel labels exact hypothetical
amounts, score changes and any retained-policy recommendation change. It states
that these are model responses, not causal forecasts, facility offers or
officer decisions. Decision confirmation continues to use the **recorded**
loan amount after exploring a different scenario.

Learner spread is the absolute difference between the two raw default
probabilities, in percentage points. It is not a confidence interval, accuracy
measure or calibrated SME default rate. Clipping warnings distinguish numerical
training boundaries from the deliberate two-level repayment-history encoding.

## Verification

- Native backend: **338 passed**, including 32 new tests covering source binding,
  actual ensemble/scenario reproduction, train-only thresholding, role access,
  corrupt references, finite inputs, policy retention and all-table preservation
  with SELECT-only diagnostics.
- Production Linux image: **336 passed, 2 skipped**. The two existing CSV-based
  protocol checks skip because the raw training file is excluded from the
  serving image; they passed natively with the file present.
- Frontend: **53 passed**; production build completed.
- New synthetic browser coverage: **18 passed**, using snapshots generated by
  the real ML service in an isolated in-memory database. This covers all 25
  predictions, policy-boundary changes, unusual/clipped inputs, partial and
  unavailable states, stale-response cancellation, reason preservation,
  recorded-amount confirmation and 390-pixel mobile layouts. No write requests,
  missing fixture routes or browser exceptions were observed.
- Existing browser regression coverage: **119 passed** across assessment,
  Action Desk, monitoring, register search, navigation, unsaved work, Pakistan
  dates and credit confirmation. The dashboard lazy-route assertion needed a
  30-second loading allowance under concurrent release work; its assertions
  were retained and the complete suite passed on rerun.
- Live account: **9 checks passed**. The deployed model summary, source
  fingerprint, mobile model card, stored explanation read and ML readiness
  were verified. All eight existing case responses had identical before/after
  content fingerprints. Only verification login/logout requests wrote anything.

**Live historical-data limitation:** all eight pre-existing assessments use
older August/September credit versions and have no retained model-version
foreign key. The live API correctly withholds their new-model diagnostics and
the UI displays that reason. No historical case was relinked or rescored.
The complete current-model scenario flow was verified with real-ML synthetic
cases in isolated test databases, including the production Linux image; no
new assessment was created in the live database. Newly assessed cases retain
their exact model link through the existing scoring path and can use the new
diagnostics when that model is serving.

The reference/scenario interface screenshots use synthetic cases. Element
captures hide the sticky workspace header and skip link only during capture
so those unrelated overlays do not obscure the inspected panel.

## Deployment and preservation

A fresh 52,946-byte backup was restored to a scratch database before deployment;
all ten table fingerprints and the append-only audit protection were verified.
Backup: `backups/foriflow-20261027-004537-6a22510d149746cc82d6e4b331376bbb.dump`,
SHA-256 `DC26B15D1121F51DCB19D617AFD8A4466C98449E03CC3307E1268470CE71201A`.

Backend and frontend were replaced independently after image verification.
The database image remains
`sha256:557fea37a744d5f4c8faab304b0a90858b53ab119735a88c131fd19dab802f36`.
New backend: `sha256:44d184a997bfb4dee3e437d78c8f02214b57d72c6b07d09b622f9da15e2a2bf1`.
New frontend: `sha256:a999352f1c0a534de87a2188e02738045395f2b2fd5fc0b4b1f330d7b419be90`.
Both application services and the retained database passed their health checks.
Before live-account verification, all ten database table contents matched the
verified pre-update backup exactly, including eight applications, four
observations, four alerts and both existing model-version rows.
Live-account verification subsequently generated normal authentication audit
and token-revocation records; it left all saved application contents unchanged.
Rollback images are retained as
`foriflow-backend:before-ml-diagnostics-20261027-005451` and
`foriflow-frontend:before-ml-diagnostics-20261027-005451`.

Detailed post-deployment content comparisons, regression logs and live-account
verification are retained alongside the training manifest in the evidence
folder. Passwords, bearer tokens and customer screenshots are not included.
