"""Unit tests for the scoring engine and its SHAP-style explanations."""

from __future__ import annotations

import pytest

from schemas import Decision, RiskBand, SMEApplicant
from services.scoring_service import (
    FEATURE_WEIGHTS,
    MANUAL_REVIEW_UPPER_BOUND,
    REJECT_UPPER_BOUND,
    ScoringService,
    get_scoring_service,
)
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

pytestmark = pytest.mark.scoring


@pytest.fixture(name="service")
def service_fixture() -> ScoringService:
    """Return a scoring service with the production weight vector."""
    return ScoringService()


def test_feature_weights_sum_to_one() -> None:
    """The published weight vector must be a proper convex combination."""
    assert sum(FEATURE_WEIGHTS.values()) == pytest.approx(1.0)


def test_get_scoring_service_is_cached() -> None:
    """Dependency injection must reuse the same stateless instance."""
    assert get_scoring_service() is get_scoring_service()


@pytest.mark.parametrize(
    ("payload", "expected_decision", "expected_band"),
    [
        (STRONG_APPLICANT, Decision.APPROVED, RiskBand.LOW),
        (MID_APPLICANT, Decision.MANUAL_REVIEW, RiskBand.MEDIUM),
        (WEAK_APPLICANT, Decision.REJECTED, RiskBand.HIGH),
    ],
)
def test_score_maps_applicants_to_expected_bands(
    service: ScoringService,
    payload: dict[str, object],
    expected_decision: Decision,
    expected_band: RiskBand,
) -> None:
    """Reference applicants must land in their intended policy bands."""
    result = service.score(SMEApplicant(**payload))

    assert 0.0 <= result.risk_score <= 100.0
    assert result.decision is expected_decision
    assert result.risk_band is expected_band


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, Decision.REJECTED),
        (REJECT_UPPER_BOUND, Decision.REJECTED),
        (REJECT_UPPER_BOUND + 0.01, Decision.MANUAL_REVIEW),
        (MANUAL_REVIEW_UPPER_BOUND, Decision.MANUAL_REVIEW),
        (MANUAL_REVIEW_UPPER_BOUND + 0.01, Decision.APPROVED),
        (100.0, Decision.APPROVED),
    ],
)
def test_decision_policy_boundaries(score: float, expected: Decision) -> None:
    """0-40 Rejected, 41-70 Manual Review, 71-100 Approved."""
    assert ScoringService.decision_for(score) is expected


def test_score_is_deterministic(service: ScoringService) -> None:
    """The same payload must always produce the same score."""
    applicant = SMEApplicant(**MID_APPLICANT)
    assert service.score(applicant).risk_score == service.score(applicant).risk_score


def test_better_payment_history_never_lowers_the_score(service: ScoringService) -> None:
    """The model must stay monotonic in repayment behaviour."""
    weaker = SMEApplicant(**{**MID_APPLICANT, "payment_history_score": 40})
    stronger = SMEApplicant(**{**MID_APPLICANT, "payment_history_score": 95})

    assert service.score(stronger).risk_score > service.score(weaker).risk_score


def test_higher_existing_debt_lowers_the_score(service: ScoringService) -> None:
    """Additional leverage must be penalised."""
    lighter = SMEApplicant(**{**MID_APPLICANT, "existing_debt_pkr": 100_000})
    heavier = SMEApplicant(**{**MID_APPLICANT, "existing_debt_pkr": 5_000_000})

    assert service.score(heavier).risk_score < service.score(lighter).risk_score


def test_zero_cash_flow_zeroes_affordability_features(service: ScoringService) -> None:
    """Without verifiable cash flow, affordability and debt capacity score 0."""
    result = service.score(SMEApplicant(**{**MID_APPLICANT, "cash_flow_proxy": 0}))

    assert result.normalised_features["loan_affordability"] == 0.0
    assert result.normalised_features["debt_burden"] == 0.0
    assert result.decision is not Decision.APPROVED


def test_normalised_features_stay_within_unit_interval(service: ScoringService) -> None:
    """Every normalised feature must remain inside [0, 1] even at the extremes."""
    extreme = SMEApplicant(
        **{
            **STRONG_APPLICANT,
            "monthly_digital_payments": 900_000_000,
            "inventory_turnover": 50,
            "years_in_operation": 100,
            "num_employees": 5_000,
        }
    )
    for name, value in service.score(extreme).normalised_features.items():
        assert 0.0 <= value <= 1.0, name


def test_shap_contributions_are_additive(service: ScoringService) -> None:
    """Contributions plus the base value must reconstruct the score exactly."""
    result = service.score(SMEApplicant(**MID_APPLICANT))
    contributions = service.explain(result)

    total = service.base_value + sum(c.contribution for c in contributions)
    assert total == pytest.approx(result.risk_score, abs=0.5)


def test_shap_contributions_are_sorted_by_absolute_impact(
    service: ScoringService,
) -> None:
    """The waterfall chart relies on descending absolute impact."""
    contributions = service.explain(service.score(SMEApplicant(**WEAK_APPLICANT)))
    impacts = [abs(c.contribution) for c in contributions]

    assert impacts == sorted(impacts, reverse=True)
    assert len(contributions) == len(FEATURE_WEIGHTS)


def test_explanation_directions_match_contribution_signs(
    service: ScoringService,
) -> None:
    """``direction`` must always agree with the sign of the contribution."""
    for contribution in service.explain(service.score(SMEApplicant(**MID_APPLICANT))):
        expected = "increases" if contribution.contribution >= 0 else "decreases"
        assert contribution.direction == expected


def test_build_explanation_returns_narrative_and_factors(
    service: ScoringService,
) -> None:
    """The assembled payload must be ready for the credit file."""
    result = service.score(SMEApplicant(**WEAK_APPLICANT))
    explanation = service.build_explanation(
        result, application_id=7, business_name="Ahmed Auto Spares (Karachi)"
    )

    assert explanation.application_id == 7
    assert explanation.risk_score == result.risk_score
    assert explanation.top_negative_factors
    assert "Rejected" in explanation.narrative
    assert "no live ECIB" in explanation.compliance_note
    assert "not SBP-certified" in explanation.compliance_note


def test_invalid_weight_vectors_are_rejected() -> None:
    """A service cannot be built without usable weights."""
    with pytest.raises(ValueError):
        ScoringService(weights={})
    with pytest.raises(ValueError):
        ScoringService(weights={"payment_history_score": 0.0})
