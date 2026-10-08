"""The fitted early-warning Markov chain and how monitoring uses it."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ml import ews_markov
from ml.features import load_ews_transition
from schemas import EWSMonitorRequest, InstallmentStatus
from services.ews_service import MODEL_ALERT_PROBABILITY, STATUS_TO_CHAIN_STATE, EWSService
from tests.conftest import STRONG_APPLICANT, decide

CHAIN = load_ews_transition()
needs_chain = pytest.mark.skipif(CHAIN is None, reason="ml.ews_markov not run")

# A small chain with easy numbers: nothing leaves Current, Late moves on or defaults.
TOY = np.array(
    [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 0.5, 0.5, 0.0],
        [0.0, 0.0, 0.5, 0.5],
        [0.0, 0.0, 0.0, 1.0],
    ]
)


# --- the mathematics ---------------------------------------------------------------


def test_states_follow_months_of_delay() -> None:
    assert [ews_markov.state_of(d) for d in (-2, -1, 0, 1, 2, 3, 4, 8)] == [
        0, 0, 0, 1, 1, 2, 3, 3
    ]


def test_default_is_absorbing_in_the_histories() -> None:
    import pandas as pd

    frame = pd.DataFrame([dict(zip(ews_markov.PAY_COLUMNS, (0, 4, 0, 2, 0, 0)))])
    assert ews_markov.histories(frame).tolist() == [[0, 3, 3, 3, 3, 3]]


def test_transition_rows_are_probabilities() -> None:
    states = np.array([[0, 0, 1, 2, 3, 3], [0, 1, 1, 0, 0, 0]])
    matrix = ews_markov.transition_matrix(ews_markov.count_transitions(states))

    assert np.allclose(matrix.sum(axis=1), 1.0)
    assert matrix[ews_markov.DEFAULT].tolist() == [0.0, 0.0, 0.0, 1.0]
    assert matrix[0, 0] == pytest.approx(3 / 5)


def test_default_probability_accumulates_month_by_month() -> None:
    reached = ews_markov.default_by_month(TOY, state=2, months=3)
    assert reached == pytest.approx([0.5, 0.75, 0.875])
    assert ews_markov.default_by_month(TOY, state=0, months=12)[-1] == 0.0


def test_expected_days_is_conditional_on_defaulting() -> None:
    # From Late 60-89: default in month 1 w.p. 1/2, month 2 w.p. 1/4: mean of
    # (1, 2) weighted (2/3, 1/3) is 4/3 months = 40 days.
    assert ews_markov.expected_days_to_default(TOY, state=2, months=2) == pytest.approx(40.0)
    assert ews_markov.expected_days_to_default(TOY, state=3, months=12) == 0.0
    # A state that never defaults has no runway to report.
    assert ews_markov.expected_days_to_default(TOY, state=0, months=12) is None


# --- the fitted artefact -----------------------------------------------------------


@needs_chain
def test_fitted_chain_is_consistent() -> None:
    matrix = np.array(CHAIN["transition_matrix"])
    assert np.allclose(matrix.sum(axis=1), 1.0)

    outlook = {row["state"]: row for row in CHAIN["state_outlook"]}
    assert set(outlook) == set(CHAIN["states"]) == set(STATUS_TO_CHAIN_STATE.values())
    # Risk rises and the runway shortens with every ageing bucket.
    order = ["Current", "Late 1-59", "Late 60-89", "Default"]
    risks = [outlook[name]["default_within_3_months"] for name in order]
    days = [outlook[name]["expected_days_to_default"] for name in order]
    assert risks == sorted(risks)
    assert days == sorted(days, reverse=True)
    # The earliest a Late 60-89 account can default is next month.
    assert outlook["Late 60-89"]["expected_days_to_default"] >= 30


@needs_chain
def test_outlook_matches_the_matrix() -> None:
    matrix = np.array(CHAIN["transition_matrix"])
    for state, row in enumerate(CHAIN["state_outlook"][:-1]):
        reached = ews_markov.default_by_month(matrix, state, CHAIN["outlook_months"])
        assert row["default_within_3_months"] == pytest.approx(reached[2])
        assert row["default_within_12_months"] == pytest.approx(reached[-1])


# --- how monitoring uses it ----------------------------------------------------------


def _request(status: InstallmentStatus, **fields: Any) -> EWSMonitorRequest:
    return EWSMonitorRequest(
        borrower_id=1,
        month_number=1,
        installment_status=status,
        bureau_balance=0,
        pos_cash_balance=1_000_000,
        **fields,
    )


def _evaluate(service: EWSService, status: InstallmentStatus, **fields: Any):
    return service.evaluate(
        baseline_score=80.0,
        payload=_request(status, **fields),
        original_loan_amount_pkr=1_000_000,
        expected_monthly_cash_flow=100_000,
    )


def test_without_a_chain_the_service_stays_rule_based() -> None:
    outcome = _evaluate(EWSService(), InstallmentStatus.LATE_60_89)

    assert outcome.default_probability_3m is None
    assert outcome.runway_basis == "rules"
    assert outcome.alert_triggered is True


@needs_chain
def test_the_chain_supplies_probability_and_runway() -> None:
    service = EWSService(chain=CHAIN)
    outlook = {row["state"]: row for row in CHAIN["state_outlook"]}

    late = _evaluate(service, InstallmentStatus.LATE_60_89)
    assert late.runway_basis == "markov"
    assert late.default_probability_3m == pytest.approx(
        outlook["Late 60-89"]["default_within_3_months"], abs=1e-4
    )
    assert late.estimated_days_to_default == outlook["Late 60-89"]["expected_days_to_default"]

    # The two lightest buckets share a chain state.
    assert (
        _evaluate(service, InstallmentStatus.LATE_1_29).default_probability_3m
        == _evaluate(service, InstallmentStatus.LATE_30_59).default_probability_3m
    )
    assert _evaluate(service, InstallmentStatus.DEFAULT).estimated_days_to_default == 0


def test_the_chain_no_longer_raises_an_alert() -> None:
    """Reversed in 2.1: a high chain probability alone no longer alerts.

    Until 2.0 the chain could alert when the score had not dropped. It is now
    reported for reference only; the alert comes from the EWS rules.
    """
    chain = {
        "state_outlook": [
            {"state": "Late 60-89", "default_within_3_months": MODEL_ALERT_PROBABILITY,
             "default_within_12_months": 0.5, "expected_days_to_default": 60},
        ]
    }
    service = EWSService(chain=chain)

    by_model = _evaluate(
        service, InstallmentStatus.LATE_60_89, current_score=80.0,
        override_reason="Officer typed the bank's own score.",
    )
    assert by_model.score_drop == 0.0
    assert by_model.default_probability_3m == MODEL_ALERT_PROBABILITY
    assert by_model.alert_triggered is False


@needs_chain
def test_the_chain_flagged_only_what_the_rules_mark_critical() -> None:
    """Why the chain left the alert path: it added no alert the rules miss.

    The statuses whose fitted three-month default probability reached the old
    10% line are exactly Late 60-89 and Default, which the EWS rules treat as
    CRITICAL on their own.
    """
    from services.ews_engine import CRITICAL_STATUSES

    service = EWSService(chain=CHAIN)
    flagged = {
        status.value
        for status in InstallmentStatus
        if service.chain_outlook(status)["default_within_3_months"] >= MODEL_ALERT_PROBABILITY
    }
    assert flagged == set(CRITICAL_STATUSES)


@needs_chain
def test_monitoring_returns_the_probability(client: TestClient) -> None:
    scored = client.post("/score", json=STRONG_APPLICANT).json()
    decide(client, scored["application_id"])
    body = client.post(
        "/ews/monitor",
        json={
            "borrower_id": scored["application_id"],
            "month_number": 1,
            "installment_status": "Late 60-89",
            "bureau_balance": 1_000_000,
            "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"],
        },
    ).json()

    assert body["runway_basis"] == "markov"
    assert body["default_probability_3m"] >= MODEL_ALERT_PROBABILITY
    assert body["alert"]["estimated_days_to_default"] == body["estimated_days_to_default"]
    # The alert comes from the rules, with its reasons; the probability is reference only.
    assert body["ews_state"] == "CRITICAL"
    assert "PAYMENT_DELAY_INCREASED" in body["alert"]["reason_codes"]


def test_early_warning_endpoint(client: TestClient) -> None:
    assert client.get("/model/early-warning", headers={"Authorization": ""}).status_code == 401
    response = client.get("/model/early-warning")
    if response.status_code == 404:
        pytest.skip("ml.ews_markov not run")
    assert "transition_matrix" in response.json()
