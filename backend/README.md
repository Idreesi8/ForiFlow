# ForiFlow Backend

FastAPI service powering **ForiFlow** — alternative-data SME credit scoring and an
Early Warning System (EWS) for Pakistani banks. All amounts are in PKR, bureau
features reference **ECIB**, and decisions are explainable for **SBP**
fair-lending and adverse-action reporting.

## Quick start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows (use: source .venv/bin/activate on Linux/macOS)
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs
- Health probe: http://localhost:8000/health
- CORS is pre-configured for the React dashboard on `http://localhost:3000`.

Run the tests from the same directory:

```bash
pytest
```

## Configuration

| Variable                  | Default                  | Purpose                     |
| ------------------------- | ------------------------ | --------------------------- |
| `FORIFLOW_DATABASE_URL`   | `sqlite:///./foriflow.db` | SQLAlchemy connection URL   |
| `FORIFLOW_LOG_LEVEL`      | `INFO`                   | Root log level              |

Tables are created automatically on startup.

## Endpoints

| Method  | Path                                 | Purpose                                        |
| ------- | ------------------------------------ | ---------------------------------------------- |
| `POST`  | `/score`                             | Score an SME application and persist it        |
| `GET`   | `/score/applications`                | List scored applications (filter by decision)  |
| `GET`   | `/score/applications/{id}`           | Fetch one application                          |
| `POST`  | `/explain/{application_id}`          | Generate the SHAP explanation                  |
| `GET`   | `/explain/{application_id}`          | Read the stored explanation                    |
| `POST`  | `/ews/monitor`                       | Record a monitored month, alert on score drops |
| `GET`   | `/ews/alerts`                        | List alerts, worst first                       |
| `GET`   | `/ews/borrowers/{id}/history`        | Monthly score trend for one borrower           |
| `PATCH` | `/ews/alerts/{id}/resolve`           | Resolve an alert                               |

### Decision policy

The score runs from 0 (worst) to 100 (best):

| Score range | Decision      | Risk band   |
| ----------- | ------------- | ----------- |
| 0 – 40      | Rejected      | High Risk   |
| 41 – 70     | Manual Review | Medium Risk |
| 71 – 100    | Approved      | Low Risk    |

### EWS alerting

The origination score is the borrower's baseline. Each monitored month is
re-scored from the repayment ageing bucket, the ECIB bureau balance and POS
settlement inflows. A drop of **more than 15 points** raises an alert with an
estimated runway to default. An unresolved alert is updated in place rather than
duplicated, and re-submitting a month (e.g. after a late bureau refresh)
overwrites that observation.

## Layout

```
backend/
  main.py                     # app factory, CORS, lifespan, health
  schemas.py                  # Pydantic request/response models + enums
  models/database.py          # engine, session, Application / Alert / EWSTracking
  routers/score.py            # POST /score and application queries
  routers/explain.py          # SHAP-style explanations
  routers/ews.py              # monitoring, alerts, borrower history
  services/scoring_service.py # scoring + explainability logic (ML + surrogate)
  services/ews_service.py     # monitoring, alert and runway logic
  ml/features.py              # canonical feature schema shared by train + serve
  ml/train_real_model.py      # training pipeline -> model, scaler, SHAP, metadata
  ml/predict_sample.py        # single-applicant smoke test
  ml/shap_utils.py            # SHAP output normalisation helpers
  ml/data/                    # raw CSV training data (not committed)
  tests/                      # pytest suite (in-memory SQLite)
```

## Model

### Training

```bash
python -m ml.train_real_model                          # full run, ~20 min
python -m ml.train_real_model --dataset credit_risk_shared   # retrain only, ~2 min
python -m ml.predict_sample                            # score one applicant
```

`--dataset` skips the candidate comparison for routine retrains and carries the
previously recorded comparison into the new metadata for traceability.

