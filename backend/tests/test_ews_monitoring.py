"""EWS 2.1 through the API: history, provenance, trend, state, alerts, lifecycle, roles."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from models.database import Alert, Application, AuditLog, EWSTracking, User
from services.audit_service import Action
from services.auth_service import hash_password
from tests.conftest import STRONG_APPLICANT, bearer_header, decide

pytestmark = pytest.mark.ews

REASON = "Owner showed the ledger; the bureau figure was a typo."
CASH = STRONG_APPLICANT["cash_flow_proxy"]


@pytest.fixture(name="facility")
def facility_fixture(client: TestClient) -> dict[str, Any]:
    scored = client.post("/score", json=STRONG_APPLICANT).json()
    decide(client, scored["application_id"])
    return {"id": scored["application_id"], "baseline": scored["risk_score"]}


@pytest.fixture(name="officers")
def officers_fixture(db_session_factory) -> dict[str, dict[str, str]]:
    db = db_session_factory()
    try:
        for name, role in (("ana", "analyst"), ("mona", "manager")):
            db.add(User(username=name, hashed_password=hash_password("long-password-1"), role=role))
        db.commit()
    finally:
        db.close()
    return {"analyst": bearer_header("ana", "analyst"), "manager": bearer_header("mona", "manager")}


def _month(facility: dict[str, Any], month: int, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "borrower_id": facility["id"],
        "month_number": month,
        "installment_status": "On Time",
        "bureau_balance": 2_000_000,
        "pos_cash_balance": CASH,
    }
    payload.update(fields)
    return payload


def _record(client: TestClient, facility, month: int, headers=None, **fields) -> dict[str, Any]:
    response = client.post("/ews/observations", json=_month(facility, month, **fields), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _audit(db_session_factory, **filters) -> list[AuditLog]:
    db = db_session_factory()
    try:
        statement = select(AuditLog).order_by(AuditLog.id)
        for name, value in filters.items():
            statement = statement.where(getattr(AuditLog, name) == value)
        return list(db.scalars(statement).all())
    finally:
        db.close()


# --- observation integrity ----------------------------------------------------------


def test_an_observation_records_who_when_and_in_which_request(
    client: TestClient, facility, officers
) -> None:
    body = _record(client, facility, 1, headers=officers["analyst"], days_late=0)
    row = body["tracking"]
    assert row["created_by"] == "ana"
    assert row["created_at"] is not None
    assert row["request_id"]
    assert row["observation_date"] == date.today().isoformat()
    assert row["record_status"] == "active"
    assert row["score_source"] == "ews_rule_adjusted"
    assert row["rule_score"] == row["monthly_score"]
    assert row["assessment"]["state"] == "NORMAL"
    assert body["ews_state"] == "NORMAL"


def test_a_recorded_month_cannot_be_recorded_again(client: TestClient, facility) -> None:
    _record(client, facility, 1)
    again = client.post("/ews/monitor", json=_month(facility, 1, bureau_balance=5))
    assert again.status_code == 409
    rows = client.get(f"/ews/facilities/{facility['id']}/observations").json()
    assert [r["bureau_balance"] for r in rows] == [2_000_000]


def test_the_database_allows_one_active_row_per_month(
    client: TestClient, facility, db_session_factory
) -> None:
    _record(client, facility, 1)
    db = db_session_factory()
    try:
        db.add(
            EWSTracking(
                borrower_id=facility["id"], month_number=1, installment_status="On Time",
                bureau_balance=1, pos_cash_balance=1, monthly_score=50,
                data_source_primary="ECIB", score_source="ews_rule_adjusted", record_status="active",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_a_correction_keeps_the_original_and_links_both(
    client: TestClient, facility, officers, db_session_factory
) -> None:
    original = _record(client, facility, 2, installment_status="Late 30-59", days_late=35)
    original_id = original["tracking"]["id"]
    body = {
        "installment_status": "On Time", "bureau_balance": 2_000_000,
        "pos_cash_balance": CASH, "correction_reason": REASON,
    }
    refused = client.post(f"/ews/observations/{original_id}/correct", json=body, headers=officers["analyst"])
    assert refused.status_code == 403

    corrected = client.post(f"/ews/observations/{original_id}/correct", json=body, headers=officers["manager"])
    assert corrected.status_code == 201, corrected.text
    new = corrected.json()["tracking"]
    assert new["supersedes_observation_id"] == original_id
    assert new["correction_reason"] == REASON
    assert new["observation_date"] == original["tracking"]["observation_date"]

    rows = client.get(f"/ews/facilities/{facility['id']}/observations").json()
    old = next(r for r in rows if r["id"] == original_id)
    assert old["installment_status"] == "Late 30-59" and old["days_late"] == 35
    assert old["record_status"] == "superseded"
    assert old["superseded_by_observation_id"] == new["id"]
    active = client.get(
        f"/ews/facilities/{facility['id']}/observations", params={"include_superseded": False}
    ).json()
    assert [r["id"] for r in active] == [new["id"]]

    again = client.post(f"/ews/observations/{original_id}/correct", json=body)
    assert again.status_code == 409 and str(new["id"]) in again.json()["detail"]


def test_days_late_must_fit_the_bucket_and_dates_cannot_be_future(
    client: TestClient, facility
) -> None:
    assert client.post("/ews/monitor", json=_month(facility, 1, days_late=45)).status_code == 422
    assert client.post(
        "/ews/monitor", json=_month(facility, 1, installment_status="Late 30-59", days_late=20)
    ).status_code == 422
    assert client.post(
        "/ews/monitor", json=_month(facility, 1, installment_status="Default", days_late=95)
    ).status_code == 201
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert client.post(
        "/ews/monitor", json=_month(facility, 2, observation_date=tomorrow)
    ).status_code == 422
    too_early = client.post(
        "/ews/monitor", json=_month(facility, 2, observation_date="2020-01-01")
    )
    assert too_early.status_code == 422 and "before application" in too_early.json()["detail"]


# --- score provenance -----------------------------------------------------------------


def test_an_override_needs_a_reason_and_a_manager(
    client: TestClient, facility, officers, db_session_factory
) -> None:
    no_reason = client.post("/ews/monitor", json=_month(facility, 1, current_score=40))
    assert no_reason.status_code == 422
    stray = client.post("/ews/monitor", json=_month(facility, 1, override_reason=REASON))
    assert stray.status_code == 422

    analyst = client.post(
        "/ews/monitor",
        json=_month(facility, 1, current_score=40, override_reason=REASON),
        headers=officers["analyst"],
    )
    assert analyst.status_code == 403
    denied = _audit(db_session_factory, action=Action.EWS_SCORE_OVERRIDE_DENIED)
    assert len(denied) == 1 and denied[0].username == "ana"
    assert client.get(f"/ews/facilities/{facility['id']}/observations").json() == []

    body = _record(
        client, facility, 1, headers=officers["manager"], current_score=40, override_reason=REASON
    )
    row = body["tracking"]
    assert row["score_source"] == "officer_override"
    assert row["score_source_label"] == "Officer Override"
    assert row["override_reason"] == REASON
    assert row["monthly_score"] == 40 and row["rule_score"] == facility["baseline"]
    assert body["score_source"] == "officer_override"

    entry = _audit(db_session_factory, action=Action.EWS_SCORE_OVERRIDDEN)[0]
    assert entry.username == "mona"
    assert entry.previous_state == {"monthly_score": facility["baseline"], "score_source": "ews_rule_adjusted"}
    assert entry.new_state["monthly_score"] == 40
    assert entry.new_state["override_reason"] == REASON


def test_a_rule_score_is_never_labelled_a_model_score(client: TestClient, facility) -> None:
    row = _record(client, facility, 1)["tracking"]
    assert row["score_source"] == "ews_rule_adjusted"
    assert "rules" in row["score_source_label"]
    points = client.get(f"/ews/facilities/{facility['id']}/trend").json()["points"]
    assert [(p["label"], p["score_source"]) for p in points] == [
        ("Baseline", "origination_assessment"),
        ("Month 1", "ews_rule_adjusted"),
    ]


# --- trend and state through the API -----------------------------------------------


def test_trend_needs_three_months(client: TestClient, facility) -> None:
    trend = client.get(f"/ews/facilities/{facility['id']}/trend").json()
    assert trend["direction"] == "Insufficient Data" and trend["observations"] == 0
    assert trend["points"][0]["label"] == "Baseline"

    _record(client, facility, 1)
    _record(client, facility, 2, pos_cash_balance=CASH * 0.7)
    two = client.get(f"/ews/facilities/{facility['id']}/trend").json()
    assert two["direction"] == "Insufficient Data"
    assert two["message"] == "Insufficient history for multi-month trend"
    assert two["recent_deterioration"] == pytest.approx(two["previous_score"] - two["latest_score"])

    _record(client, facility, 3, pos_cash_balance=CASH * 0.4)
    three = client.get(f"/ews/facilities/{facility['id']}/trend").json()
    assert three["direction"] == "Deteriorating"
    assert three["slope_points_per_month"] < -1
    assert three["message"] is None
    assert [p["label"] for p in three["points"]] == ["Baseline", "Month 1", "Month 2", "Month 3"]


def test_state_endpoint_explains_itself(client: TestClient, facility) -> None:
    _record(client, facility, 1)
    _record(client, facility, 2, installment_status="Late 30-59", days_late=31)
    state = client.get(f"/ews/facilities/{facility['id']}/state").json()
    assert state["state"] == "WARNING"
    assert "Latest month is Late 30-59." in state["state_reasons"]
    codes = [s["code"] for s in state["signals"]]
    assert "PAYMENT_DELAY_INCREASED" in codes
    assert all(s["evidence"] for s in state["signals"])
    assert state["recommended_actions"][0].startswith("Relationship manager")
    assert state["open_alert"]["severity"] == "WARNING"
    assert "not a default prediction" in state["note"]


def test_the_ews_never_changes_the_credit_decision(
    client: TestClient, facility, db_session_factory
) -> None:
    _record(client, facility, 1, installment_status="Default", days_late=120)
    application = client.get(f"/score/applications/{facility['id']}").json()
    assert application["decision_status"] == "Approved"
    assert application["risk_score"] == facility["baseline"]
    db = db_session_factory()
    try:
        assert db.get(Application, facility["id"]).decision_status == "Approved"
    finally:
        db.close()


def test_overview_counts_states_and_lists_facilities(client: TestClient, facility) -> None:
    other = client.post("/score", json={**STRONG_APPLICANT, "business_name": "Second Shop"}).json()
    decide(client, other["application_id"])
    second = {"id": other["application_id"], "baseline": other["risk_score"]}
    _record(client, facility, 1)
    _record(client, second, 1, installment_status="Late 60-89", days_late=70)

    body = client.get("/ews/overview").json()
    assert body["monitored_facilities"] == 2
    assert body["state_counts"] == {"NORMAL": 1, "WATCH": 0, "WARNING": 0, "CRITICAL": 1}
    assert body["open_alerts"] == 1 and body["overdue_actions"] == 0
    worst, calm = body["rows"]
    assert worst["facility_id"] == second["id"] and worst["state"] == "CRITICAL"
    assert worst["active_alerts"] == 1 and worst["trend_direction"] == "Insufficient Data"
    assert worst["last_observation_date"] == date.today().isoformat()
    assert calm["state"] == "NORMAL" and calm["active_alerts"] == 0
    assert body["methodology"]["score_drop_warning"] == 15


# --- alerts -------------------------------------------------------------------------


def test_an_alert_carries_severity_reasons_evidence_and_actions(client: TestClient, facility) -> None:
    alert = _record(client, facility, 1, installment_status="Late 60-89", days_late=65)["alert"]
    assert alert["severity"] == "CRITICAL"
    assert alert["alert_status"] == "Open"
    assert "PAYMENT_DELAY_INCREASED" in alert["reason_codes"]
    kinds = {item["kind"] for item in alert["evidence"]}
    assert kinds == {"signal", "state_rule"}
    assert any("Late 60-89" in item["evidence"] for item in alert["evidence"])
    assert alert["recommended_actions"][0].startswith("Refer the facility")
    assert alert["baseline_score"] == facility["baseline"]
    assert alert["is_open"] is True and alert["is_legacy"] is False


def test_one_open_alert_per_facility_is_enforced_by_the_database(
    client: TestClient, facility, db_session_factory
) -> None:
    alert = _record(client, facility, 1, installment_status="Default")["alert"]
    db = db_session_factory()
    try:
        db.add(
            Alert(borrower_id=facility["id"], baseline_score=1, current_score=1, score_drop=0,
                  estimated_days_to_default=0, alert_status="Acknowledged")
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()
    assert [a["id"] for a in client.get("/ews/alerts").json()] == [alert["id"]]


def test_repeated_months_update_one_alert_and_audit_only_changes(
    client: TestClient, facility, db_session_factory
) -> None:
    first = _record(client, facility, 1, installment_status="Late 30-59", days_late=40)["alert"]
    second = _record(client, facility, 2, installment_status="Late 30-59", days_late=50)["alert"]
    third = _record(client, facility, 3, installment_status="Default", days_late=95)["alert"]
    assert first["id"] == second["id"] == third["id"]
    assert (first["severity"], third["severity"]) == ("WARNING", "CRITICAL")
    actions = [
        e.action for e in _audit(db_session_factory, entity_type="ews_alert", entity_id=str(first["id"]))
    ]
    assert actions == [Action.EWS_ALERT_CREATED, Action.EWS_ALERT_UPDATED, Action.EWS_ALERT_ESCALATED]

    # An improving month does not lower the severity or close the alert.
    _record(client, facility, 4, installment_status="Late 30-59", days_late=30)
    alert = client.get(f"/ews/alerts/{first['id']}").json()
    assert alert["severity"] == "CRITICAL" and alert["alert_status"] == "Open"


def test_the_full_lifecycle_is_recorded(
    client: TestClient, facility, officers, db_session_factory
) -> None:
    alert = _record(client, facility, 1, installment_status="Default")["alert"]
    url = f"/ews/alerts/{alert['id']}"

    early = client.post(f"{url}/action-required", json={"action_note": "Visit the shop."})
    assert early.status_code == 409 and "Acknowledge" in early.json()["detail"]

    ack = client.post(f"{url}/acknowledge", json={"note": "Seen."}, headers=officers["manager"])
    assert ack.status_code == 200
    assert ack.json()["alert_status"] == "Acknowledged" and ack.json()["acknowledged_by"] == "mona"
    assert ack.json()["acknowledged_at"] is not None
    assert client.post(f"{url}/acknowledge").status_code == 409

    due = (date.today() + timedelta(days=2)).isoformat()
    assigned = client.post(f"{url}/assign", json={"assigned_to": "ana", "due_date": due})
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"] == "ana" and assigned.json()["assigned_by"] == "admin"
    assert assigned.json()["action_due_date"] == due
    assert client.post(f"{url}/assign", json={"assigned_to": "nobody"}).status_code == 422
    past = (date.today() - timedelta(days=1)).isoformat()
    assert client.post(f"{url}/due-date", json={"due_date": past}).status_code == 422

    action = client.post(f"{url}/action-required", json={"action_note": "Collect three statements."})
    assert action.status_code == 200
    assert action.json()["alert_status"] == "Action Required"
    assert action.json()["action_note"] == "Collect three statements."

    resolved = client.post(f"{url}/resolve", json={"note": "Statements show recovery."})
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["alert_status"] == "Resolved" and body["resolved_by"] == "admin"
    assert body["resolved_at"] is not None and body["is_open"] is False
    assert client.post(f"{url}/resolve", json={"note": "Again please."}).status_code == 409
    assert client.post(f"{url}/acknowledge").status_code == 409

    # Resolved alerts stay visible.
    assert [a["id"] for a in client.get("/ews/alerts").json()] == [alert["id"]]
    history = client.get(f"{url}/history").json()
    assert [h["action"] for h in history] == [
        Action.EWS_ALERT_CREATED,
        Action.EWS_ALERT_ACKNOWLEDGED,
        Action.EWS_ALERT_ASSIGNED,
        Action.EWS_ALERT_ACTION_REQUIRED,
        Action.EWS_ALERT_RESOLVED,
    ]
    assigned_entry = history[2]
    assert assigned_entry["previous_state"]["assigned_to"] is None
    assert assigned_entry["new_state"]["assigned_to"] == "ana"
    assert history[1]["username"] == "mona" and history[1]["details"]["note"] == "Seen."


def test_an_alert_can_be_dismissed_with_a_reason(client: TestClient, facility) -> None:
    alert = _record(client, facility, 1, installment_status="Default")["alert"]
    assert client.post(f"/ews/alerts/{alert['id']}/dismiss", json={"note": "x"}).status_code == 422
    dismissed = client.post(
        f"/ews/alerts/{alert['id']}/dismiss", json={"note": "Raised on a typing error."}
    )
    assert dismissed.status_code == 200 and dismissed.json()["alert_status"] == "Dismissed"
    assert client.get("/ews/alerts", params={"alert_status": "Dismissed"}).json()[0]["id"] == alert["id"]
    # A later breach opens a new alert.
    relapse = _record(client, facility, 2, installment_status="Default")["alert"]
    assert relapse["id"] != alert["id"]


def test_an_overdue_action_is_flagged(
    client: TestClient, facility, db_session_factory
) -> None:
    alert = _record(client, facility, 1, installment_status="Default")["alert"]
    db = db_session_factory()
    try:
        db.execute(
            update(Alert)
            .where(Alert.id == alert["id"])
            .values(action_due_date=date.today() - timedelta(days=3))
        )
        db.commit()
    finally:
        db.close()
    assert client.get(f"/ews/alerts/{alert['id']}").json()["is_overdue"] is True
    overview = client.get("/ews/overview").json()
    assert overview["overdue_actions"] == 1 and overview["rows"][0]["overdue"] is True


def test_alert_filters(client: TestClient, facility) -> None:
    _record(client, facility, 1, installment_status="Late 30-59", days_late=31)
    assert len(client.get("/ews/alerts", params={"severity": "WARNING"}).json()) == 1
    assert client.get("/ews/alerts", params={"severity": "CRITICAL"}).json() == []
    assert len(client.get("/ews/alerts", params={"open_only": True}).json()) == 1
    assert len(client.get("/ews/alerts", params={"facility_id": facility["id"]}).json()) == 1
    assert client.get("/ews/alerts", params={"alert_status": "Active"}).status_code == 422


# --- authorisation ------------------------------------------------------------------


def test_an_analyst_records_and_reads_but_does_not_manage_alerts(
    client: TestClient, facility, officers
) -> None:
    analyst = officers["analyst"]
    alert = _record(client, facility, 1, headers=analyst, installment_status="Default")["alert"]
    url = f"/ews/alerts/{alert['id']}"
    for method, path, body in (
        ("post", f"{url}/acknowledge", None),
        ("post", f"{url}/assign", {"assigned_to": "ana"}),
        ("post", f"{url}/due-date", {"due_date": date.today().isoformat()}),
        ("post", f"{url}/action-required", {"action_note": "Do something."}),
        ("post", f"{url}/resolve", {"note": "Closing it myself."}),
        ("post", f"{url}/dismiss", {"note": "Closing it myself."}),
        ("patch", f"{url}/review", None),
    ):
        response = getattr(client, method)(path, json=body, headers=analyst)
        assert response.status_code == 403, path
    for path in (
        "/ews/alerts", url, f"{url}/history", "/ews/overview", "/ews/methodology",
        f"/ews/facilities/{facility['id']}/trend", f"/ews/facilities/{facility['id']}/state",
        f"/ews/facilities/{facility['id']}/timeline", f"/ews/facilities/{facility['id']}/observations",
    ):
        assert client.get(path, headers=analyst).status_code == 200, path
    assert client.get(f"{url}").json()["alert_status"] == "Open"


def test_every_ews_route_needs_a_signed_in_officer(anonymous_client: TestClient) -> None:
    for path in ("/ews/overview", "/ews/alerts", "/ews/methodology", "/ews/facilities/1/trend"):
        assert anonymous_client.get(path).status_code == 401, path


# --- timeline -----------------------------------------------------------------------


def test_the_timeline_holds_only_stored_events(
    client: TestClient, facility, db_session_factory
) -> None:
    raised = _record(client, facility, 1, installment_status="Default")
    client.post(f"/ews/alerts/{raised['alert']['id']}/acknowledge")
    timeline = client.get(f"/ews/facilities/{facility['id']}/timeline").json()
    kinds = [event["kind"] for event in timeline["events"]]
    assert kinds[0] == Action.APPLICATION_CREATED
    assert Action.OFFICER_DECISION in kinds
    assert kinds[-3:] == [Action.EWS_OBSERVATION_CREATED, Action.EWS_ALERT_CREATED, Action.EWS_ALERT_ACKNOWLEDGED]
    assert all(event["source"] == "audit_log" for event in timeline["events"])
    assert timeline["note"] is None
    stored = _audit(db_session_factory)
    related = [
        e for e in stored
        if (e.entity_type, e.entity_id) in {
            ("application", str(facility["id"])),
            ("ews_observation", str(raised["tracking"]["id"])),
            ("ews_alert", str(raised["alert"]["id"])),
        }
    ]
    assert len(related) == len(timeline["events"])


def test_rows_from_before_the_audit_trail_are_marked_as_such(
    client: TestClient, facility, db_session_factory
) -> None:
    db = db_session_factory()
    try:
        db.add(
            EWSTracking(
                borrower_id=facility["id"], month_number=1, installment_status="On Time",
                bureau_balance=1, pos_cash_balance=1, monthly_score=70,
                data_source_primary="ECIB", score_source="legacy_unknown", record_status="active",
            )
        )
        db.commit()
    finally:
        db.close()
    timeline = client.get(f"/ews/facilities/{facility['id']}/timeline").json()
    legacy = [e for e in timeline["events"] if e["source"] == "record"]
    assert len(legacy) == 1
    assert legacy[0]["occurred_at"] is None and "before the audit trail" in legacy[0]["detail"]
    assert "predate the audit trail" in timeline["note"]
    row = client.get(f"/ews/facilities/{facility['id']}/observations").json()[0]
    assert row["is_legacy"] is True and row["score_source_label"].startswith("Unknown")
