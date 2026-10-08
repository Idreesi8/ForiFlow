"""Early Warning System (EWS): the monthly monitored score and the runway heuristic.

Each approved facility is re-assessed monthly from officer-entered repayment
behaviour, an officer-typed bureau balance and POS settlement inflows (no live
bureau connector). :meth:`EWSService.derive_monthly_score` turns a month into
the monitored score: the origination score minus fixed rule penalties.

Whether a facility is NORMAL, WATCH, WARNING or CRITICAL, and whether an alert
is raised, is decided by :mod:`services.ews_engine` from the facility's whole
recorded history, not here.

The fitted Markov chain (``ml.ews_markov``) is reported for reference only.
Until 2.0 it could raise an alert on its own (three-month default probability
at or above :data:`MODEL_ALERT_PROBABILITY`). The fitted probabilities cross
that line exactly for Late 60-89 and Default, which the engine already treats
as CRITICAL, so the chain added no alert the rules miss; and it was fitted on
consumer card histories, not SME loans. Since 2.1 it plays no part in alerts.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from schemas import EWSObservationFields, InstallmentStatus
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

# How each officer-entered ageing bucket maps onto the fitted Markov chain
# (ml.ews_markov). The UCI file the chain is fitted on does not separate one
# and two missed payments before its last month, so the two lightest buckets
# share a state.
STATUS_TO_CHAIN_STATE: dict[InstallmentStatus, str] = {
    InstallmentStatus.ON_TIME: "Current",
    InstallmentStatus.LATE_1_29: "Late 1-59",
    InstallmentStatus.LATE_30_59: "Late 1-59",
    InstallmentStatus.LATE_60_89: "Late 60-89",
    InstallmentStatus.DEFAULT: "Default",
}

# The chain's alert line until 2.0, kept to document (and test) that the
# statuses it flagged are exactly the ones the rules mark CRITICAL. Not used.
MODEL_ALERT_PROBABILITY: float = 0.10


@dataclass(frozen=True, slots=True)
class MonitoringOutcome:
    """Result of evaluating one borrower-month of surveillance data."""

    baseline_score: float
    current_score: float
    score_drop: float
    # The score-drop rule alone (drop above the threshold). The alert itself is
    # decided by services.ews_engine from the whole history.
    alert_triggered: bool
    estimated_days_to_default: int
    recommended_action: str
    # Reference only, from the Markov chain; None when no fitted chain is loaded.
    default_probability_3m: float | None = None
    runway_basis: str = "rules"
    # What the rules give for the month, whether or not an officer overrode it.
    rule_score: float = 0.0
    score_overridden: bool = False


class EWSService:
    """The monthly monitored score and the runway heuristic.

    Injected into the EWS router via :func:`get_ews_service`.
    """

    def __init__(
        self,
        alert_threshold: float = ALERT_SCORE_DROP_THRESHOLD,
        chain: dict | None = None,
    ) -> None:
        """Store the score-drop threshold and, if given, the fitted Markov chain.

        ``chain`` is the content of ``ml/ews_transition.json``. Without it the
        service keeps the rule-based runway and reports no probability.
        """
        if alert_threshold <= 0:
            raise ValueError("The alert threshold must be a positive number of points.")
        self.alert_threshold = alert_threshold
        self.outlook: dict[str, dict] = {
            row["state"]: row for row in (chain or {}).get("state_outlook", [])
        }

    def chain_outlook(self, installment_status: InstallmentStatus) -> dict | None:
        """The fitted chain's outlook for a facility in this ageing bucket."""
        return self.outlook.get(STATUS_TO_CHAIN_STATE[installment_status])

    def derive_monthly_score(
        self,
        baseline_score: float,
        payload: EWSObservationFields,
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
        # before an officer updates the typed bureau balance.
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

    def runway(self, installment_status: InstallmentStatus, score_drop: float) -> tuple[int, str]:
        """The heuristic runway for a month: the chain's if loaded, else the rule's.

        Shown with an alert for compatibility; it does not raise or rank alerts.
        """
        outlook = self.chain_outlook(installment_status)
        if outlook is not None and outlook.get("expected_days_to_default") is not None:
            return int(outlook["expected_days_to_default"]), "markov"
        return self.estimate_days_to_default(score_drop, installment_status), "rules"

    def recommended_action(
        self,
        alert_triggered: bool,
        score_drop: float,
        installment_status: InstallmentStatus,
    ) -> str:
        """Return the next best action for the relationship manager."""
        if installment_status is InstallmentStatus.DEFAULT:
            return (
                "Hand over to remedial management immediately. Classification "
                "under SBP Prudential Regulations is the bank's process — "
                "ForiFlow does not classify or certify."
            )
        if not alert_triggered:
            return "No action required. Continue routine monthly monitoring."
        if score_drop >= 2 * self.alert_threshold:
            return (
                "Escalate to the recovery unit within 48 hours, obtain an updated "
                "bureau extract (ForiFlow has no live ECIB feed), and consider "
                "restructuring the facility."
            )
        return (
            "Relationship manager to contact the borrower within 7 days and verify "
            "POS settlement trends."
        )

    def evaluate(
        self,
        baseline_score: float,
        payload: EWSObservationFields,
        original_loan_amount_pkr: float,
        expected_monthly_cash_flow: float,
    ) -> MonitoringOutcome:
        """The month's monitored score, its drop from baseline and the runway heuristic.

        An officer override (``payload.current_score``) replaces the rule score;
        the rule score is still returned so the record shows what it replaced.
        """
        rule_score = self.derive_monthly_score(
            baseline_score=baseline_score,
            payload=payload,
            original_loan_amount_pkr=original_loan_amount_pkr,
            expected_monthly_cash_flow=expected_monthly_cash_flow,
        )
        overridden = payload.current_score is not None
        current_score = payload.current_score if overridden else rule_score
        score_drop = round(baseline_score - current_score, 2)
        alert_triggered = score_drop > self.alert_threshold

        # Reference only: the chain's outlook for this ageing bucket. It does
        # not change alert_triggered (see the module docstring).
        outlook = self.chain_outlook(payload.installment_status)
        probability = days = None
        if outlook is not None:
            probability = round(float(outlook["default_within_3_months"]), 4)
            days = outlook["expected_days_to_default"]

        return MonitoringOutcome(
            baseline_score=round(baseline_score, 2),
            current_score=round(current_score, 2),
            score_drop=score_drop,
            alert_triggered=alert_triggered,
            estimated_days_to_default=(
                int(days)
                if days is not None
                else self.estimate_days_to_default(score_drop, payload.installment_status)
            ),
            recommended_action=self.recommended_action(
                alert_triggered, score_drop, payload.installment_status
            ),
            default_probability_3m=probability,
            runway_basis="markov" if days is not None else "rules",
            rule_score=rule_score,
            score_overridden=overridden,
        )


@lru_cache(maxsize=1)
def get_ews_service() -> EWSService:
    """FastAPI dependency returning the shared EWS engine, with the fitted chain."""
    from ml.features import load_ews_transition

    return EWSService(chain=load_ews_transition())