The pipeline explores both CSVs, maps them onto the ForiFlow feature space,
compares candidate training sets by 5-fold cross-validation, then fits a
`StandardScaler` → `SMOTE` → soft-voting `XGBoost + RandomForest` ensemble on the
winner. SMOTE runs **inside** each CV fold (via an `imblearn` pipeline) so
synthetic minority rows never leak into a validation fold. It writes:

| Artefact                 | Contents                                            |
| ------------------------ | --------------------------------------------------- |
| `ml/foriflow_model.pkl`  | Fitted soft-voting ensemble                          |
| `ml/scaler.pkl`          | `StandardScaler` fitted on the training split        |
| `ml/shap_explainer.pkl`  | One TreeExplainer per member, plus voting weights    |
| `ml/feature_names.json`  | Feature order, learned clip bounds, metrics, lineage |

### Which dataset was used, and why

The two files do not carry the same columns: `credit_risk_dataset.csv` has no
tenure and no existing-debt measure. Merging on the union would leave those
columns wholly imputed for 32k rows, letting the model recover *which dataset a
row came from* and exploit the gap between their default rates (22% vs 12%). The
combined candidate is therefore restricted to the true column intersection, and
each option has to win on cross-validated AUC:

| Candidate            | Features | Rows    | AUC-ROC | F1    |
| -------------------- | -------- | ------- | ------- | ----- |
| `credit_risk_shared` | 3        | 32,581  | 0.774   | 0.550 |
| `combined_shared`    | 3        | 287,928 | 0.652   | 0.299 |
| `loan_default_full`  | 6        | 255,347 | 0.622   | 0.237 |

`credit_risk_dataset.csv` wins decisively despite being the smallest.
`Loan_default.csv` is largely synthetic — `CreditScore`, `DTIRatio` and
`MonthsEmployed` are near-uniform and every categorical level sits within a
10-13% default rate — so adding its 255k rows dilutes real signal rather than
adding to it.

### Feature engineering decisions

- **Currency invariance.** The datasets are in USD and ForiFlow underwrites in
  PKR, so exposure is expressed as ratios against the applicant's own income
  (`loan_to_income`) rather than absolute amounts. No FX assumption is needed and
  PKR inputs land inside the trained distribution.
- **The income denominator is gross turnover, not net cash flow.** In the training
  data a loan above 30% of gross annual income is already deep in the tail — the
  default rate jumps from 22% in the 0.2-0.3 band to 67% in 0.3-0.4. An SME
  borrowing half its annual *net* cash flow is unremarkable, so using net cash
  flow as the denominator pushed ordinary applicants into that tail: a healthy
  Faisalabad textile SME scored 18/100 and was rejected. Turnover is estimated
  from monthly digital receipts, floored at net cash flow for cash-heavy
  businesses, which also lets ForiFlow's flagship alternative-data signal reach
  the model. The same applicant now scores 68.
- **Learned clip bounds.** Training persists each feature's 1st/99th percentile
  and serving clips to those saved bounds, keeping live applicants inside the
  range the trees were split on.
- **Age is excluded** even though both datasets carry it and it is predictive:
  the intake form never collects it, so training on it would force a fabricated
  constant at inference.
- **Payment history is a clean/adverse signal only.** `payment_history_score` is
  bridged from `cb_person_default_on_file` alone (37.8% default with a prior
  default on file, 18.4% without). Credit history *length* is available but
  excluded: within clean records, default risk is flat across it (20.0% at two
  years versus 16-18% at fifteen, correlation −0.018). An earlier version folded
  it in, and the model could only fit it as noise — it charged an applicant with
  an excellent ECIB record 22 points, which is indefensible in an adverse-action
  letter. Dropping it *improved* hold-out AUC from 0.766 to 0.776. The cost is
  granularity: ECIB scores either side of the midpoint read as clean or adverse
  rather than on a fine scale.
