"""Which application fields reach the score, and which do not.

Three groups, kept apart so the dashboard never implies that a field moves a
score it does not move:

A. **Model features**: what the serving model reads, and the intake fields
   each one is built from.
B. **Collected but unused**: intake fields the form records that the serving
   model does not read. Kept for the credit file and for future versions.
C. **Future SME features**: data a Pakistani SME model would need from a data
   partner. Not collected and not used today; listed so the gap is explicit.

For the trained ensemble the contract follows ``feature_names.json``. For the
hand-weighted fallback formula every scoring field is used.
"""

from __future__ import annotations

from typing import Any

# The intake fields that can carry a score. Identity and reporting fields
# (names, CNIC/NTN, phone, sector) are never model inputs.
SCORING_INTAKE_FIELDS: dict[str, str] = {
    "loan_amount_pkr": "Loan amount",
    "tenure_months": "Tenure (months)",
    "monthly_digital_payments": "Monthly digital payments",
    "payment_history_score": "Payment history score",
    "inventory_turnover": "Inventory turnover",
    "order_consistency": "Order consistency",
    "existing_debt_pkr": "Existing debt",
    "cash_flow_proxy": "Monthly cash flow proxy",
    "years_in_operation": "Years in operation",
    "num_employees": "Employees",
}

IDENTITY_AND_REPORTING_FIELDS: list[str] = [
    "applicant_name",
    "business_name",
    "business_sector",
    "contact_phone",
    "identifier (CNIC / NTN)",
]

# How ml.features.build_raw_features builds each model feature.
MODEL_FEATURE_SOURCES: dict[str, dict[str, Any]] = {
    "loan_to_income": {
        "label": "Facility size vs annual turnover",
        "intake_fields": ["loan_amount_pkr", "monthly_digital_payments", "cash_flow_proxy"],
        "formula": "loan amount / (12 x max(monthly digital payments, monthly cash flow))",
    },
    "installment_to_income": {
        "label": "Installment affordability vs turnover",
        "intake_fields": ["loan_amount_pkr", "tenure_months", "monthly_digital_payments", "cash_flow_proxy"],
        "formula": "(loan amount / tenure) / max(monthly digital payments, monthly cash flow)",
    },
    "debt_service_to_income": {
        "label": "Existing debt burden",
        "intake_fields": ["existing_debt_pkr", "monthly_digital_payments", "cash_flow_proxy"],
        "formula": "(existing debt / 36) / max(monthly digital payments, monthly cash flow)",
    },
    "payment_history_score": {
        "label": "Repayment history (officer-entered)",
        "intake_fields": ["payment_history_score"],
        "formula": "read as clean (above the midpoint of the two trained levels) or adverse",
    },
    "years_in_operation": {
        "label": "Years in operation",
        "intake_fields": ["years_in_operation"],
        "formula": "as entered, clipped to the training range",
    },
    "tenure_months": {
        "label": "Requested tenure",
        "intake_fields": ["tenure_months"],
        "formula": "as entered",
    },
}

# What a Pakistani SME model would need. Data requirements, not model inputs.
FUTURE_SME_FEATURES: list[dict[str, str]] = [
    {"name": "Bank statement cash flows", "why": "Verified monthly inflows and outflows instead of a typed proxy"},
    {"name": "Bureau (ECIB) report", "why": "Real repayment history, enquiries and existing exposures"},
    {"name": "Facility history with the lender", "why": "Prior limits, utilisation, restructurings and arrears"},
    {"name": "Existing obligations schedule", "why": "Actual instalments due, not a balance divided by an assumed term"},
    {"name": "Business sector and location", "why": "Sector and regional risk, once outcomes exist to learn from"},
    {"name": "Outcome label", "why": "Whether each SME facility defaulted (e.g. 90+ days past due) within a fixed window"},
]


def contract(scorer: Any) -> dict:
    """The feature contract of the engine that is scoring now."""
    engine = getattr(scorer, "engine", "surrogate")
    if engine == "ml":
        features = list(getattr(scorer, "feature_names", []))
        model_features = [
            {
                "name": name,
                **MODEL_FEATURE_SOURCES.get(
                    name, {"label": name, "intake_fields": [], "formula": "unknown"}
                ),
            }
            for name in features
        ]
        used = {field for feature in model_features for field in feature["intake_fields"]}
        basis = (
            "The trained ensemble reads only these features (feature_names.json). "
            "Every other intake field is recorded but does not change the score."
        )
    else:
        model_features = [
            {
                "name": name,
                "label": label,
                "intake_fields": [name],
                "formula": "hand-weighted fallback formula",
            }
            for name, label in SCORING_INTAKE_FIELDS.items()
        ]
        used = set(SCORING_INTAKE_FIELDS)
        basis = (
            "The fallback formula is serving: it reads every scoring field, with "
            "hand-set weights that were not fitted to data."
        )
    unused = [
        {"name": name, "label": label}
        for name, label in SCORING_INTAKE_FIELDS.items()
        if name not in used
    ]
    return {
        "engine": engine,
        "model_version": getattr(scorer, "model_version", None),
        "basis": basis,
        "model_features": model_features,
        "used_intake_fields": sorted(used),
        "collected_unused": unused,
        "identity_and_reporting_fields": IDENTITY_AND_REPORTING_FIELDS,
        "future_sme_features": FUTURE_SME_FEATURES,
        "future_note": (
            "Data requirements for a future Pakistani SME model. None of these is "
            "collected or used by the current model."
        ),
    }
