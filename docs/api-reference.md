# ForiFlow API reference

Base URL in Docker and local Vite: `http://localhost:3000/api` (nginx / Vite
strip `/api` before FastAPI). Direct access: `http://localhost:8000`.

Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs).

All amounts are PKR. Timestamps are UTC ISO-8601.

## GET `/`

Service metadata.

**Response `200`**

```json
{
  "service": "ForiFlow API",
  "version": "1.0.0",
  "docs": "/docs"
}
```

## GET `/health`

Liveness and database connectivity. The dashboard polls this every 60 seconds.

**Response `200`**

```json
{
  "status": "ok",
  "service": "ForiFlow API",
  "version": "1.0.0",
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

**Response `201`**

```json
{
  "application_id": 12,
  "applicant_name": "Ayesha Siddiqui",
  "business_name": "Siddiqui Textiles (Faisalabad)",
  "loan_amount_pkr": 2500000.0,
  "tenure_months": 24,
  "monthly_installment_pkr": 104166.67,
  "risk_score": 79.4,
  "decision": "Approved",
  "risk_band": "Low Risk",
  "confidence": 71.7,
  "model_version": "ensemble-xgb-rf-credit_risk_shared-2026-08-11T23:51:28",
  "explanation": {
    "application_id": 12,
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "risk_score": 79.4,
    "decision": "Approved",
    "risk_band": "Low Risk",
    "base_value": 47.67,
    "feature_contributions": [
      {
        "feature": "loan_to_income",
        "label": "Facility size vs annual turnover",
        "value": 0.13,
        "contribution": 20.44,
        "direction": "increases",
        "weight": 0.42
      }
    ],
    "top_positive_factors": ["Facility size vs annual turnover"],
    "top_negative_factors": [],
    "narrative": "Score 79.4/100 (Low Risk) resulted in a 'Approved' outcome.",
    "compliance_note": "SHAP values are stored on-premise so a bank can support an SBP-oriented adverse-action file. Payment-history and bureau-balance fields are officer-entered; there is no live ECIB connector. ForiFlow is not SBP-certified.",
    "model_version": "ensemble-xgb-rf-credit_risk_shared-2026-08-11T23:51:28"
  },
  "created_at": "2026-08-15T08:12:01.441000Z"
}
```

**Errors:** `422` on field-range violations (see `SMEApplicant` in
`backend/schemas.py`).

## GET `/score/applications`

List scored applications, newest first.

Query: `decision` (`Rejected` | `Manual Review` | `Approved`), `limit` (1–200,
default 50), `offset`.

**Response `200`**

```json
[
  {
    "id": 12,
    "applicant_name": "Ayesha Siddiqui",
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "loan_amount_pkr": 2500000.0,
    "tenure_months": 24,
    "risk_score": 79.4,
    "decision": "Approved",
    "created_at": "2026-08-15T08:12:01.441000Z"
  }
]
```

`GET /score/applications/{id}` returns one row or `404`.

## POST `/explain/{application_id}`

Rebuild or return the stored SHAP explanation for a scored application.

Query: `refresh` (default `false`) — recompute from the current engine.

**Response `200`** — same body as `ScoreResponse.explanation` above.

**Errors:** `404` if the application id does not exist.

`GET /explain/{application_id}` is the read-only twin.

## POST `/ews/monitor`

Record one month of post-disbursement surveillance. Triggers an alert when the
monthly score drops more than 15 points from the originating application.

**Request**

```json
{
  "borrower_id": 12,
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

**Response `201`**

```json
{
  "borrower_id": 12,
  "business_name": "Siddiqui Textiles (Faisalabad)",
  "month_number": 4,
  "baseline_score": 79.4,
  "current_score": 52.1,
  "score_drop": 27.3,
  "alert_triggered": true,
  "alert_threshold": 15.0,
  "estimated_days_to_default": 48,
  "recommended_action": "Call the relationship manager and request updated POS settlements.",
  "tracking": {
    "id": 3,
    "borrower_id": 12,
    "month_number": 4,
    "installment_status": "Late 30-59",
    "bureau_balance": 1650000.0,
    "pos_cash_balance": 240000.0,
    "monthly_score": 52.1,
    "data_source_primary": "ECIB"
  },
  "alert": {
    "id": 1,
    "borrower_id": 12,
    "baseline_score": 79.4,
    "current_score": 52.1,
    "score_drop": 27.3,
    "estimated_days_to_default": 48,
    "alert_status": "Active",
    "triggered_at": "2026-08-15T08:20:11.002000Z",
    "resolved_at": null
  }
}
```

**Errors:** `404` if `borrower_id` is not a scored application.

## GET `/ews/alerts`

Officer alert queue.

Query: `alert_status` (`Active` | `In Review` | `Resolved`), `limit`, `offset`.

**Response `200`**

```json
[
  {
    "id": 1,
    "borrower_id": 12,
    "baseline_score": 79.4,
    "current_score": 52.1,
    "score_drop": 27.3,
    "estimated_days_to_default": 48,
    "alert_status": "Active",
    "triggered_at": "2026-08-15T08:20:11.002000Z",
    "resolved_at": null
  }
]
```

Related: `GET /ews/borrowers/{id}/history` and
`PATCH /ews/alerts/{id}/resolve`.
