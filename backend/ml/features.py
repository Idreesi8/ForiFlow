"""Canonical ML feature schema shared by training and serving.

Both ``train_real_model.py`` and ``services.scoring_service`` import this module,
so a feature can never be built one way at training time and another way at
inference time.

Design notes
------------
**Currency invariance.** The public datasets are denominated in USD while
ForiFlow underwrites in PKR, so absolute amounts would place live applicants far
outside the training distribution. Every feature is therefore a ratio against
the applicant's own income, a 0-100 score, or a duration. No FX assumption is
needed anywhere in the pipeline.

**The income denominator is gross turnover, not net cash flow.** The training
column ``person_income`` is *gross annual income*, and in that data a loan worth
more than 30% of income is already deep in the tail: the default rate jumps from
22% in the 0.2-0.3 band to 67% in the 0.3-0.4 band. An SME borrowing half its
annual *net* cash flow is unremarkable, so dividing by net cash flow would push
ordinary applicants into that tail and reject them. The correct analogue of gross
personal income is the business's gross annual receipts, estimated from monthly
digital receipts and floored at net cash flow (which can never exceed turnover)
for cash-heavy businesses. This is also what lets ForiFlow's flagship
alternative-data signal, digital payment volume, reach the model at all.

**Debt is converted from a stock to a service ratio.** ``Loan_default.csv``
supplies ``DTIRatio``, a monthly debt-service-to-income ratio, whereas ForiFlow
collects ``existing_debt_pkr``, an outstanding balance. Dividing the balance by
:data:`ASSUMED_DEBT_AMORTISATION_MONTHS` puts both on the same footing; without
this the live values would sit an order of magnitude above every trained split.

**Age is deliberately excluded.** Both source datasets carry it and it is
predictive, but the ForiFlow intake form never collects it, so training on it
would force a fabricated constant at inference and turn a real signal into a
fixed bias.

**Clip bounds are learned, not guessed.** Training persists the 1st/99th
percentile of each feature and serving applies those saved bounds, which keeps
live applicants inside the range the trees were actually split on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"

MODEL_PATH = ML_DIR / "foriflow_model.pkl"
SCALER_PATH = ML_DIR / "scaler.pkl"
SHAP_EXPLAINER_PATH = ML_DIR / "shap_explainer.pkl"
FEATURE_NAMES_PATH = ML_DIR / "feature_names.json"

# Full set of features this module knows how to build. The subset actually used
# by the trained model is recorded in ``feature_names.json``, because the winning
# dataset determines which features are genuinely available.
FEATURE_NAMES: list[str] = [
    "loan_to_income",
    "installment_to_income",
    "debt_service_to_income",
    "payment_history_score",
    "years_in_operation",
    "tenure_months",
]

# Credit-officer friendly names used when rendering SHAP contributions.
FEATURE_LABELS: dict[str, str] = {
    "loan_to_income": "Facility size vs annual turnover",
    "installment_to_income": "Installment affordability vs turnover",
    "debt_service_to_income": "Existing debt burden",
    "payment_history_score": "Repayment history (ECIB)",
    "years_in_operation": "Years in operation",
    "tenure_months": "Requested tenure",
}

# Assumed remaining amortisation on an applicant's existing borrowings, used to
# convert an outstanding balance into a monthly debt service figure.
ASSUMED_DEBT_AMORTISATION_MONTHS: float = 36.0

# Substituted when an applicant reports neither digital receipts nor cash flow, so
# a division by zero becomes a worst-case ratio rather than an error. Clipping
# pulls it back to the worst value actually seen in training.
NO_CASH_FLOW_RATIO: float = 999.0


class SMEApplicantLike(Protocol):
    """The applicant attributes needed to build a feature vector."""

    loan_amount_pkr: float
    tenure_months: int
    monthly_digital_payments: float
    payment_history_score: float
    existing_debt_pkr: float
    cash_flow_proxy: float
    years_in_operation: float


def monthly_turnover_proxy(applicant: SMEApplicantLike) -> float:
    """Estimate gross monthly receipts, the analogue of gross personal income.

    Digital receipts are the primary estimate. Net cash flow acts as a floor
    because turnover can never be lower than net cash flow, which keeps
    cash-heavy businesses with little digital footprint from looking as though
    they have almost no income.
    """
    return max(float(applicant.monthly_digital_payments), float(applicant.cash_flow_proxy))


def build_raw_features(applicant: SMEApplicantLike) -> dict[str, float]:
    """Map a ForiFlow applicant onto the model's feature space, unclipped."""
    monthly_turnover = monthly_turnover_proxy(applicant)
    annual_turnover = monthly_turnover * 12.0
    tenure = max(int(applicant.tenure_months), 1)
    installment = float(applicant.loan_amount_pkr) / tenure
    monthly_debt_service = (
        float(applicant.existing_debt_pkr) / ASSUMED_DEBT_AMORTISATION_MONTHS
    )

    if monthly_turnover > 0:
        loan_to_income = float(applicant.loan_amount_pkr) / annual_turnover
        installment_to_income = installment / monthly_turnover
        debt_service_to_income = monthly_debt_service / monthly_turnover
    else:
        loan_to_income = NO_CASH_FLOW_RATIO
        installment_to_income = NO_CASH_FLOW_RATIO
        debt_service_to_income = NO_CASH_FLOW_RATIO

    return {
        "loan_to_income": loan_to_income,
        "installment_to_income": installment_to_income,
        "debt_service_to_income": debt_service_to_income,
        "payment_history_score": float(applicant.payment_history_score),
        "years_in_operation": float(applicant.years_in_operation),
        "tenure_months": float(tenure),
    }


def apply_clips(
    features: dict[str, float], clips: dict[str, list[float] | tuple[float, float]]
) -> dict[str, float]:
    """Clamp each feature into the range learned during training."""
    clipped: dict[str, float] = {}
    for name, value in features.items():
        bounds = clips.get(name)
        if bounds is None:
            clipped[name] = float(value)
            continue
        lower, upper = float(bounds[0]), float(bounds[1])
        clipped[name] = max(lower, min(upper, float(value)))
    return clipped


def load_feature_metadata() -> dict:
    """Read the served feature order and their learned clip bounds."""
    with FEATURE_NAMES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def artifacts_available() -> bool:
    """True when every artefact needed for ML scoring is on disk."""
    return all(
        path.exists()
        for path in (MODEL_PATH, SCALER_PATH, SHAP_EXPLAINER_PATH, FEATURE_NAMES_PATH)
    )
