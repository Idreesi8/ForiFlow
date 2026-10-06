"""Officer decisions: Manual Review approval, who scored what, alert handling.

The model's band stays in ``decision``. An officer's call on a Manual Review
case is stored beside it, and only an approved application can be monitored.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from models.database import Application, User
from services.auth_service import hash_password
from tests.conftest import (
    MID_APPLICANT,
    STRONG_APPLICANT,
    WEAK_APPLICANT,
    bearer_header,
    decide,
)

NOTE = "Five years of clean POS receipts; facility is 28% of turnover."


def _score(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/score", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _review(client: TestClient, application_id: int, decision: str, **kwargs: Any):
    return client.post(
        f"/score/applications/{application_id}/review",
        json={"decision": decision, "note": NOTE},
        **kwargs,
    )


def _month(borrower_id: int, month: int = 1, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "borrower_id": borrower_id,
        "month_number": month,
        "installment_status": "On Time",
        "bureau_balance": 1_000_000,
        "pos_cash_balance": MID_APPLICANT["cash_flow_proxy"],
    }
    payload.update(overrides)
    return payload


def _analyst(db_session_factory) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(
            User(
                username="analyst1",
                hashed_password=hash_password("analyst-password"),
                role="analyst",
            )
        )
        db.commit()
    finally:
        db.close()
    return bearer_header(username="analyst1", role="analyst")


@pytest.fixture(name="pending")
def pending_fixture(client: TestClient) -> dict[str, Any]:
    scored = _score(client, MID_APPLICANT)
    assert scored["decision"] == "Manual Review"
    return scored


# --- who scored it ---------------------------------------------------------------


def test_scoring_records_the_officer(client: TestClient) -> None:
    scored = _score(client, STRONG_APPLICANT)
    assert scored["scored_by"] == "admin"

    stored = client.get(f"/score/applications/{scored['application_id']}").json()
    assert stored["scored_by"] == "admin"


def test_no_band_is_final_until_an_officer_decides(client: TestClient) -> None:
    """Reversed in 2.0. Before, an Approved or Rejected band was the final decision."""
    approve_recommended = _score(client, STRONG_APPLICANT)["application_id"]
    decline_recommended = _score(client, WEAK_APPLICANT)["application_id"]

    for application_id, band in ((approve_recommended, "Approved"), (decline_recommended, "Rejected")):
        stored = client.get(f"/score/applications/{application_id}").json()
        assert stored["decision"] == band
        assert stored["final_decision"] is None
        assert stored["decision_status"] == "Pending"


# --- Manual Review decision ------------------------------------------------------


def test_manual_review_is_pending_until_an_officer_decides(
    client: TestClient, pending: dict[str, Any]
) -> None:
    application_id = pending["application_id"]
    stored = client.get(f"/score/applications/{application_id}").json()
    assert stored["final_decision"] is None
    assert stored["review_decision"] is None

    queue = client.get("/score/applications", params={"pending_review": True}).json()
    assert [row["id"] for row in queue] == [application_id]


@pytest.mark.parametrize("decision", ["Approved", "Rejected"])
def test_officer_decision_is_recorded_with_reason_name_and_time(
    client: TestClient, pending: dict[str, Any], decision: str
) -> None:
    application_id = pending["application_id"]
    response = _review(client, application_id, decision)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"] == "Manual Review"  # the model's band is kept
    assert body["review_decision"] == decision
    assert body["final_decision"] == decision
    assert body["review_note"] == NOTE
    assert body["reviewed_by"] == "admin"
    assert body["reviewed_at"] is not None

    assert client.get("/score/applications", params={"pending_review": True}).json() == []
    decided = client.get("/score/applications", params={"pending_review": False}).json()
    assert [row["id"] for row in decided] == [application_id]


def test_a_recorded_decision_cannot_be_changed(
    client: TestClient, pending: dict[str, Any]
) -> None:
    application_id = pending["application_id"]
    assert _review(client, application_id, "Approved").status_code == 200

    again = _review(client, application_id, "Rejected")
    assert again.status_code == 409
    assert "already Approved by admin" in again.json()["detail"]
    stored = client.get(f"/score/applications/{application_id}").json()
    assert stored["review_decision"] == "Approved"


@pytest.mark.parametrize(
    ("payload", "band"), [(STRONG_APPLICANT, "Approved"), (WEAK_APPLICANT, "Rejected")]
)
def test_every_recommendation_takes_an_officer_decision(
    client: TestClient, payload: dict[str, Any], band: str
) -> None:
    """Reversed in 2.0: no band is final by itself. The officer decides each one."""
    scored = _score(client, payload)
    assert scored["decision"] == band and scored["decision_status"] == "Pending"

    response = _review(client, scored["application_id"], band)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == band  # the recommendation is left as it was
    assert body["final_decision"] == band and body["reviewed_by"] == "admin"


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "Approved", "note": "too short"},
        {"decision": "Approved"},
        {"decision": "Manual Review", "note": NOTE},
        {"decision": "Approved", "note": "x" * 1001},
    ],
)
def test_invalid_review_payloads_are_rejected(
    client: TestClient, pending: dict[str, Any], body: dict[str, Any]
) -> None:
    response = client.post(
        f"/score/applications/{pending['application_id']}/review", json=body
    )
    assert response.status_code == 422


def test_reviewing_an_unknown_application_returns_404(client: TestClient) -> None:
    assert _review(client, 4321, "Approved").status_code == 404


def test_analysts_cannot_decide_manual_review(
    client: TestClient, db_session_factory, pending: dict[str, Any]
) -> None:
    analyst = _analyst(db_session_factory)
    response = _review(client, pending["application_id"], "Approved", headers=analyst)

    assert response.status_code == 403
    assert client.get(
        f"/score/applications/{pending['application_id']}"
    ).json()["review_decision"] is None


# --- monitoring follows the final decision ----------------------------------------


def test_pending_manual_review_cannot_be_monitored(
    client: TestClient, pending: dict[str, Any]
) -> None:
    response = client.post("/ews/monitor", json=_month(pending["application_id"]))

    assert response.status_code == 409
    assert "awaiting an officer decision" in response.json()["detail"]


def test_officer_approved_application_can_be_monitored(
    client: TestClient, pending: dict[str, Any]
) -> None:
    application_id = pending["application_id"]
    assert _review(client, application_id, "Approved").status_code == 200

    response = client.post("/ews/monitor", json=_month(application_id))
    assert response.status_code == 201, response.text


def test_officer_rejected_application_cannot_be_monitored(
    client: TestClient, pending: dict[str, Any]
) -> None:
    application_id = pending["application_id"]
    assert _review(client, application_id, "Rejected").status_code == 200

    response = client.post("/ews/monitor", json=_month(application_id))
    assert response.status_code == 409
    assert "Rejected by admin" in response.json()["detail"]


# --- alert handling ----------------------------------------------------------------


@pytest.fixture(name="alert")
def alert_fixture(client: TestClient) -> dict[str, Any]:
    scored = _score(client, STRONG_APPLICANT)
    decide(client, scored["application_id"])
    body = client.post(
        "/ews/monitor",
        json=_month(
            scored["application_id"],
            current_score=scored["risk_score"] - 25,
            pos_cash_balance=STRONG_APPLICANT["cash_flow_proxy"],
        ),
    ).json()
    assert body["alert_triggered"] is True
    assert body["alert"]["business_name"] == STRONG_APPLICANT["business_name"]
    return body["alert"]


def test_any_officer_can_take_an_alert_for_review(
    client: TestClient, db_session_factory, alert: dict[str, Any]
) -> None:
    analyst = _analyst(db_session_factory)
    response = client.patch(f"/ews/alerts/{alert['id']}/review", headers=analyst)

    assert response.status_code == 200, response.text
    assert response.json()["alert_status"] == "In Review"
    assert response.json()["assigned_to"] == "analyst1"
    listed = client.get("/ews/alerts", params={"alert_status": "In Review"}).json()
    assert [row["id"] for row in listed] == [alert["id"]]


def test_resolving_records_who_and_why_and_is_final(
    client: TestClient, alert: dict[str, Any]
) -> None:
    assert client.patch(f"/ews/alerts/{alert['id']}/review").status_code == 200
    resolved = client.patch(
        f"/ews/alerts/{alert['id']}/resolve", json={"note": "Paid arrears on 12 Oct."}
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["alert_status"] == "Resolved"
    assert body["resolved_by"] == "admin"
    assert body["resolution_note"] == "Paid arrears on 12 Oct."
    assert body["assigned_to"] == "admin"

    again = client.patch(f"/ews/alerts/{alert['id']}/resolve", json={"note": "Again."})
    assert again.status_code == 409
    assert client.patch(f"/ews/alerts/{alert['id']}/review").status_code == 409


def test_resolving_needs_a_note(client: TestClient, alert: dict[str, Any]) -> None:
    assert client.patch(f"/ews/alerts/{alert['id']}/resolve").status_code == 422
    short = client.patch(f"/ews/alerts/{alert['id']}/resolve", json={"note": "ok"})
    assert short.status_code == 422


def test_reviewing_an_unknown_alert_returns_404(client: TestClient) -> None:
    assert client.patch("/ews/alerts/999/review").status_code == 404


# --- the stored explanation is the audit record ------------------------------------


def test_refresh_never_overwrites_the_stored_explanation(
    client: TestClient, db_session_factory
) -> None:
    application_id = _score(client, STRONG_APPLICANT)["application_id"]

    # Stand-in for an explanation written by an earlier model version.
    db = db_session_factory()
    try:
        application = db.get(Application, application_id)
        stored = json.loads(application.shap_explanation_json)
        stored["model_version"] = "earlier-model"
        application.shap_explanation_json = json.dumps(stored)
        db.commit()
    finally:
        db.close()

    refreshed = client.post(f"/explain/{application_id}", params={"refresh": True}).json()
    assert refreshed["model_version"] != "earlier-model"

    kept = client.get(f"/explain/{application_id}").json()
    assert kept["model_version"] == "earlier-model"
