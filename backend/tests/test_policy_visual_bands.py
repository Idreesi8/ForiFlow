"""Band boundaries shown to officers come from the right policy, never from constants.

Policy A is the demo policy (Decline <= 40, Manual Review <= 70, Approve above).
Policy B is Decline <= 45, Manual Review <= 74, Approve above (75 and up).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from models.database import Application
from schemas import RiskBand
from services import policy_rules
from services.policy_rules import ScoreBands
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

POLICY_B = {
    "version": "B",
    "name": "Policy B",
    "decline_max_score": 45,
    "manual_review_max_score": 74,
    "manager_approval_limit_pkr": 2_000_000,
}
LEGACY_TO_RECOMMENDATION = {"Rejected": "Decline", "Manual Review": "Manual Review", "Approved": "Approve"}
BAND_OF = {"Decline": "High Risk", "Manual Review": "Medium Risk", "Approve": "Low Risk"}


def _activate_b(client: TestClient) -> None:
    created = client.post("/policy/versions", json=POLICY_B)
    assert created.status_code == 201, created.text
    assert client.post(f"/policy/versions/{created.json()['id']}/activate").status_code == 200


def _score(client: TestClient, payload: dict) -> dict:
    response = client.post("/score", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _rule(score: float, low: float, high: float) -> str:
    """What the drawn bands say for a score: the check the dashboard relies on."""
    return "Decline" if score <= low else "Manual Review" if score <= high else "Approve"


# --- histogram ----------------------------------------------------------------------


def test_policy_a_histogram_keeps_the_bars_the_dashboard_always_had(client: TestClient) -> None:
    stats = client.get("/score/stats").json()

    assert stats["histogram_policy_version"] == "1.0"
    assert stats["histogram_bands"] == {
        "decline_max_score": 40.0,
        "manual_review_max_score": 70.0,
        "approve_above_score": 70.0,
        "source": "active_policy",
    }
    bars = stats["score_histogram"]
    assert [b["label"] for b in bars] == ["0-20", "20-40", "40-55", "55-70", "70-85", "85-100"]
    assert [b["risk_band"] for b in bars] == ["High Risk"] * 2 + ["Medium Risk"] * 2 + ["Low Risk"] * 2
    assert [b["recommendation"] for b in bars] == ["Decline"] * 2 + ["Manual Review"] * 2 + ["Approve"] * 2


def test_policy_b_moves_the_histogram_edges_and_colours(client: TestClient) -> None:
    _activate_b(client)
    stats = client.get("/score/stats").json()

    assert stats["histogram_policy_version"] == "B"
    assert (stats["histogram_bands"]["decline_max_score"], stats["histogram_bands"]["manual_review_max_score"]) == (45, 74)
    bars = stats["score_histogram"]
    assert [b["label"] for b in bars] == ["0-22.5", "22.5-45", "45-59.5", "59.5-74", "74-87", "87-100"]
    assert [(b["lower"], b["upper"]) for b in bars] == [
        (0, 22.5), (22.5, 45), (45, 59.5), (59.5, 74), (74, 87), (87, 100)]
    assert [b["risk_band"] for b in bars] == ["High Risk"] * 2 + ["Medium Risk"] * 2 + ["Low Risk"] * 2


@pytest.mark.parametrize("bands", [ScoreBands(40, 70), ScoreBands(45, 74), ScoreBands(42.5, 71.25)])
def test_no_bar_straddles_a_cut_off(bands: ScoreBands) -> None:
    buckets = policy_rules.histogram_buckets(bands)

    assert buckets[0][1] == 0 and buckets[-1][2] == 100
    assert all(a[2] == b[1] for a, b in zip(buckets, buckets[1:]))  # contiguous
    edges = {upper for _, _, upper, _ in buckets}
    assert {bands.decline_max_score, bands.manual_review_max_score} <= edges
    for _, lower, upper, band in buckets:
        # Every score in (lower, upper] has the bar's band under this policy.
        for score in (lower + 0.01, (lower + upper) / 2, upper):
            assert policy_rules.risk_band_for(score, bands) is band


def test_histogram_counts_follow_the_active_policy_edges(client: TestClient, db_session_factory) -> None:
    application_id = _score(client, STRONG_APPLICANT)["application_id"]
    db = db_session_factory()
    try:
        template = db.get(Application, application_id)
        for score in (45.0, 45.01, 74.0, 74.01):
            clone = Application(**{c.name: getattr(template, c.name) for c in Application.__table__.columns if c.name != "id"})
            clone.risk_score = score
            db.add(clone)
        db.commit()
    finally:
        db.close()
    _activate_b(client)

    bars = {b["label"]: b["count"] for b in client.get("/score/stats").json()["score_histogram"]}
    assert bars["22.5-45"] >= 1 and bars["45-59.5"] >= 1  # 45 and 45.01 split on the edge
    assert bars["59.5-74"] >= 1 and bars["74-87"] >= 1  # 74 and 74.01 split on the edge


# --- each application carries the bands it was assessed under ------------------------


def test_new_assessments_carry_the_active_policy_bands(client: TestClient) -> None:
    under_a = _score(client, MID_APPLICANT)
    assert under_a["policy"]["bands"] == {
        "decline_max_score": 40.0,
        "manual_review_max_score": 70.0,
        "approve_above_score": 70.0,
        "source": "policy_snapshot",
    }
    _activate_b(client)
    under_b = _score(client, MID_APPLICANT)
    assert under_b["policy"]["bands"]["decline_max_score"] == 45
    assert under_b["policy"]["bands"]["manual_review_max_score"] == 74
    assert under_b["policy"]["bands"]["source"] == "policy_snapshot"


def test_activating_a_policy_does_not_redraw_an_old_assessment(client: TestClient) -> None:
    old = _score(client, MID_APPLICANT)
    before = client.get(f"/score/applications/{old['application_id']}").json()
    _activate_b(client)
    after = client.get(f"/score/applications/{old['application_id']}").json()

    assert after["policy"]["bands"] == before["policy"]["bands"]
    assert after["policy"]["bands"]["decline_max_score"] == 40.0
    assert after["policy"]["policy_version"] == "1.0"
    listed = {row["id"]: row for row in client.get("/score/applications").json()}
    assert listed[old["application_id"]]["policy"]["bands"]["manual_review_max_score"] == 70.0
    history = client.get(f"/borrowers/{old['borrower_public_id']}/history").json()
    assert history["applications"][0]["policy_version"] == "1.0"


def test_an_application_from_before_2_0_shows_the_fixed_rule_of_its_time(
    client: TestClient, db_session_factory
) -> None:
    application_id = _score(client, MID_APPLICANT)["application_id"]
    db = db_session_factory()
    try:
        row = db.get(Application, application_id)
        row.policy_evaluation, row.policy_id, row.policy_version = None, None, None
        db.commit()
    finally:
        db.close()
    _activate_b(client)  # today's policy must not be used for it

    bands = client.get(f"/score/applications/{application_id}").json()["policy"]["bands"]
    assert bands == {
        "decline_max_score": 40.0,
        "manual_review_max_score": 70.0,
        "approve_above_score": 70.0,
        "source": "legacy_fixed_rule",
    }


# --- what the API recommends and what the bands draw always agree --------------------


@pytest.mark.parametrize("activate_b", [False, True])
def test_recommendation_band_and_drawn_bands_agree(client: TestClient, activate_b: bool) -> None:
    if activate_b:
        _activate_b(client)
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT, {**MID_APPLICANT, "monthly_digital_payments": 900_000}):
        body = _score(client, payload)
        bands = body["policy"]["bands"]
        drawn = _rule(body["risk_score"], bands["decline_max_score"], bands["manual_review_max_score"])
        assert body["recommendation"] == drawn == LEGACY_TO_RECOMMENDATION[body["decision"]]
        assert body["risk_band"] == body["assessment"]["risk_band"] == BAND_OF[drawn]
        stored = client.get(f"/score/applications/{body['application_id']}").json()
        assert stored["recommendation"] == drawn and stored["risk_band"] == BAND_OF[drawn]


def test_the_same_score_is_recommended_differently_under_a_and_b(client: TestClient, db_session_factory) -> None:
    """A score between 70 and 74 is Approve under A and Manual Review under B."""
    from services.scoring_service import ScoringService
    from schemas import SMEApplicant

    service = ScoringService()
    payload = None
    for history in range(0, 101):
        candidate = {**STRONG_APPLICANT, "payment_history_score": history}
        score = service.score(SMEApplicant(**candidate)).risk_score
        if 70 < score <= 74:
            payload = candidate
            break
    assert payload is not None, "no applicant scored between 70 and 74"

    under_a = _score(client, payload)
    _activate_b(client)
    under_b = _score(client, payload)

    assert under_a["risk_score"] == under_b["risk_score"]
    assert (under_a["recommendation"], under_a["risk_band"]) == ("Approve", "Low Risk")
    assert (under_b["recommendation"], under_b["risk_band"]) == ("Manual Review", "Medium Risk")
    # Each keeps its own bands, so each is drawn the way it was recommended.
    assert _rule(under_a["risk_score"], 40, 70) == "Approve"
    assert _rule(under_b["risk_score"], 45, 74) == "Manual Review"
    assert client.get(f"/score/applications/{under_a['application_id']}").json()["recommendation"] == "Approve"


def test_stored_explanations_keep_their_recommendation_after_a_policy_change(client: TestClient, db_session_factory) -> None:
    body = _score(client, MID_APPLICANT)
    _activate_b(client)
    db = db_session_factory()
    try:
        stored = json.loads(db.get(Application, body["application_id"]).shap_explanation_json)
    finally:
        db.close()
    assert stored["recommendation"] == body["recommendation"] and stored["policy_version"] == "1.0"
    assert client.get(f"/explain/{body['application_id']}").json()["recommendation"] == body["recommendation"]


# --- the same on PostgreSQL ----------------------------------------------------------

from tests.test_postgres_phase2 import (  # noqa: E402  fixtures, registered by import
    migrated_fixture,
    pg_client_fixture,
    pg_engine_fixture,
)


@pytest.mark.postgres
def test_bands_follow_the_right_policy_on_postgres(pg_client: TestClient) -> None:
    legacy = pg_client.get("/score/applications/1").json()  # scored before 2.0
    assert legacy["policy"]["bands"]["source"] == "legacy_fixed_rule"

    under_a = _score(pg_client, MID_APPLICANT)
    _activate_b(pg_client)
    under_b = _score(pg_client, MID_APPLICANT)

    a = pg_client.get(f"/score/applications/{under_a['application_id']}").json()["policy"]["bands"]
    b = pg_client.get(f"/score/applications/{under_b['application_id']}").json()["policy"]["bands"]
    assert (a["decline_max_score"], a["manual_review_max_score"]) == (40, 70)
    assert (b["decline_max_score"], b["manual_review_max_score"]) == (45, 74)
    stats = pg_client.get("/score/stats").json()
    assert stats["histogram_policy_version"] == "B"
    assert [bar["label"] for bar in stats["score_histogram"]][2:4] == ["45-59.5", "59.5-74"]
    assert pg_client.get("/score/applications/1").json()["policy"]["bands"]["source"] == "legacy_fixed_rule"