- **Monotone constraints on the boosted member.** Larger facilities, heavier debt
  burdens and weaker repayment records can only ever be shown as increasing risk.
  Random forests cannot take these constraints, which is part of why the forest
  carries the smaller voting weight; a small local non-monotonicity survives from
  it (a business trading two years can score ~3 points below one trading six
  months, all else equal).
- **Categorical columns are reported, not served.** The exploration step prints
  ordinal codes and per-level default rates for every categorical column, but
  home ownership, education, employment type and loan purpose are dropped because
  the ForiFlow form cannot supply them.

### Accuracy, and an important limitation

5-fold cross-validation gives **AUC-ROC 0.776 ± 0.008** and **F1 0.540**; the
held-out 20% scores AUC 0.776, F1 0.544, Brier 0.175. Hold-out applicants spread
across the policy bands at roughly 20% Rejected, 42% Manual Review and 39%
Approved, so the bands remain meaningful rather than approving everyone.

The winning dataset only supports **three** features — `loan_to_income`,
`payment_history_score` and `years_in_operation`. Loan amount, cash flow and
digital receipts all feed the first of those, but four intake concepts have no
counterpart in either public dataset and therefore **do not move the ML score**:
inventory turnover, order consistency, employee count and existing debt burden.
Requested tenure only enters through installment affordability, which is likewise
absent, so tenure does not affect the score either. Every explanation states this
in its `compliance_note`, and the fields are still persisted for policy rules and
audit. Closing the gap needs SME data carrying those signals, or a blended score
that keeps the surrogate's policy weighting for the unmodelled fields.

Because the ensemble is trained on SMOTE-balanced data, its probabilities are
calibrated to a 50% prior rather than the portfolio's true default rate. The
score is therefore a **relative creditworthiness ranking** on a 0-100 scale, not
an absolute default probability — which is also what keeps the SHAP base value
near 50 and spreads applicants across the policy bands.

### Serving

`get_scoring_service()` returns `MLScoringService` when the artefacts are present
and falls back to the linear surrogate otherwise, so the API still boots on a
fresh checkout. Set `FORIFLOW_SCORING_ENGINE` to `ml`, `surrogate` or `auto`
(default) to override; `ml` fails loudly rather than falling back.

`MLScoringService` subclasses `ScoringService`, so routers keep one dependency
type and inherit the decision policy and narrative builder. It adds:

- `risk_score = 100 * (1 - PD)` from the ensemble;
- `confidence` (0-100), combining agreement between the two members with the
  score's distance from the nearest policy boundary — a decision-stability
  indicator, not a statistical confidence interval;
- real TreeSHAP contributions in **probability space**, so each value converts
  directly into score points and `base_value + Σ contributions` reproduces the
  score exactly (verified at training time and in `tests/test_ml_model.py`).

Explaining probabilities requires interventional TreeSHAP with a background
sample. Note that XGBoost ≥ 3.0 enables categorical support by default, which
makes `shap` refuse interventional explainers even with no categorical splits;
the trainer sets `enable_categorical=False` for this reason.

Scoring one applicant takes about 230 ms, dominated by interventional TreeSHAP
over the forest's ~70k leaves. Three things keep it there: a 50-row SHAP
background, forcing `n_jobs=1` on the loaded members (parallel dispatch cost more
than it saved for single-row inference — 183 ms versus a few milliseconds), and
averaging the member probabilities directly instead of making a third pass over
the trees. Model loading (~1 s warm, tens of seconds on a cold import cache)
happens during app startup rather than on the first request.

The surrogate remains the fallback: a deterministic additive model whose exact
SHAP values follow analytically, with `base_value` 50 for a neutral applicant.
The API test suite pins it via a dependency override so that decision-policy
tests assert fixed arithmetic; the trained ensemble has its own contract tests.

Services are wired into the routers with FastAPI dependency injection
(`get_scoring_service`, `get_ews_service`, `get_db`), so tests and alternative
implementations can substitute their own instances.
