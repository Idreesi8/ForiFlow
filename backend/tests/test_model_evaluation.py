"""Calibrated probability of default and the recorded hold-out evaluation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ml.features import load_model_evaluation
from schemas import SMEApplicant
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

# --- API (any engine) ---------------------------------------------------------------


def test_evaluation_needs_a_login(client: TestClient) -> None:
    for path in ("/model/evaluation", "/model/comparison"):
        assert client.get(path, headers={"Authorization": ""}).status_code == 401


@pytest.mark.skipif(load_model_evaluation() is None, reason="ml.evaluate_model not run")
def test_evaluation_reports_the_holdout(client: TestClient) -> None:
    body = client.get("/model/evaluation").json()
    hold = body["holdout"]

    assert body["rows"]["holdout"] == sum(row["rows"] for row in hold["bands"])
    matrix = hold["confusion_at_half"]
    assert (
        matrix["true_positive"]
        + matrix["false_positive"]
        + matrix["false_negative"]
        + matrix["true_negative"]
        == body["rows"]["holdout"]
    )
    assert hold["roc_curve"][0] == {"fpr": 0.0, "tpr": 0.0}
    assert hold["roc_curve"][-1] == {"fpr": 1.0, "tpr": 1.0}
    # Calibration must not cost discrimination, and must beat both the raw
    # probabilities and a model that always predicts the base rate.
    assert hold["calibrated"]["brier"] < hold["brier_no_skill"] < hold["raw"]["brier"]
    assert hold["raw"]["auc_roc"] - hold["calibrated"]["auc_roc"] < 0.005
    assert abs(hold["calibrated"]["mean_predicted"] - body["default_rate"]["holdout"]) < 0.01


@pytest.mark.skipif(load_model_evaluation() is None, reason="ml.evaluate_model not run")
def test_calibrator_is_monotone() -> None:
    calibrator = load_model_evaluation()["calibrator"]
    raw, calibrated = calibrator["raw_probability"], calibrator["calibrated_probability"]

    assert len(raw) == len(calibrated) >= 2
    assert raw == sorted(raw)
    assert calibrated == sorted(calibrated)
    assert 0.0 <= calibrated[0] and calibrated[-1] <= 1.0


def test_comparison_lists_the_served_model(client: TestClient) -> None:
    response = client.get("/model/comparison")
    if response.status_code == 404:
        pytest.skip("ml.compare_models not run")
    assert "served_ensemble_xgb_rf" in response.json()["models"]


def test_surrogate_reports_no_probability(client: TestClient) -> None:
    body = client.post("/score", json=MID_APPLICANT).json()

    assert body["probability_of_default"] is None
    assert body["explanation"]["probability_of_default"] is None


# --- trained ensemble ----------------------------------------------------------------


@pytest.mark.ml
def test_calibrated_pd_follows_the_score(ml_service) -> None:
    """A higher score can never carry a higher probability of default."""
    if ml_service.calibration is None:
        pytest.skip("ml.evaluate_model not run for this model")
    results = sorted(
        (
            ml_service.score(SMEApplicant(**payload))
            for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT)
        ),
        key=lambda result: result.risk_score,
    )
    for result in results:
        assert 0.0 <= result.calibrated_pd <= 1.0
    pds = [result.calibrated_pd for result in results]
    assert pds == sorted(pds, reverse=True)


@pytest.mark.ml
def test_explanation_stores_the_calibrated_pd(ml_service) -> None:
    if ml_service.calibration is None:
        pytest.skip("ml.evaluate_model not run for this model")
    result = ml_service.score(SMEApplicant(**MID_APPLICANT))
    explanation = ml_service.build_explanation(result, application_id=1, business_name="x")

    assert explanation.probability_of_default == result.calibrated_pd


@pytest.mark.ml
def test_a_calibrator_from_another_training_run_is_ignored(ml_service) -> None:
    stale = {"model_trained_at": "1999-01-01T00:00:00", "calibrator": {
        "raw_probability": [0.0, 1.0], "calibrated_probability": [0.0, 1.0]}}

    assert ml_service._calibration_breakpoints(stale) is None
    assert ml_service._calibration_breakpoints(None) is None
