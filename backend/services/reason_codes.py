"""Reason codes: the largest risk factors of an assessment, as stable codes.

This is a thin, deterministic layer over the SHAP explanation; it does not
replace it and adds no judgement of its own. The rule:

1. Take the explanation's feature contributions (score points).
2. Keep those that lowered the score by at least :data:`MIN_POINTS`.
3. Order them largest first and keep the top :data:`MAX_CODES`.
4. Give each the code fixed for its feature below.

A code exists only for a feature an explanation can actually contain: the
inputs of the trained ensemble (``ml.features.FEATURE_NAMES``) and of the
fallback formula. A feature with no entry here gets no code; nothing is
invented for it.
"""

from __future__ import annotations

from schemas import ReasonCode, ShapFeatureContribution

# Contributions smaller than this many score points are not worth a code.
MIN_POINTS: float = 0.5
MAX_CODES: int = 3

# feature key -> (code, meaning). Codes are never reused or renumbered.
REASON_CODES: dict[str, tuple[str, str]] = {
    # Inputs of the trained ensemble.
    "loan_to_income": ("R01", "Facility is large against annual turnover"),
    "payment_history_score": ("R02", "Adverse repayment history"),
    "years_in_operation": ("R03", "Short trading history"),
    "installment_to_income": ("R04", "Installment is high against turnover"),
    "debt_service_to_income": ("R05", "High existing debt burden"),
    "tenure_months": ("R06", "Requested tenure adds risk"),
    # Inputs only the fallback formula reads.
    "loan_affordability": ("R04", "Installment is high against cash flow"),
    "debt_burden": ("R05", "High existing debt burden"),
    "monthly_digital_payments": ("R07", "Low digital payment volume"),
    "order_consistency": ("R08", "Irregular order volumes"),
    "inventory_turnover": ("R09", "Slow inventory turnover"),
    "num_employees": ("R10", "Very small business"),
}


def reason_codes_for(contributions: list[ShapFeatureContribution]) -> list[ReasonCode]:
    """The top risk factors of an explanation, coded. See the module rule."""
    adverse = sorted(
        (item for item in contributions if item.contribution <= -MIN_POINTS),
        key=lambda item: (item.contribution, item.feature),
    )
    codes: list[ReasonCode] = []
    for item in adverse:
        entry = REASON_CODES.get(item.feature)
        if entry is None:
            continue
        codes.append(
            ReasonCode(
                code=entry[0], label=entry[1], feature=item.feature, points=item.contribution
            )
        )
        if len(codes) == MAX_CODES:
            break
    return codes
