"""API tests for the ``/explain`` router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.scoring_service import FEATURE_WEIGHTS
from tests.conftest import WEAK_APPLICANT

pytestmark = pytest.mark.explain


def test_explain_returns_full_attribution(
    client: TestClient, scored_application_id: int
) -> None:
    """Every weighted feature must appear with a signed contribution."""
    response = client.post(f"/explain/{scored_application_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["application_id"] == scored_application_id
    assert body["base_value"] == 50.0
    assert len(body["feature_contributions"]) == len(FEATURE_WEIGHTS)

    features = {c["feature"] for c in body["feature_contributions"]}
    assert features == set(FEATURE_WEIGHTS)
    for contribution in body["feature_contributions"]:
        assert contribution["label"]
        assert contribution["direction"] in {"increases", "decreases"}


def test_explanation_contributions_reconstruct_the_score(
    client: TestClient, scored_application_id: int
) -> None:
    """base_value + sum(contributions) must equal the application's score."""
    body = client.post(f"/explain/{scored_application_id}").json()
    total = body["base_value"] + sum(
        c["contribution"] for c in body["feature_contributions"]
    )

    assert total == pytest.approx(body["risk_score"], abs=0.5)


def test_explanation_is_cached_at_scoring_time(client: TestClient) -> None:
    """The stored explanation is served without recomputation."""
    scored = client.post("/score", json=WEAK_APPLICANT).json()
    cached = client.get(f"/explain/{scored['application_id']}").json()

    assert cached == scored["explanation"]


def test_refresh_regenerates_the_explanation(
    client: TestClient, scored_application_id: int
) -> None:
    """A refresh must reproduce an identical, deterministic explanation."""
    first = client.post(f"/explain/{scored_application_id}").json()
    refreshed = client.post(
        f"/explain/{scored_application_id}", params={"refresh": True}
    ).json()

    assert refreshed == first


def test_weak_applicant_explanation_flags_concerns(client: TestClient) -> None:
    """A rejected applicant must expose its adverse-action reasons."""
    scored = client.post("/score", json=WEAK_APPLICANT).json()
    body = client.post(f"/explain/{scored['application_id']}").json()

    assert body["decision"] == "Rejected"
    assert body["risk_band"] == "High Risk"
    assert body["top_negative_factors"]
    assert "Main concerns" in body["narrative"]


def test_explain_unknown_application_returns_404(client: TestClient) -> None:
    """Explaining a missing application must fail cleanly."""
    response = client.post("/explain/4242")

    assert response.status_code == 404
    assert "4242" in response.json()["detail"]
