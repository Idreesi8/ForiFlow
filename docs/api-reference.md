# ForiFlow API reference

Base URL in Docker and local Vite: `http://localhost:3000/api` (nginx / Vite
strip `/api` before FastAPI). Direct access: `http://localhost:8000`.

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs).

All amounts are PKR. Timestamps are UTC ISO-8601.

## Authentication and roles

`GET /`, `GET /health`, `POST /auth/login` and the interactive docs are public.
Every other route needs `Authorization: Bearer <token>`; a missing, expired or
invalid token returns `401`.

Two roles exist. The role is read from the `users` table on every request, not
from the token, so changing a user's role takes effect immediately.

| Action | `analyst` | `admin` |
| --- | --- | --- |
| Score, explain, list applications | yes | yes |
| Record EWS observations, read alerts and history | yes | yes |
| Take an EWS alert for review | yes | yes |
| Approve or reject a Manual Review application | no (`403`) | yes |
| Resolve an EWS alert | no (`403`) | yes |
| List or create officer accounts | no (`403`) | yes |

The API refuses to sign tokens while `JWT_SECRET_KEY` is empty, shorter than 32
characters, or still the `.env.example` placeholder (login returns `500` and
the startup log names the problem).

### POST `/auth/login`

```json
{ "username": "officer.two", "password": "…" }
```

**Response `200`**: `access_token`, `token_type` (`bearer`), `expires_in`
(28800 seconds), `username`, `role`. Wrong credentials return `401`.

### GET `/auth/me`

The signed-in account: `id`, `username`, `role`, `created_at`.

### GET `/auth/users` (admin)

All officer accounts, oldest first. Password hashes are never returned.

### POST `/auth/users` (admin)

```json
{ "username": "officer.two", "password": "at-least-12-chars", "role": "analyst" }
```

`role` defaults to `analyst`. Usernames are 3–64 characters of letters, digits,
`.`, `_` or `-`. Passwords are 12–72 characters and may not be the
`.env.example` placeholder (`422`). An existing username returns `409`.
**Response `201`**: the new account, as in `GET /auth/me`.

## GET `/`

Service metadata.

**Response `200`**

```json
{
  "service": "ForiFlow API",
  "version": "1.4.0",
  "docs": "/docs",
  "endpoints": ["/auth/login", "/score", "/score/applications", "/score/stats",
                "/explain/{application_id}", "/ews/monitor", "/ews/alerts"]
}
```

## GET `/health`

Liveness and database connectivity. The dashboard polls this every 60 seconds.

**Response `200`**

```json
{
  "status": "ok",
  "service": "ForiFlow API",
  "version": "1.4.0",
  "database": "connected"
}
```

## POST `/score`

Score an SME application, persist it, and return the decision plus SHAP
explanation. Policy: 0–40 Rejected, 41–70 Manual Review, 71–100 Approved.

Query: `include_explanation` (default `true`).

**Request**

```json
{
  "applicant_name": "Ayesha Siddiqui",
  "business_name": "Siddiqui Textiles (Faisalabad)",
  "loan_amount_pkr": 2500000,
  "tenure_months": 24,
  "monthly_digital_payments": 1450000,
  "payment_history_score": 78,
  "inventory_turnover": 6.5,
  "order_consistency": 82,
  "existing_debt_pkr": 900000,
  "cash_flow_proxy": 410000,
  "years_in_operation": 7,
  "num_employees": 18
}
```

**Response `201`** (a real response from the served model, trained 25 September 2026)

```json
{
  "application_id": 1,
  "applicant_name": "Ayesha Siddiqui",
  "business_name": "Siddiqui Textiles (Faisalabad)",
  "loan_amount_pkr": 2500000.0,
  "tenure_months": 24,
  "monthly_installment_pkr": 104166.67,
  "risk_score": 67.23,
  "decision": "Manual Review",
  "risk_band": "Medium Risk",
  "confidence": 43.7,
  "probability_of_default": 0.0913,
  "model_version": "ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26",
  "explanation": {
    "application_id": 1,
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "risk_score": 67.23,
    "decision": "Manual Review",
    "risk_band": "Medium Risk",
    "base_value": 47.2,
    "feature_contributions": [
      {
        "feature": "loan_to_income",
        "label": "Facility size vs annual turnover",
        "value": 0.1437,
        "contribution": 10.77,
        "direction": "increases",
        "weight": 0.5377
      },
      {
        "feature": "years_in_operation",
        "label": "Years in operation",
        "value": 7.0,
        "contribution": 5.08,
        "direction": "increases",
        "weight": 0.2536
      },
      {
        "feature": "payment_history_score",
        "label": "Repayment history (officer-entered)",
        "value": 78.0,
        "contribution": 4.18,
        "direction": "increases",
        "weight": 0.2087
      }
    ],
    "top_positive_factors": [
      "Facility size vs annual turnover",
      "Years in operation",
      "Repayment history (officer-entered)"
    ],
    "top_negative_factors": [],
    "narrative": "Score 67.2/100 (Medium Risk) resulted in a 'Manual Review' outcome. Supporting factors: facility size vs annual turnover (+10.8), years in operation (+5.1), repayment history (officer-entered) (+4.2). Referred to a credit officer for manual verification of cash flow evidence.",
    "compliance_note": "SHAP values are stored on-premise so a bank can support an SBP-oriented adverse-action file. Payment-history and bureau-balance fields are officer-entered; there is no live ECIB or other bureau connector. All amounts are in PKR. ForiFlow is not SBP-certified. Scored by the trained XGBoost + RandomForest ensemble (credit_risk_shared dataset, 5-fold CV 0.7752 ± 0.0073, hold-out 0.7731 (n=32,581, 3 features, trained on a public/proxy dataset — not a real SME portfolio) with TreeSHAP attributions. Payment history is read as a clean (above 52.5) or adverse (52.5 and below) record, not as a fine scale. Collected but not used by this model version: Business size (employees), Existing debt burden, Installment affordability vs cash flow, Inventory turnover, Order consistency.",
    "model_version": "ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26"
  },
  "created_at": "2026-09-25T10:47:02.821460+05:00",
  "scored_by": "officer.two"
}
```

