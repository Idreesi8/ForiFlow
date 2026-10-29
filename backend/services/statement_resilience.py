"""Transparent principal-only cash-flow scenarios from recorded statement months.

This is a historical replay and a sensitivity calculation, not a default model,
DSCR, repayment forecast, affordability decision or offer. It leaves scoring,
credit policy and officer authority unchanged.
"""
from __future__ import annotations

import math
import statistics
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any

from services.statement_service import StatementSummary

METHOD_VERSION = 'principal-stress-v1'
DECLINES = (0, 10, 20, 30)


def assess_statement_resilience(
    summary: StatementSummary, loan_amount_pkr: float, tenure_months: int
) -> dict[str, Any]:
    """Replay each recorded month under explicit, fixed-outflow inflow shocks.

    Counts compare unrounded amounts, including the exact principal/tenure
    quotient. Display amounts round to paisa using ROUND_HALF_UP. Quiet months
    remain in the denominator. No missing repayment costs are guessed.
    """
    if not math.isfinite(loan_amount_pkr) or loan_amount_pkr <= 0:
        raise ValueError('Facility amount must be finite and positive.')
    if type(tenure_months) is not int or tenure_months <= 0:
        raise ValueError('Tenure must be a positive whole number.')
    if not summary.months:
        raise ValueError('At least one recorded month is required.')

    # All finite IEEE float inputs, even malformed exports with very large
    # amounts, fit this precision without decimal quantization failures.
    with localcontext() as context:
        context.prec = 400
        principal = Decimal(str(loan_amount_pkr)) / Decimal(tenure_months)

        def money(value: Decimal) -> float:
            rounded = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return float(rounded) if rounded else 0.0

        scenarios = []
        for decline in DECLINES:
            factor = Decimal(100 - decline) / Decimal(100)
            remaining = [
                Decimal(str(month.inflow)) * factor
                - Decimal(str(month.outflow)) - principal
                for month in summary.months
            ]
            scenarios.append({
                'inflow_decline_percent': decline,
                'months_covering_principal': sum(value >= 0 for value in remaining),
                'months_observed': len(remaining),
                'median_remainder_pkr': money(statistics.median(remaining)),
                'lowest_remainder_pkr': money(min(remaining)),
            })

        return {
            'method_version': METHOD_VERSION,
            'loan_amount_pkr': loan_amount_pkr,
            'tenure_months': tenure_months,
            'monthly_principal_pkr': money(principal),
            'scenarios': scenarios,
            'assumptions': [
                'New principal is facility amount divided by tenure. Interest and fees are excluded.',
                'Each recorded month is replayed with inflows reduced and outflows held constant.',
                'Statement receipts are not verified sales. Existing debt payments and owner transfers may be included.',
                'Historical scenarios are not forecasts or an approval; an officer must verify complete cash flows and actual repayment terms.',
            ],
        }
