"""Early Warning System (EWS) business logic for ForiFlow.

Each disbursed facility is re-assessed monthly using repayment behaviour, the
ECIB bureau balance and POS settlement inflows. When the borrower's score falls
more than :data:`ALERT_SCORE_DROP_THRESHOLD` points below its origination
baseline, an alert is raised together with an estimated runway to default so
that the recovery team can prioritise outreach.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from schemas import EWSMonitorRequest, InstallmentStatus
from services.scoring_service import clamp

ALERT_SCORE_DROP_THRESHOLD: float = 15.0

# Score points deducted from the baseline for each repayment ageing bucket.
# Calibrated so that a 60-89 day delinquency alone breaches the alert threshold.
INSTALLMENT_PENALTIES: dict[InstallmentStatus, float] = {
    InstallmentStatus.ON_TIME: 0.0,
    InstallmentStatus.LATE_1_29: 6.0,
    InstallmentStatus.LATE_30_59: 14.0,
    InstallmentStatus.LATE_60_89: 26.0,
    InstallmentStatus.DEFAULT: 45.0,
}

# Expected days to default per ageing bucket, before score-drop adjustment.
BASE_RUNWAY_DAYS: dict[InstallmentStatus, int] = {
    InstallmentStatus.ON_TIME: 180,
    InstallmentStatus.LATE_1_29: 150,
    InstallmentStatus.LATE_30_59: 90,
    InstallmentStatus.LATE_60_89: 45,
    InstallmentStatus.DEFAULT: 0,
}

MIN_RUNWAY_DAYS: int = 7
MAX_RUNWAY_DAYS: int = 365


@dataclass(frozen=True, slots=True)
class MonitoringOutcome:
    """Result of evaluating one borrower-month of surveillance data."""

    baseline_score: float
    current_score: float
    score_drop: float
    alert_triggered: bool
    estimated_days_to_default: int
    recommended_action: str


class EWSService:
    """Monthly monitoring, alert triggering and runway estimation.

    Injected into the EWS router via :func:`get_ews_service` so the threshold
    can be tuned per portfolio without touching the endpoint.
    """

    def __init__(self, alert_threshold: float = ALERT_SCORE_DROP_THRESHOLD) -> None:
        """Store the score-drop threshold, in score points, that raises an alert."""
        if alert_threshold <= 0:
            raise ValueError("The alert threshold must be a positive number of points.")
        self.alert_threshold = alert_threshold

    def derive_monthly_score(
        self,
        baseline_score: float,
        payload: EWSMonitorRequest,
        original_loan_amount_pkr: float,
        expected_monthly_cash_flow: float,
    ) -> float:
        """Recompute the borrower's score from this month's observations.

        Three signals move the score away from its baseline:

        * repayment ageing bucket (dominant, see :data:`INSTALLMENT_PENALTIES`);
        * bureau leverage, i.e. how much of the original facility is still
          outstanding relative to the amortisation schedule;
        * POS cash coverage, i.e. current settlement inflow versus the cash flow
          underwritten at origination.
        """
        penalty = INSTALLMENT_PENALTIES[payload.installment_status]

        # Straight-line amortisation expectation: after `month_number` months a
        # performing borrower should have paid down a proportional share. Bureau
        # balances above that path signal refinancing or fresh borrowing.
        if original_loan_amount_pkr > 0:
            leverage = payload.bureau_balance / original_loan_amount_pkr
            penalty += clamp(leverage - 1.0, 0.0, 1.0) * 12.0

        # Shrinking POS inflows are an early liquidity signal, often visible
        # before the bureau refresh lands.
        if expected_monthly_cash_flow > 0:
            coverage = payload.pos_cash_balance / expected_monthly_cash_flow
            penalty += clamp(1.0 - coverage, 0.0, 1.0) * 15.0

        return round(clamp(baseline_score - penalty, 0.0, 100.0), 2)

    def estimate_days_to_default(
        self, score_drop: float, installment_status: InstallmentStatus
    ) -> int:
        """Estimate the runway before the facility is expected to default.

        Starts from the ageing bucket's base runway and shortens it in
        proportion to how fast the score is deteriorating.
        """
        if installment_status is InstallmentStatus.DEFAULT:
            return 0

        base_days = BASE_RUNWAY_DAYS[installment_status]
        # Every point of deterioration beyond the alert threshold removes three
        # days of runway.
        excess_drop = max(score_drop - self.alert_threshold, 0.0)
        estimated = base_days - int(round(excess_drop * 3.0))
        return int(clamp(float(estimated), float(MIN_RUNWAY_DAYS), float(MAX_RUNWAY_DAYS)))

    def recommended_action(
        self,
        alert_triggered: bool,
        score_drop: float,
        installment_status: InstallmentStatus,
    ) -> str:
        """Return the next best action for the relationship manager."""
        if installment_status is InstallmentStatus.DEFAULT:
            return (
                "Classify per SBP Prudential Regulations and hand over to remedial "
                "management immediately."
            )
        if not alert_triggered:
            return "No action required. Continue routine monthly monitoring."
        if score_drop >= 2 * self.alert_threshold:
            return (
                "Escalate to the recovery unit within 48 hours, request an ECIB refresh "
                "and consider restructuring the facility."
            )
        return (
            "Relationship manager to contact the borrower within 7 days and verify "
            "POS settlement trends."
        )

    def evaluate(
        self,
        baseline_score: float,
        payload: EWSMonitorRequest,
        original_loan_amount_pkr: float,
        expected_monthly_cash_flow: float,
    ) -> MonitoringOutcome:
        """Evaluate one borrower-month and decide whether to raise an alert."""
        current_score = (
            payload.current_score
            if payload.current_score is not None
            else self.derive_monthly_score(
                baseline_score=baseline_score,
                payload=payload,
                original_loan_amount_pkr=original_loan_amount_pkr,
                expected_monthly_cash_flow=expected_monthly_cash_flow,
            )
        )
        score_drop = round(baseline_score - current_score, 2)
        alert_triggered = score_drop > self.alert_threshold

        return MonitoringOutcome(
            baseline_score=round(baseline_score, 2),
            current_score=round(current_score, 2),
            score_drop=score_drop,
            alert_triggered=alert_triggered,
            estimated_days_to_default=self.estimate_days_to_default(
                score_drop, payload.installment_status
            ),
            recommended_action=self.recommended_action(
                alert_triggered, score_drop, payload.installment_status
            ),
        )


@lru_cache(maxsize=1)
def get_ews_service() -> EWSService:
    """FastAPI dependency returning the shared EWS engine."""
    return EWSService()