**Errors:** `422` on field-range violations (see `SMEApplicant` in
`backend/schemas.py`).

## GET `/score/applications`

List scored applications, newest first.

Query: `decision` (the model's band: `Rejected` | `Manual Review` | `Approved`),
`final_decision` (the decision that stands: `Approved` | `Rejected`, i.e. the
model's band or the officer's call on a Manual Review case), `pending_review`
(`true`: Manual Review cases still awaiting an officer decision; `false`: every
other row), `limit` (1–200, default 50), `offset`.

**Response `200`**

```json
[
  {
    "id": 1,
    "applicant_name": "Ayesha Siddiqui",
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "loan_amount_pkr": 2500000.0,
    "tenure_months": 24,
    "risk_score": 67.23,
    "decision": "Manual Review",
    "created_at": "2026-09-25T10:47:02.821460+05:00",
    "scored_by": "officer.two",
    "review_decision": null,
    "review_note": null,
    "reviewed_by": null,
    "reviewed_at": null,
    "final_decision": null
  }
]
```

`decision` is always the model's band. `final_decision` is the decision that
stands: the model's band for Approved and Rejected, the officer's
`review_decision` for a reviewed Manual Review case, and `null` while that
review is pending. `scored_by` is `null` for rows scored before migration
`0003_officer_decisions` (version 1.3.0).

## GET `/score/stats`

Portfolio totals for the dashboard, computed in SQL over every application and
alert (not limited by paging).

**Response `200`**

```json
{
  "total_applications": 5,
  "model_decisions": {"Rejected": 1, "Manual Review": 3, "Approved": 1},
  "pending_review": 1,
  "final_approved": 2,
  "final_rejected": 2,
  "approval_rate": 40.0,
  "approved_exposure_pkr": 3600000.0,
  "average_score": 51.28,
  "score_histogram": [
    {"label": "0-20", "lower": 0.0, "upper": 20.0, "count": 1},
    {"label": "20-40", "lower": 20.0, "upper": 40.0, "count": 0},
    {"label": "40-55", "lower": 40.0, "upper": 55.0, "count": 0},
    {"label": "55-70", "lower": 55.0, "upper": 70.0, "count": 3},
    {"label": "70-85", "lower": 70.0, "upper": 85.0, "count": 1},
    {"label": "85-100", "lower": 85.0, "upper": 100.0, "count": 0}
  ],
  "open_alerts": 1,
  "worst_open_drop": 26.0
}
```

(Trained model: the `STRONG`, `WEAK` and three `MID` applicants from
`backend/tests/conftest.py`, one Manual Review case approved, one rejected, and
one Late 60–89 month on the Approved one.) Histogram bars cover (lower, upper], with 0 in the first bar, so every score
is counted once; the edges 40 and 70 are the policy boundaries.

`GET /score/applications/{id}` returns one row or `404`.

## POST `/score/applications/{id}/review` (admin)

Record the final decision on a Manual Review application, with the reason.

```json
{ "decision": "Approved", "note": "Five years of clean POS receipts; facility is 28% of turnover." }
```

`decision` is `Approved` or `Rejected`; `note` is 10–1000 characters.
**Response `200`**: the application, as in `GET /score/applications/{id}`,
with `review_decision`, `review_note`, `reviewed_by` and `reviewed_at` set.

**Errors:** `404` unknown id; `409` if the model's band is Approved or
Rejected (only Manual Review needs an officer decision) or if a decision is
already recorded (it cannot be changed); `403` for analysts; `422` for a
missing or short note.

## POST `/explain/{application_id}`

Rebuild or return the stored SHAP explanation for a scored application.

Query: `refresh` (default `false`) — recompute from the current engine. The
explanation stored at scoring time is the audit record, so a refresh returns
the recomputed explanation without overwriting it (it is only written when
none is stored).

**Response `200`** — same body as `ScoreResponse.explanation` above.

**Errors:** `404` if the application id does not exist.

`GET /explain/{application_id}` is the read-only twin.

## POST `/ews/monitor`

Record one month of post-disbursement surveillance. Triggers an alert when the
monthly score drops more than 15 points from the originating application.

**Request**

```json
{
  "borrower_id": 1,
  "month_number": 4,
  "installment_status": "Late 30-59",
  "bureau_balance": 1650000,
  "pos_cash_balance": 240000,
  "data_source_primary": "ECIB"
}
```

`installment_status`: `On Time`, `Late 1-29`, `Late 30-59`, `Late 60-89`,
`Default`. `data_source_primary`: `ECIB`, `POS`, `Bank Statement`,
`Self Reported`.

`borrower_id` is an application id. An unknown id returns `404`. Only an
approved application became a facility, so only it can be monitored: Approved
by the model, or Manual Review and then approved by an officer. Anything else
returns `409`: a model Rejected application, a Manual Review case still
awaiting its decision, or one an officer rejected. `month_number` cannot be
past the facility's `tenure_months` (`422`).

The alert follows the latest month on file. A new latest month that drops more
than 15 points opens an alert, or updates the open one. Back-filling an older
month never changes the alert (the response says so in `recommended_action`).
If the latest month is corrected and no longer breaches, the open alert is
closed with an automatic note. The example below assumes application 1 was
approved first.

**Response `201`**

```json
{
  "borrower_id": 1,
  "business_name": "Siddiqui Textiles (Faisalabad)",
  "month_number": 4,
  "baseline_score": 67.23,
  "current_score": 47.01,
  "score_drop": 20.22,
  "alert_triggered": true,
  "alert_threshold": 15.0,
  "estimated_days_to_default": 74,
  "recommended_action": "Relationship manager to contact the borrower within 7 days and verify POS settlement trends.",
  "tracking": {
    "id": 1,
    "borrower_id": 1,
    "month_number": 4,
    "installment_status": "Late 30-59",
    "bureau_balance": 1650000.0,
    "pos_cash_balance": 240000.0,
    "monthly_score": 47.01,
    "data_source_primary": "ECIB"
  },
  "alert": {
    "id": 1,
    "borrower_id": 1,
    "baseline_score": 67.23,
    "current_score": 47.01,
    "score_drop": 20.22,
    "estimated_days_to_default": 74,
    "alert_status": "Active",
    "triggered_at": "2026-09-25T10:47:16.580236+05:00",
    "resolved_at": null,
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "assigned_to": null,
    "resolved_by": null,
    "resolution_note": null
  }
}
```

**Errors:** `404` if `borrower_id` is not a scored application; `409` if it is
not an approved facility; `422` for a month past the tenure or out-of-range
fields.

## GET `/ews/alerts`

Officer alert queue.

Query: `alert_status` (`Active` | `In Review` | `Resolved`), `limit`, `offset`.

**Response `200`**

```json
[
  {
    "id": 1,
    "borrower_id": 1,
    "baseline_score": 67.23,
    "current_score": 47.01,
    "score_drop": 20.22,
    "estimated_days_to_default": 74,
    "alert_status": "Active",
    "triggered_at": "2026-09-25T10:47:16.580236+05:00",
    "resolved_at": null,
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "assigned_to": null,
    "resolved_by": null,
    "resolution_note": null
  }
]
```

Related: `GET /ews/borrowers/{id}/history`.

## PATCH `/ews/alerts/{id}/review`

Any officer takes an open alert for review: `alert_status` becomes
`In Review` and `assigned_to` records who. `404` unknown id, `409` if the
alert is already resolved or is being reviewed by another officer.

## PATCH `/ews/alerts/{id}/resolve` (admin)

```json
{ "note": "Borrower paid the arrears on 12 Oct." }
```

Closes an Active or In Review alert, recording `resolved_at`, `resolved_by`
and `resolution_note` (5–1000 characters). `404` unknown id, `409` if already
resolved, `403` for analysts, `422` without a note.

## GET `/model/evaluation`

Hold-out evaluation of the served model, recorded by `python -m
ml.evaluate_model`. Any signed-in officer. `404` if the script has not run.

Returns `rows`, `default_rate`, `protocol`, the isotonic `calibrator`
breakpoints, and under `holdout`: `raw` and `calibrated` (AUC-ROC, Brier,
expected calibration error, mean prediction), `brier_no_skill`, `roc_curve`,
`confusion_at_half`, `thresholds` (score 30 to 70), `bands` (observed default
rate and calibrated PD per policy band), `reliability_raw` and
`reliability_calibrated`. These describe the public training file, not the
live portfolio.

## GET `/model/comparison`

The alternatives benchmark recorded by `python -m ml.compare_models`: per model
the cross-validated AUC-ROC, PR-AUC, F1, Brier, single-row latency, and a
paired t-test against the served ensemble. Any signed-in officer.
