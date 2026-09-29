"""Dashboard totals and the rules that keep EWS alerts consistent."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from models.database import User
from services.auth_service import hash_password
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT, bearer_header

NOTE = "Clean POS receipts for five years; facility is 28% of turnover."


def _score(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/score", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _month(borrower: dict[str, Any], month: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "borrower_id": borrower["application_id"],
        "month_number": month,
        "installment_status": "On Time",
        "bureau_balance": 1_000_000,
        "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"],
    }
    payload.update(overrides)
    return payload


@pytest.fixture(name="approved")
def approved_fixture(client: TestClient) -> dict[str, Any]:
    scored = _score(client, STRONG_APPLICANT)
    assert scored["decision"] == "Approved"
    return scored


# --- portfolio totals ------------------------------------------------------------


def test_stats_on_an_empty_portfolio(client: TestClient) -> None:
    body = client.get("/score/stats").json()

    assert body["total_applications"] == 0
    assert body["approval_rate"] == 0.0
    assert body["average_score"] is None
    assert body["open_alerts"] == 0
    assert body["worst_open_drop"] is None
    assert sum(bucket["count"] for bucket in body["score_histogram"]) == 0


def test_stats_count_every_application_and_officer_decisions(client: TestClient) -> None:
    strong = _score(client, STRONG_APPLICANT)
    weak = _score(client, WEAK_APPLICANT)
    approved_mr = _score(client, MID_APPLICANT)
    rejected_mr = _score(client, MID_APPLICANT)
    _score(client, MID_APPLICANT)  # left pending

    for application, decision in ((approved_mr, "Approved"), (rejected_mr, "Rejected")):
        response = client.post(
            f"/score/applications/{application['application_id']}/review",
            json={"decision": decision, "note": NOTE},
        )
        assert response.status_code == 200

    body = client.get("/score/stats").json()
    assert body["total_applications"] == 5
    assert body["model_decisions"] == {"Rejected": 1, "Manual Review": 3, "Approved": 1}
    assert body["pending_review"] == 1
    assert body["final_approved"] == 2
    assert body["final_rejected"] == 2
    assert body["approval_rate"] == 40.0
    assert body["approved_exposure_pkr"] == pytest.approx(
        STRONG_APPLICANT["loan_amount_pkr"] + MID_APPLICANT["loan_amount_pkr"]
    )
    scores = [strong["risk_score"], weak["risk_score"], *[approved_mr["risk_score"]] * 3]
    assert body["average_score"] == pytest.approx(sum(scores) / 5, abs=0.01)
    # Every score lands in exactly one bar.
    assert sum(bucket["count"] for bucket in body["score_histogram"]) == 5


def test_histogram_has_no_gaps_between_bars(client: TestClient, db_session_factory) -> None:
    """Scores between whole-number edges (40.5, 70.3) must still be counted."""
    from models.database import Application

    application_id = _score(client, STRONG_APPLICANT)["application_id"]
    db = db_session_factory()
    try:
        template = db.get(Application, application_id)
        for score in (20.5, 40.0, 40.5, 55.75, 70.3, 85.2, 100.0):
            clone = Application(
                **{
                    column.name: getattr(template, column.name)
                    for column in Application.__table__.columns
                    if column.name != "id"
                }
            )
            clone.risk_score = score
            db.add(clone)
        db.commit()
    finally:
        db.close()

    bars = {bucket["label"]: bucket["count"] for bucket in client.get("/score/stats").json()["score_histogram"]}
    assert sum(bars.values()) == 8
    assert bars["20-40"] == 2  # 20.5 and 40.0 (40 is still Rejected)
    assert bars["40-55"] == 1  # 40.5


def test_final_decision_filter(client: TestClient, approved: dict[str, Any]) -> None:
    mid = _score(client, MID_APPLICANT)
    client.post(
        f"/score/applications/{mid['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
    )
    _score(client, WEAK_APPLICANT)

    rows = client.get("/score/applications", params={"final_decision": "Approved"}).json()
    assert sorted(row["id"] for row in rows) == sorted(
        [approved["application_id"], mid["application_id"]]
    )


# --- EWS consistency -------------------------------------------------------------


def test_months_past_the_tenure_are_refused(
    client: TestClient, approved: dict[str, Any]
) -> None:
    tenure = STRONG_APPLICANT["tenure_months"]
    assert client.post("/ews/monitor", json=_month(approved, tenure)).status_code == 201

    response = client.post("/ews/monitor", json=_month(approved, tenure + 1))
    assert response.status_code == 422
    assert f"{tenure}-month tenure" in response.json()["detail"]


def test_correcting_the_alert_month_closes_the_alert(
    client: TestClient, approved: dict[str, Any]
) -> None:
    raised = client.post(
        "/ews/monitor", json=_month(approved, 3, installment_status="Default")
    ).json()
    assert raised["alert_triggered"] is True

    corrected = client.post("/ews/monitor", json=_month(approved, 3)).json()
    assert corrected["alert_triggered"] is False
    assert corrected["alert"]["id"] == raised["alert"]["id"]
    assert corrected["alert"]["alert_status"] == "Resolved"
    assert "month 3 was corrected" in corrected["alert"]["resolution_note"]
    assert client.get("/score/stats").json()["open_alerts"] == 0


def test_a_new_healthy_month_leaves_the_alert_for_an_officer(
    client: TestClient, approved: dict[str, Any]
) -> None:
    raised = client.post(
        "/ews/monitor", json=_month(approved, 3, installment_status="Default")
    ).json()
    recovered = client.post("/ews/monitor", json=_month(approved, 4)).json()

    assert recovered["alert"] is None
    alerts = client.get("/ews/alerts").json()
    assert [(a["id"], a["alert_status"]) for a in alerts] == [(raised["alert"]["id"], "Active")]


def test_correcting_a_healthy_month_does_not_close_an_earlier_alert(
    client: TestClient, approved: dict[str, Any]
) -> None:
    client.post("/ews/monitor", json=_month(approved, 3, installment_status="Default"))
    client.post("/ews/monitor", json=_month(approved, 4))
    corrected = client.post(
        "/ews/monitor", json=_month(approved, 4, data_source_primary="POS")
    ).json()

    assert corrected["alert"] is None
    assert client.get("/score/stats").json()["open_alerts"] == 1


def test_back_filling_an_older_month_never_rewrites_the_alert(
    client: TestClient, approved: dict[str, Any]
) -> None:
    raised = client.post(
        "/ews/monitor", json=_month(approved, 5, installment_status="Default")
    ).json()
    backfill = client.post(
        "/ews/monitor", json=_month(approved, 2, installment_status="Late 60-89")
    ).json()

    assert backfill["alert_triggered"] is False
    assert backfill["alert"] is None
    assert "latest month on file (month 5)" in backfill["recommended_action"]
    alert = client.get("/ews/alerts").json()[0]
    assert alert["current_score"] == raised["alert"]["current_score"]


def test_an_alert_under_review_cannot_change_hands(
    client: TestClient, db_session_factory, approved: dict[str, Any]
) -> None:
    alert = client.post(
        "/ews/monitor", json=_month(approved, 1, installment_status="Default")
    ).json()["alert"]
    db = db_session_factory()
    try:
        db.add(User(username="bob", hashed_password=hash_password("bob-password-1"), role="analyst"))
        db.commit()
    finally:
        db.close()

    assert client.patch(f"/ews/alerts/{alert['id']}/review").status_code == 200
    assert client.patch(f"/ews/alerts/{alert['id']}/review").status_code == 200  # same officer
    taken = client.patch(
        f"/ews/alerts/{alert['id']}/review", headers=bearer_header("bob", "analyst")
    )
    assert taken.status_code == 409
    assert "already being reviewed by admin" in taken.json()["detail"]
