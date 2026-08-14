"""API tests for the ``/score`` router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

pytestmark = pytest.mark.scoring


def test_health_endpoint_reports_ok(client: TestClient) -> None:
    """The health probe must confirm database connectivity."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:5173",
    ],
)
def test_cors_allows_the_react_dev_server(client: TestClient, origin: str) -> None:
    """The dashboard must reach the API on whichever dev port Vite ended up on."""
    response = client.options(
        "/score",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_score_persists_application_and_returns_decision(client: TestClient) -> None:
    """A valid application is scored, stored and returned with its explanation."""
    response = client.post("/score", json=STRONG_APPLICANT)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["application_id"] > 0
    assert body["business_name"] == STRONG_APPLICANT["business_name"]
    assert 71 <= body["risk_score"] <= 100
    assert body["decision"] == "Approved"
    assert body["risk_band"] == "Low Risk"
    assert body["monthly_installment_pkr"] == pytest.approx(2_400_000 / 36, abs=0.01)
    assert body["explanation"]["application_id"] == body["application_id"]

    stored = client.get(f"/score/applications/{body['application_id']}")
    assert stored.status_code == 200
    assert stored.json()["risk_score"] == body["risk_score"]


@pytest.mark.parametrize(
    ("payload", "expected_decision"),
    [
        (STRONG_APPLICANT, "Approved"),
        (MID_APPLICANT, "Manual Review"),
        (WEAK_APPLICANT, "Rejected"),
    ],
)
def test_decision_bands_end_to_end(
    client: TestClient, payload: dict[str, object], expected_decision: str
) -> None:
    """Each reference applicant must receive its expected decision."""
    response = client.post("/score", json=payload)

    assert response.status_code == 201
    assert response.json()["decision"] == expected_decision


def test_score_can_omit_the_explanation(client: TestClient) -> None:
    """The dashboard can request a lighter payload."""
    response = client.post(
        "/score", json=MID_APPLICANT, params={"include_explanation": False}
    )

    assert response.status_code == 201
    assert response.json()["explanation"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("loan_amount_pkr", 0),
        ("loan_amount_pkr", -50_000),
        ("tenure_months", 1),
        ("tenure_months", 240),
        ("payment_history_score", 101),
        ("payment_history_score", -1),
        ("order_consistency", 150),
        ("num_employees", -3),
        ("applicant_name", "A"),
    ],
)
def test_invalid_payloads_are_rejected(
    client: TestClient, field: str, value: object
) -> None:
    """Pydantic must reject out-of-range underwriting data with a 422."""
    response = client.post("/score", json={**MID_APPLICANT, field: value})

    assert response.status_code == 422
    assert any(field in str(error["loc"]) for error in response.json()["detail"])


def test_missing_required_field_is_rejected(client: TestClient) -> None:
    """Incomplete applications cannot be scored."""
    payload = {k: v for k, v in MID_APPLICANT.items() if k != "cash_flow_proxy"}

    assert client.post("/score", json=payload).status_code == 422


def test_list_applications_supports_filtering(client: TestClient) -> None:
    """Applications are listed newest first and can be filtered by decision."""
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        assert client.post("/score", json=payload).status_code == 201

    all_applications = client.get("/score/applications").json()
    assert len(all_applications) == 3

    approved = client.get("/score/applications", params={"decision": "Approved"}).json()
    assert len(approved) == 1
    assert approved[0]["business_name"] == STRONG_APPLICANT["business_name"]


def test_unknown_application_returns_404(client: TestClient) -> None:
    """Missing applications must produce a helpful 404."""
    response = client.get("/score/applications/9999")

    assert response.status_code == 404
    assert "9999" in response.json()["detail"]
