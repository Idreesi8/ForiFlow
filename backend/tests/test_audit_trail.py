"""The audit trail: what is written, by whom, and that it cannot be changed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DatabaseError

from models.database import AuditLog, AuditLogImmutable, User
from services import audit_service
from services.audit_service import Action, AuditContext
from services.auth_service import hash_password
from tests.conftest import (
    MID_APPLICANT,
    STRONG_APPLICANT,
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_USERNAME,
    bearer_header,
    decide,
)

NOTE = "Clean receipts for five years; facility is modest against turnover."


def _entries(db_session_factory, **filters) -> list[AuditLog]:
    db = db_session_factory()
    try:
        statement = select(AuditLog).order_by(AuditLog.id)
        for name, value in filters.items():
            statement = statement.where(getattr(AuditLog, name) == value)
        return list(db.scalars(statement).all())
    finally:
        db.close()


def _officer(db_session_factory, username: str, role: str) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(User(username=username, hashed_password=hash_password("a-long-password"), role=role))
        db.commit()
    finally:
        db.close()
    return bearer_header(username=username, role=role)


def _month(client: TestClient, application_id: int, status: str = "On Time", **extra):
    return client.post(
        "/ews/monitor",
        json={
            "borrower_id": application_id,
            "month_number": 1,
            "installment_status": status,
            "bureau_balance": 1,
            "pos_cash_balance": 10_000_000,
            **extra,
        },
    )


# --- what gets written --------------------------------------------------------------


def test_scoring_writes_the_borrower_application_score_and_explanation(
    client: TestClient, db_session_factory
) -> None:
    body = client.post("/score", json=STRONG_APPLICANT).json()
    application_id = str(body["application_id"])

    actions = [entry.action for entry in _entries(db_session_factory)]
    for expected in (
        Action.BORROWER_CREATED,
        Action.MODEL_REGISTERED,
        Action.APPLICATION_CREATED,
        Action.APPLICATION_SCORED,
        Action.RECOMMENDATION_GENERATED,
        Action.EXPLANATION_GENERATED,
    ):
        assert expected in actions

    scored = _entries(db_session_factory, action=Action.APPLICATION_SCORED)[0]
    assert scored.entity_type == "application" and scored.entity_id == application_id
    assert scored.new_state["risk_score"] == body["risk_score"]
    # The score is the model's; the recommendation has its own entry.
    assert "decision" not in scored.new_state
    recommended = _entries(db_session_factory, action=Action.RECOMMENDATION_GENERATED)[0]
    assert recommended.new_state["recommendation"] == body["recommendation"]
    assert recommended.new_state["decision_status"] == "Pending"
    assert scored.details["model_version"] == body["model_version"]
    assert scored.details["scoring_engine"] == "surrogate"


def test_entries_name_the_officer_who_acted(client: TestClient, db_session_factory) -> None:
    analyst = _officer(db_session_factory, "analyst1", "analyst")
    client.post("/score", json=STRONG_APPLICANT, headers=analyst)

    db = db_session_factory()
    try:
        user = db.scalar(select(User).where(User.username == "analyst1"))
    finally:
        db.close()
    scored = _entries(db_session_factory, action=Action.APPLICATION_SCORED)[0]
    assert (scored.username, scored.role, scored.user_id) == ("analyst1", "analyst", user.id)
    assert scored.occurred_at is not None


def test_every_entry_of_one_request_shares_its_request_id(
    client: TestClient, db_session_factory
) -> None:
    response = client.post("/score", json=STRONG_APPLICANT)
    request_id = response.headers["X-Request-ID"]

    mine = _entries(db_session_factory, request_id=request_id)
    assert {entry.action for entry in mine} >= {
        Action.APPLICATION_CREATED,
        Action.APPLICATION_SCORED,
    }
    assert all(entry.ip_address for entry in mine)


def test_a_safe_request_id_is_kept_and_an_unsafe_one_replaced(client: TestClient) -> None:
    kept = client.get("/health", headers={"X-Request-ID": "trace-1234.abcd"})
    assert kept.headers["X-Request-ID"] == "trace-1234.abcd"

    replaced = client.get("/health", headers={"X-Request-ID": "x'; DROP TABLE audit_logs;--"})
    assert replaced.headers["X-Request-ID"] != "x'; DROP TABLE audit_logs;--"
    assert len(replaced.headers["X-Request-ID"]) == 32


def test_login_success_and_failure_are_both_recorded_without_the_password(
    anonymous_client: TestClient, db_session_factory
) -> None:
    ok = anonymous_client.post(
        "/auth/login", json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD}
    )
    assert ok.status_code == 200
    bad = anonymous_client.post(
        "/auth/login", json={"username": "intruder", "password": "wrong-password-123"}
    )
    assert bad.status_code == 401

    success = _entries(db_session_factory, action=Action.LOGIN)[0]
    failure = _entries(db_session_factory, action=Action.LOGIN_FAILED)[0]
    assert success.username == TEST_ADMIN_USERNAME and success.role == "admin"
    assert failure.username == "intruder" and failure.user_id is None

    everything = str(
        [
            (e.previous_state, e.new_state, e.details, e.username)
            for e in _entries(db_session_factory)
        ]
    )
    assert TEST_ADMIN_PASSWORD not in everything
    assert "wrong-password-123" not in everything
    assert ok.json()["access_token"] not in everything


def test_officer_decision_keeps_before_and_after(client: TestClient, db_session_factory) -> None:
    pending = client.post("/score", json=MID_APPLICANT).json()
    client.post(
        f"/score/applications/{pending['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
    )

    entry = _entries(db_session_factory, action=Action.OFFICER_DECISION)[0]
    assert entry.previous_state == {
        "decision": "Manual Review",
        "review_decision": None,
        "decision_status": "Pending",
    }
    assert entry.new_state["review_decision"] == "Approved"
    assert entry.new_state["review_note"] == NOTE
    assert entry.new_state["reviewed_by"] == TEST_ADMIN_USERNAME


def test_a_refused_approval_is_recorded_even_though_the_request_fails(
    client: TestClient, db_session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1000000")
    manager = _officer(db_session_factory, "manager1", "manager")
    pending = client.post("/score", json=MID_APPLICANT).json()

    denied = client.post(
        f"/score/applications/{pending['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
        headers=manager,
    )
    assert denied.status_code == 403

    entry = _entries(db_session_factory, action=Action.APPROVAL_DENIED)[0]
    assert entry.username == "manager1"
    assert entry.details["manager_approval_limit_pkr"] == 1_000_000
    assert _entries(db_session_factory, action=Action.OFFICER_DECISION) == []


def test_a_corrected_month_keeps_the_figures_it_replaced(
    client: TestClient, db_session_factory
) -> None:
    application_id = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    decide(client, application_id)
    assert _month(client, application_id, "Late 60-89", amount_paid_pkr=1000).status_code == 201
    assert _month(client, application_id, "On Time", amount_paid_pkr=66_000).status_code == 201

    created = _entries(db_session_factory, action=Action.EWS_OBSERVATION_CREATED)
    updated = _entries(db_session_factory, action=Action.EWS_OBSERVATION_UPDATED)
    assert len(created) == 1 and len(updated) == 1
    assert created[0].previous_state is None
    # The row itself now says On Time; the trail still has what it said before.
    assert updated[0].previous_state["installment_status"] == "Late 60-89"
    assert updated[0].previous_state["amount_paid_pkr"] == 1000
    assert updated[0].new_state["installment_status"] == "On Time"
    assert updated[0].details["application_id"] == application_id


def test_an_alert_is_audited_from_raised_to_resolved(
    client: TestClient, db_session_factory
) -> None:
    application_id = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    decide(client, application_id)
    alert = _month(client, application_id, "Default").json()["alert"]
    client.patch(f"/ews/alerts/{alert['id']}/review")
    client.patch(f"/ews/alerts/{alert['id']}/resolve", json={"note": "Handed to remedial."})

    actions = [
        entry.action
        for entry in _entries(db_session_factory, entity_type="ews_alert", entity_id=str(alert["id"]))
    ]
    assert actions == [Action.EWS_ALERT_CREATED, Action.EWS_ALERT_TAKEN, Action.EWS_ALERT_RESOLVED]
    resolved = _entries(db_session_factory, action=Action.EWS_ALERT_RESOLVED)[0]
    assert resolved.previous_state["alert_status"] == "In Review"
    assert resolved.new_state["alert_status"] == "Resolved"
    assert resolved.new_state["resolution_note"] == "Handed to remedial."


def test_an_alert_closed_by_a_correction_is_audited(
    client: TestClient, db_session_factory
) -> None:
    application_id = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    decide(client, application_id)
    _month(client, application_id, "Default")
    _month(client, application_id, "On Time")

    assert len(_entries(db_session_factory, action=Action.EWS_ALERT_AUTO_RESOLVED)) == 1


def test_recomputing_an_explanation_is_recorded_and_reading_one_is_not(
    client: TestClient, db_session_factory, scored_application_id: int
) -> None:
    before = len(_entries(db_session_factory))
    assert client.get(f"/explain/{scored_application_id}").status_code == 200
    assert client.post(f"/explain/{scored_application_id}").status_code == 200  # stored copy
    assert len(_entries(db_session_factory)) == before

    assert client.post(f"/explain/{scored_application_id}?refresh=true").status_code == 200
    entry = _entries(db_session_factory, action=Action.EXPLANATION_RECOMPUTED)[0]
    assert entry.entity_id == str(scored_application_id)
    assert entry.details["scored_with"] == entry.details["explained_with"]
    assert entry.details["stored"] is False


def test_creating_an_officer_is_recorded_without_the_password(
    client: TestClient, db_session_factory
) -> None:
    client.post(
        "/auth/users",
        json={"username": "analyst9", "password": "a-very-long-password", "role": "analyst"},
    )
    entry = _entries(db_session_factory, action=Action.USER_CREATED)[0]
    assert entry.new_state == {"username": "analyst9", "role": "analyst"}
    assert "a-very-long-password" not in str(entry.details) + str(entry.new_state)


# --- nothing secret gets in ---------------------------------------------------------


def test_scrub_removes_credentials_at_any_depth() -> None:
    cleaned = audit_service.scrub(
        {
            "username": "ali",
            "password": "hunter2-hunter2",
            "nested": {"Authorization": "Bearer abc", "api_key": "k", "note": "fine"},
            "items": [{"access_token": "t", "amount": 5}],
        }
    )
    assert cleaned["username"] == "ali"
    assert cleaned["password"] == audit_service.REDACTED
    assert cleaned["nested"] == {
        "Authorization": audit_service.REDACTED,
        "api_key": audit_service.REDACTED,
        "note": "fine",
    }
    assert cleaned["items"] == [{"access_token": audit_service.REDACTED, "amount": 5}]


def test_record_scrubs_what_it_is_given(db_session_factory) -> None:
    db = db_session_factory()
    try:
        audit_service.record(
            db,
            action="test.event",
            entity_type="test",
            details={"jwt_secret": "s3cr3t-value", "ok": 1},
            context=AuditContext(ip_address="10.0.0.9", request_id="abc12345"),
        )
        db.commit()
    finally:
        db.close()
    entry = _entries(db_session_factory, action="test.event")[0]
    assert entry.details == {"jwt_secret": audit_service.REDACTED, "ok": 1}
    assert (entry.username, entry.ip_address, entry.request_id) == (
        "system",
        "10.0.0.9",
        "abc12345",
    )


# --- append-only --------------------------------------------------------------------


def test_the_orm_refuses_to_update_or_delete_an_entry(
    client: TestClient, db_session_factory
) -> None:
    client.post("/score", json=STRONG_APPLICANT)

    db = db_session_factory()
    try:
        entry = db.scalars(select(AuditLog)).first()
        entry.username = "someone-else"
        with pytest.raises(AuditLogImmutable):
            db.commit()
        db.rollback()

        entry = db.scalars(select(AuditLog)).first()
        db.delete(entry)
        with pytest.raises(AuditLogImmutable):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_the_database_itself_refuses_bulk_and_raw_changes(
    client: TestClient, db_session_factory
) -> None:
    client.post("/score", json=STRONG_APPLICANT)
    before = [(e.id, e.username, e.action) for e in _entries(db_session_factory)]
    assert before

    for statement in (
        update(AuditLog).values(username="someone-else"),
        delete(AuditLog),
        text("UPDATE audit_logs SET action = 'x'"),
        text("DELETE FROM audit_logs WHERE id > 0"),
    ):
        db = db_session_factory()
        try:
            with pytest.raises(DatabaseError, match="append-only"):
                db.execute(statement)
                db.commit()
            db.rollback()
        finally:
            db.close()

    assert [(e.id, e.username, e.action) for e in _entries(db_session_factory)] == before


def test_no_route_can_change_or_remove_audit_entries(client: TestClient) -> None:
    routes = client.get("/openapi.json").json()["paths"]
    audit_routes = {path: sorted(methods) for path, methods in routes.items() if "/audit" in path}

    assert audit_routes == {"/audit/logs": ["get"]}
    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/audit/logs").status_code == 405
    assert client.delete("/audit/logs/1").status_code in (404, 405)


def test_normal_work_only_ever_adds_entries(client: TestClient, db_session_factory) -> None:
    seen: list[tuple[int, str]] = []

    def check_grew() -> None:
        now = [(e.id, e.action) for e in _entries(db_session_factory)]
        assert now[: len(seen)] == seen and len(now) > len(seen)
        seen[:] = now

    pending = client.post("/score", json=MID_APPLICANT).json()
    check_grew()
    client.post(
        f"/score/applications/{pending['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
    )
    check_grew()
    alert = _month(client, pending["application_id"], "Default").json()["alert"]
    check_grew()
    client.patch(f"/ews/alerts/{alert['id']}/resolve", json={"note": "Handed to remedial."})
    check_grew()
    client.patch(f"/borrowers/{pending['borrower_public_id']}", json={"status": "inactive"})
    check_grew()


# --- reading the trail --------------------------------------------------------------


def test_only_an_admin_reads_the_trail(client: TestClient, db_session_factory) -> None:
    client.post("/score", json=STRONG_APPLICANT)
    manager = _officer(db_session_factory, "manager1", "manager")
    analyst = _officer(db_session_factory, "analyst1", "analyst")

    assert client.get("/audit/logs", headers=manager).status_code == 403
    assert client.get("/audit/logs", headers=analyst).status_code == 403
    assert client.get("/audit/logs", headers={"Authorization": ""}).status_code == 401
    assert client.get("/audit/logs").status_code == 200


def test_the_trail_is_newest_first_and_filters(client: TestClient) -> None:
    first = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    second = client.post("/score", json=MID_APPLICANT).json()["application_id"]

    everything = client.get("/audit/logs").json()
    assert [row["id"] for row in everything] == sorted((row["id"] for row in everything), reverse=True)

    scored = client.get("/audit/logs", params={"action": "application.scored"}).json()
    assert [row["entity_id"] for row in scored] == [str(second), str(first)]

    one = client.get(
        "/audit/logs", params={"entity_type": "application", "entity_id": str(first)}
    ).json()
    assert {row["action"] for row in one} == {
        "application.created",
        "application.scored",
        "recommendation.generated",
        "explanation.generated",
    }
    assert client.get("/audit/logs", params={"username": "nobody"}).json() == []
    assert len(client.get("/audit/logs", params={"limit": 2}).json()) == 2
