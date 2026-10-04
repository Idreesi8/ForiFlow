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
