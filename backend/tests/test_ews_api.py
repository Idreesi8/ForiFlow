"""API tests for the ``/ews`` router and the monitoring service."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from schemas import InstallmentStatus
from services.ews_service import ALERT_SCORE_DROP_THRESHOLD, EWSService
from tests.conftest import STRONG_APPLICANT

pytestmark = pytest.mark.ews


@pytest.fixture(name="borrower")
def borrower_fixture(client: TestClient) -> dict[str, Any]:
    """Score a healthy applicant and return its id plus baseline score."""
    response = client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201, response.text
    body = response.json()
    return {"id": body["application_id"], "baseline": body["risk_score"]}


def _healthy_month(borrower_id: int, month: int = 1, **overrides: Any) -> dict[str, Any]:
    """Build a monitoring payload that keeps the borrower at its baseline."""
    payload: dict[str, Any] = {
        "borrower_id": borrower_id,
        "month_number": month,
        "installment_status": InstallmentStatus.ON_TIME.value,
        "bureau_balance": 2_000_000,
        "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"],
        "data_source_primary": "ECIB",
    }
    payload.update(overrides)
    return payload


def test_healthy_month_records_tracking_without_alert(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """A performing borrower stays at baseline and raises no alert."""
    response = client.post("/ews/monitor", json=_healthy_month(borrower["id"]))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["baseline_score"] == borrower["baseline"]
    assert body["current_score"] == borrower["baseline"]
    assert body["score_drop"] == 0.0
    assert body["alert_triggered"] is False
    assert body["alert"] is None
    assert body["estimated_days_to_default"] is None
    assert body["tracking"]["month_number"] == 1
    assert body["tracking"]["monthly_score"] == borrower["baseline"]
    assert client.get("/ews/alerts").json() == []


def test_drop_of_exactly_the_threshold_does_not_alert(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """The alert fires strictly above 15 points, not at 15."""
    payload = _healthy_month(
        borrower["id"], current_score=borrower["baseline"] - ALERT_SCORE_DROP_THRESHOLD
    )
    body = client.post("/ews/monitor", json=payload).json()

    assert body["score_drop"] == pytest.approx(ALERT_SCORE_DROP_THRESHOLD)
    assert body["alert_triggered"] is False
    assert body["alert"] is None


def test_drop_above_threshold_triggers_alert(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """A drop beyond 15 points creates an active alert with a runway estimate."""
    payload = _healthy_month(
        borrower["id"], month=2, current_score=borrower["baseline"] - 20
    )
    response = client.post("/ews/monitor", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["alert_triggered"] is True
    assert body["score_drop"] == pytest.approx(20.0)
    assert body["alert_threshold"] == ALERT_SCORE_DROP_THRESHOLD
    assert body["estimated_days_to_default"] > 0
    assert body["alert"]["alert_status"] == "Active"
    assert body["alert"]["borrower_id"] == borrower["id"]
    assert body["recommended_action"]

    alerts = client.get("/ews/alerts", params={"alert_status": "Active"}).json()
    assert len(alerts) == 1
    assert alerts[0]["score_drop"] == pytest.approx(20.0)


def test_delinquency_alone_triggers_an_alert(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """A 60-89 day delinquency breaches the threshold without other signals."""
    payload = _healthy_month(
        borrower["id"], month=3, installment_status=InstallmentStatus.LATE_60_89.value
    )
    body = client.post("/ews/monitor", json=payload).json()

    assert body["alert_triggered"] is True
    assert body["score_drop"] > ALERT_SCORE_DROP_THRESHOLD
    assert 0 < body["estimated_days_to_default"] <= 45


def test_collapsing_pos_inflows_reduce_the_monthly_score(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """Shrinking POS settlements are an early liquidity warning."""
    healthy = client.post("/ews/monitor", json=_healthy_month(borrower["id"], 1)).json()
    stressed = client.post(
        "/ews/monitor", json=_healthy_month(borrower["id"], 2, pos_cash_balance=50_000)
    ).json()

    assert stressed["current_score"] < healthy["current_score"]


def test_default_status_reports_zero_runway(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """A defaulted facility has no remaining runway and escalates immediately."""
    payload = _healthy_month(
        borrower["id"], month=6, installment_status=InstallmentStatus.DEFAULT.value
    )
    body = client.post("/ews/monitor", json=payload).json()

    assert body["alert_triggered"] is True
    assert body["estimated_days_to_default"] == 0
    assert "remedial" in body["recommended_action"].lower()


def test_resubmitting_a_month_overwrites_the_observation(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """A corrected typed bureau balance updates the month instead of duplicating it."""
    client.post("/ews/monitor", json=_healthy_month(borrower["id"], 4))
    client.post(
        "/ews/monitor",
        json=_healthy_month(borrower["id"], 4, data_source_primary="POS"),
    )

    history = client.get(f"/ews/borrowers/{borrower['id']}/history").json()
    assert len(history) == 1
    assert history[0]["data_source_primary"] == "POS"


def test_repeated_deterioration_reuses_the_open_alert(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """An unresolved alert is updated in place rather than duplicated."""
    first = client.post(
        "/ews/monitor",
        json=_healthy_month(borrower["id"], 2, current_score=borrower["baseline"] - 18),
    ).json()
    second = client.post(
        "/ews/monitor",
        json=_healthy_month(borrower["id"], 3, current_score=borrower["baseline"] - 30),
    ).json()

    assert second["alert"]["id"] == first["alert"]["id"]
    assert second["alert"]["score_drop"] == pytest.approx(30.0)
    assert len(client.get("/ews/alerts").json()) == 1


def test_resolving_an_alert_stamps_the_resolution_time(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """Resolved alerts leave the active queue and a later relapse opens a new one."""
    opened = client.post(
        "/ews/monitor",
        json=_healthy_month(borrower["id"], 2, current_score=borrower["baseline"] - 25),
    ).json()["alert"]

    resolved = client.patch(f"/ews/alerts/{opened['id']}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["alert_status"] == "Resolved"
    assert resolved.json()["resolved_at"] is not None
    assert client.get("/ews/alerts", params={"alert_status": "Active"}).json() == []

    relapse = client.post(
        "/ews/monitor",
        json=_healthy_month(borrower["id"], 5, current_score=borrower["baseline"] - 40),
    ).json()
    assert relapse["alert"]["id"] != opened["id"]


def test_history_is_ordered_by_month(
    client: TestClient, borrower: dict[str, Any]
) -> None:
    """The dashboard trend chart consumes months in ascending order."""
    for month in (3, 1, 2):
        client.post("/ews/monitor", json=_healthy_month(borrower["id"], month))

    history = client.get(f"/ews/borrowers/{borrower['id']}/history").json()
    assert [record["month_number"] for record in history] == [1, 2, 3]


def test_monitoring_unknown_borrower_returns_404(client: TestClient) -> None:
    """Monitoring requires an originating application."""
    response = client.post("/ews/monitor", json=_healthy_month(9876))

    assert response.status_code == 404
    assert "9876" in response.json()["detail"]


def test_resolving_unknown_alert_returns_404(client: TestClient) -> None:
    """Resolving a missing alert must fail cleanly."""
    assert client.patch("/ews/alerts/555/resolve").status_code == 404


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("month_number", 0),
        ("month_number", 120),
        ("installment_status", "Sometimes Late"),
        ("bureau_balance", -1),
        ("current_score", 140),
    ],
)
def test_invalid_monitoring_payloads_are_rejected(
    client: TestClient, borrower: dict[str, Any], field: str, value: object
) -> None:
    """Surveillance payloads are validated before touching the database."""
    payload = _healthy_month(borrower["id"], **{field: value})

    assert client.post("/ews/monitor", json=payload).status_code == 422


def test_service_rejects_a_non_positive_threshold() -> None:
    """A threshold of zero or less would alert on every observation."""
    with pytest.raises(ValueError):
        EWSService(alert_threshold=0)


def test_runway_shortens_as_the_drop_deepens() -> None:
    """Faster deterioration must produce a shorter runway estimate."""
    service = EWSService()
    mild = service.estimate_days_to_default(16, InstallmentStatus.LATE_1_29)
    severe = service.estimate_days_to_default(45, InstallmentStatus.LATE_1_29)

    assert severe < mild
    assert severe >= 7
