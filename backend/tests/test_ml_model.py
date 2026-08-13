"""Contract tests for the trained ensemble.

The whole module is skipped when the model artefacts are absent, so a fresh
checkout stays green before anyone runs ``python -m ml.train_real_model``.

These tests deliberately assert *invariants* rather than specific scores: the
artefacts are regenerated whenever the model is retrained, and neither XGBoost
nor the random forest is fitted under monotonicity constraints, so exact values
and per-feature monotonicity are not part of the contract. The one directional
assertion compares applicants that differ starkly on every trained feature.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from schemas import Decision, SMEApplicant
from services.scoring_service import (
    MANUAL_REVIEW_UPPER_BOUND,
    REJECT_UPPER_BOUND,
)
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

pytestmark = pytest.mark.ml


def test_artifacts_expose_feature_names_and_clips(ml_service) -> None:
    """Serving must know the trained feature order and its clip bounds."""
    assert ml_service.feature_names, "feature_names.json listed no features"
    assert set(ml_service.feature_clips) >= set(ml_service.feature_names)
    for name in ml_service.feature_names:
        lower, upper = ml_service.feature_clips[name]
        assert lower < upper


def test_score_stays_in_range_and_matches_its_decision(ml_service) -> None:
    """Every sample applicant scores in range with a policy-consistent decision."""
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        result = ml_service.score(SMEApplicant(**payload))

        assert 0.0 <= result.risk_score <= 100.0
        assert 0.0 <= result.probability_of_default <= 1.0
        assert 0.0 <= result.confidence <= 100.0

        if result.risk_score <= REJECT_UPPER_BOUND:
            assert result.decision is Decision.REJECTED
        elif result.risk_score <= MANUAL_REVIEW_UPPER_BOUND:
            assert result.decision is Decision.MANUAL_REVIEW
        else:
            assert result.decision is Decision.APPROVED


def test_member_average_matches_the_voting_classifier(ml_service) -> None:
    """The hand-rolled soft-vote must equal ``VotingClassifier.predict_proba``.

    Scoring averages the member probabilities itself to avoid a third pass over
    the forest, so this guards that shortcut against a change in how scikit-learn
    combines weighted soft votes.
    """
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        applicant = SMEApplicant(**payload)
        scaled, _, _ = ml_service._feature_frame(applicant)

        derived = ml_service._ensemble_probability(
            ml_service._member_probabilities(scaled)
        )
        library = float(ml_service.model.predict_proba(scaled)[0, 1])
        assert derived == pytest.approx(library, abs=1e-9)


def test_score_is_derived_from_the_default_probability(ml_service) -> None:
    """``risk_score`` must be exactly ``100 * (1 - PD)``."""
    result = ml_service.score(SMEApplicant(**MID_APPLICANT))
    expected = 100.0 * (1.0 - result.probability_of_default)
    assert result.risk_score == pytest.approx(expected, abs=0.01)


def test_scoring_is_deterministic(ml_service) -> None:
    """The same payload must always produce the same score."""
    applicant = SMEApplicant(**MID_APPLICANT)
    first = ml_service.score(applicant)
    second = ml_service.score(applicant)
    assert first.risk_score == second.risk_score
    assert first.contributions == second.contributions


def test_shap_contributions_reconstruct_the_score(ml_service) -> None:
    """base value + contributions must reproduce the score.

    This is the property that makes the waterfall chart trustworthy, and it holds
    because the members are explained in probability space and averaged with the
    voting weights.
    """
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        result = ml_service.score(SMEApplicant(**payload))
        total = sum((result.contributions or {}).values())
        assert ml_service.base_value + total == pytest.approx(result.risk_score, abs=0.5)


def test_contributions_cover_every_trained_feature(ml_service) -> None:
    """Each trained feature appears once, with a label and a direction."""
    result = ml_service.score(SMEApplicant(**MID_APPLICANT))
    contributions = ml_service.explain(result)

    assert {item.feature for item in contributions} == set(ml_service.feature_names)
    for item in contributions:
        assert item.label
        assert item.direction in {"increases", "decreases"}
        assert 0.0 <= item.weight <= 1.0


def test_features_are_clipped_into_the_trained_range(ml_service) -> None:
    """An out-of-distribution applicant is pulled back to the trained bounds."""
    extreme = SMEApplicant(
        **{
            **WEAK_APPLICANT,
            "loan_amount_pkr": 500_000_000,
            "existing_debt_pkr": 1_000_000_000,
            "cash_flow_proxy": 0,
        }
    )
    result = ml_service.score(extreme)

    for name in ml_service.feature_names:
        lower, upper = ml_service.feature_clips[name]
        assert lower <= result.normalised_features[name] <= upper
    assert 0.0 <= result.risk_score <= 100.0


def test_strong_applicant_outranks_weak_applicant(ml_service) -> None:
    """A clearly bankable SME must rank above a distressed one.

    The two differ on every trained feature at once (facility-to-cash-flow,
    repayment history and trading history), so this is a smoke test for a mis-wired
    feature vector rather than a claim about per-feature monotonicity.
    """
    strong = ml_service.score(SMEApplicant(**STRONG_APPLICANT))
    weak = ml_service.score(SMEApplicant(**WEAK_APPLICANT))
    assert strong.risk_score > weak.risk_score


def test_score_endpoint_returns_confidence_and_model_version(
    ml_client: TestClient,
) -> None:
    """The API surfaces the ML-only fields and a consistent explanation."""
    response = ml_client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201, response.text

    body = response.json()
    assert 0 <= body["confidence"] <= 100
    assert body["model_version"].startswith("ensemble-xgb-rf-")

    explanation = body["explanation"]
    assert explanation["model_version"] == body["model_version"]
    total = explanation["base_value"] + sum(
        item["contribution"] for item in explanation["feature_contributions"]
    )
    assert total == pytest.approx(body["risk_score"], abs=0.5)


def test_explain_endpoint_reproduces_the_stored_score(ml_client: TestClient) -> None:
    """Re-explaining a persisted application returns the same score."""
    created = ml_client.post("/score", json=MID_APPLICANT).json()
    explained = ml_client.post(f"/explain/{created['application_id']}")

    assert explained.status_code == 200, explained.text
    assert explained.json()["risk_score"] == pytest.approx(created["risk_score"], abs=0.01)
