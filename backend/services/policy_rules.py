"""Pure credit-policy rules: how a score becomes a band and a recommendation.

Nothing here touches the database or the model. The model produces a score;
these functions read it against cut-offs that a policy supplies. The cut-offs
below are the **demo policy** defaults. They are convenient round numbers, not
values validated for Pakistani SME lending, and they were not tuned on any
dataset. A lender sets its own through a policy version (``credit_policies``).
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas import Decision, RiskBand

# Demo policy: 0-40 decline, 41-70 manual review, 71-100 approve.
DEMO_DECLINE_MAX_SCORE: float = 40.0
DEMO_MANUAL_REVIEW_MAX_SCORE: float = 70.0
DEMO_MANAGER_APPROVAL_LIMIT_PKR: float = 2_000_000.0
DEMO_POLICY_VERSION: str = "1.0"
DEMO_POLICY_NAME: str = "Demo Credit Policy"

# The fixed cut-offs in the code before release 2.0, when no policy version was
# recorded. Used only to describe applications scored then, never to score.
LEGACY_DECLINE_MAX_SCORE: float = 40.0
LEGACY_MANUAL_REVIEW_MAX_SCORE: float = 70.0


@dataclass(frozen=True, slots=True)
class ScoreBands:
    """The two cut-offs that split the 0-100 score into three bands.

    A score at or below ``decline_max_score`` is high risk; above it and at or
    below ``manual_review_max_score`` is medium risk; above that is low risk.
    """

    decline_max_score: float = DEMO_DECLINE_MAX_SCORE
    manual_review_max_score: float = DEMO_MANUAL_REVIEW_MAX_SCORE

    def __post_init__(self) -> None:
        if not 0.0 <= self.decline_max_score < self.manual_review_max_score <= 100.0:
            raise ValueError(
                "Score bands need 0 <= decline_max_score < manual_review_max_score <= 100."
            )


DEMO_BANDS = ScoreBands()


def recommendation_for(risk_score: float, bands: ScoreBands = DEMO_BANDS) -> Decision:
    """The policy's recommendation for a score, in the stored vocabulary.

    ``Decision`` predates the policy layer and its values read like outcomes
    ("Approved"). Here they are recommendations only: nothing is approved or
    rejected until an authorised officer records a decision.
    """
    if risk_score <= bands.decline_max_score:
        return Decision.REJECTED
    if risk_score <= bands.manual_review_max_score:
        return Decision.MANUAL_REVIEW
    return Decision.APPROVED


def risk_band_for(risk_score: float, bands: ScoreBands = DEMO_BANDS) -> RiskBand:
    """The risk band a score falls in under ``bands``."""
    if risk_score <= bands.decline_max_score:
        return RiskBand.HIGH
    if risk_score <= bands.manual_review_max_score:
        return RiskBand.MEDIUM
    return RiskBand.LOW


def triggered_rule(risk_score: float, bands: ScoreBands = DEMO_BANDS) -> dict:
    """Which threshold rule the score met, as structured data."""
    if risk_score <= bands.decline_max_score:
        return {
            "rule": "score_at_or_below_decline_max",
            "threshold": bands.decline_max_score,
            "comparison": "<=",
            "risk_score": risk_score,
        }
    if risk_score <= bands.manual_review_max_score:
        return {
            "rule": "score_at_or_below_manual_review_max",
            "threshold": bands.manual_review_max_score,
            "comparison": "<=",
            "risk_score": risk_score,
        }
    return {
        "rule": "score_above_manual_review_max",
        "threshold": bands.manual_review_max_score,
        "comparison": ">",
        "risk_score": risk_score,
    }


def approval_authority(
    *,
    loan_amount_pkr: float,
    recommendation: Decision,
    manager_approval_limit_pkr: float,
    decline_override_admin_only: bool,
    escalated: bool,
) -> tuple[str, str]:
    """The lowest role that may approve, and the rule that sets it.

    Returns ``(role, reason)`` with ``role`` ``'manager'`` or ``'admin'``. This
    is the single rule behind both what the API reports and what it enforces.
    Rejecting never needs more than a manager.
    """
    if escalated:
        return "admin", "escalated"
    if recommendation is Decision.REJECTED and decline_override_admin_only:
        return "admin", "approval_against_decline_recommendation"
    if loan_amount_pkr > manager_approval_limit_pkr:
        return "admin", "above_manager_limit"
    return "manager", "within_manager_limit"


def histogram_buckets(bands: ScoreBands) -> list[tuple[str, float, float, RiskBand]]:
    """Six score bars, two inside each band, with edges on the policy cut-offs.

    Each bar is ``(label, lower, upper, band)`` covering scores in
    ``(lower, upper]`` (0 belongs to the first). Because the edges sit on the
    cut-offs, no bar mixes two recommendations. For the demo policy (40 / 70)
    this gives the bars the dashboard has always shown: 0-20, 20-40, 40-55,
    55-70, 70-85, 85-100.
    """
    low, high = bands.decline_max_score, bands.manual_review_max_score
    edges = [0.0, low / 2, low, (low + high) / 2, high, (high + 100.0) / 2, 100.0]
    labels = [RiskBand.HIGH, RiskBand.HIGH, RiskBand.MEDIUM, RiskBand.MEDIUM, RiskBand.LOW, RiskBand.LOW]
    return [
        (f"{edges[i]:g}-{edges[i + 1]:g}", edges[i], edges[i + 1], labels[i])
        for i in range(6)
    ]
