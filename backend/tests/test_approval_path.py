"""Path to approval: the facility size and turnover that reach the next band."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from schemas import Decision, SMEApplicant
from services.scoring_service import APPROVAL_ROUNDING_PKR
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

# A Manual Review case on the served model: facility is 28% of yearly turnover.
BORDERLINE = {
    **MID_APPLICANT,
    "loan_amount_pkr": 500_000,
    "tenure_months": 12,
    "monthly_digital_payments": 150_000,
    "cash_flow_proxy": 150_000,
    "payment_history_score": 95,
    "years_in_operation": 5,
}


def _decision(ml_service, payload: dict, **changes) -> Decision:
    return ml_service.score(SMEApplicant(**{**payload, **changes})).decision


def _path(ml_service, payload: dict):
    applicant = SMEApplicant(**payload)
    result = ml_service.score(applicant)
    return result, ml_service.approval_path(applicant, result)


def test_surrogate_has_no_path(client: TestClient) -> None:
    body = client.post("/score", json=WEAK_APPLICANT).json()
    assert body["explanation"]["approval_path"] is None


@pytest.mark.ml
def test_an_approved_application_needs_no_path(ml_service) -> None:
    result, path = _path(ml_service, STRONG_APPLICANT)
    if result.decision is not Decision.APPROVED:
        pytest.skip("sample applicant is not approved by this model")
    assert path is None


@pytest.mark.ml
def test_thresholds_are_exact_to_the_rounding_step(ml_service) -> None:
    """At the reported value the target is reached; one step worse it is not."""
    result, path = _path(ml_service, BORDERLINE)
    if result.decision is not Decision.MANUAL_REVIEW:
        pytest.skip("sample applicant is not in Manual Review on this model")

    (step,) = path.steps
    assert step.target_decision is Decision.APPROVED
    assert step.max_loan_pkr < BORDERLINE["loan_amount_pkr"]
    assert step.max_loan_pkr % APPROVAL_ROUNDING_PKR == 0
    assert _decision(ml_service, BORDERLINE, loan_amount_pkr=step.max_loan_pkr) is Decision.APPROVED
    assert (
        _decision(
            ml_service, BORDERLINE, loan_amount_pkr=step.max_loan_pkr + APPROVAL_ROUNDING_PKR
        )
        is not Decision.APPROVED
    )

    turnover = step.required_monthly_turnover_pkr
    assert turnover > BORDERLINE["monthly_digital_payments"]
    assert (
        _decision(ml_service, BORDERLINE, monthly_digital_payments=turnover)
        is Decision.APPROVED
    )
    assert (
        _decision(
            ml_service, BORDERLINE, monthly_digital_payments=turnover - APPROVAL_ROUNDING_PKR
        )
        is not Decision.APPROVED
    )


@pytest.mark.ml
def test_a_rejected_application_gets_both_steps_in_order(ml_service) -> None:
    payload = {**BORDERLINE, "loan_amount_pkr": 900_000}
    result, path = _path(ml_service, payload)
    if result.decision is not Decision.REJECTED:
        pytest.skip("sample applicant is not rejected by this model")

    assert [step.target_decision for step in path.steps] == [
        Decision.MANUAL_REVIEW,
        Decision.APPROVED,
    ]
    review, approval = path.steps
    # Approval is the harder target: a smaller facility, a higher turnover.
    assert approval.max_loan_pkr <= review.max_loan_pkr <= payload["loan_amount_pkr"]
    assert approval.required_monthly_turnover_pkr >= review.required_monthly_turnover_pkr


@pytest.mark.ml
def test_unreachable_steps_name_what_blocks_them(ml_service) -> None:
    payload = {**BORDERLINE, "payment_history_score": 20, "years_in_operation": 0}
    _, path = _path(ml_service, payload)
    approval = path.steps[-1]
    if approval.max_loan_pkr is not None:
        pytest.skip("this model can approve the applicant at some facility size")

    assert approval.required_monthly_turnover_pkr is None
    assert path.blocked_by
    assert "Facility size vs annual turnover" not in path.blocked_by


@pytest.mark.ml
def test_nothing_reachable_is_reported_not_raised(ml_client: TestClient) -> None:
    """When no facility size or turnover reaches a better band, scoring still works.

    Here every search ends on the first pass. That once left the next pass
    with nothing to score, and the whole assessment failed with a 500.
    """
    payload = {
        **BORDERLINE,
        "loan_amount_pkr": 360_000,
        "monthly_digital_payments": 600_000,
        "cash_flow_proxy": 180_000,
        "payment_history_score": 30,
        "years_in_operation": 0.5,
    }
    response = ml_client.post("/score", json=payload)
    assert response.status_code == 201, response.text

    path = response.json()["explanation"]["approval_path"]
    if path is None or any(step["max_loan_pkr"] is not None for step in path["steps"]):
        pytest.skip("this model can move the sample applicant into a better band")
    assert all(step["required_monthly_turnover_pkr"] is None for step in path["steps"])
    assert path["blocked_by"]


@pytest.mark.ml
def test_no_turnover_leaves_only_the_turnover_route(ml_service) -> None:
    payload = {**BORDERLINE, "monthly_digital_payments": 0, "cash_flow_proxy": 0}
    _, path = _path(ml_service, payload)

    assert path.blocked_by[0] == "No documented turnover"
    assert all(step.max_loan_pkr is None for step in path.steps)
    assert path.steps[-1].required_monthly_turnover_pkr is not None


@pytest.mark.ml
def test_the_path_is_stored_with_the_explanation(ml_client: TestClient) -> None:
    scored = ml_client.post("/score", json=BORDERLINE).json()
    if scored["decision"] == "Approved":
        pytest.skip("sample applicant is approved by this model")

    stored = ml_client.post(f"/explain/{scored['application_id']}").json()
    assert stored["approval_path"] == scored["explanation"]["approval_path"]
    assert stored["approval_path"]["requested_loan_pkr"] == BORDERLINE["loan_amount_pkr"]


@pytest.mark.ml
def test_scoring_never_fails_across_the_input_range(ml_service) -> None:
    """Three hundred seeded random applicants, extremes included, all score.

    Each one is scored, explained and searched for a path, and every reported
    threshold is checked to really reach its band.
    """
    import random

    rng = random.Random(2026)
    for _ in range(300):
        turnover = rng.choice([0, 1, 40_000, 150_000, 600_000, 5_000_000, 900_000_000])
        payload = {
            **BORDERLINE,
            "loan_amount_pkr": rng.choice([1, 5_000, 90_000, 547_920, 3_000_000, 500_000_000]),
            "tenure_months": rng.choice([3, 12, 84]),
            "monthly_digital_payments": turnover,
            "cash_flow_proxy": min(rng.choice([0, turnover * 0.3, turnover * 2]), 1_000_000_000),
            "payment_history_score": rng.choice([0, 25, 52, 52.5, 53, 80, 100]),
            "years_in_operation": rng.choice([0, 0.5, 2, 5, 17, 100]),
        }
        applicant = SMEApplicant(**payload)
        result = ml_service.score(applicant)
        explanation = ml_service.build_explanation(
            result, application_id=1, business_name="x", applicant=applicant
        )
        assert 0 <= result.risk_score <= 100
        path = explanation.approval_path
        if result.decision is Decision.APPROVED:
            assert path is None
            continue
        for step in path.steps:
            floor = 70 if step.target_decision is Decision.APPROVED else 40
            if step.max_loan_pkr is not None:
                assert step.score_at_max_loan > floor
                assert 0 < step.max_loan_pkr <= payload["loan_amount_pkr"]
            if step.required_monthly_turnover_pkr is not None:
                assert step.score_at_turnover > floor
