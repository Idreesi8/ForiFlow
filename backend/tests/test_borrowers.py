"""Borrowers: one business, many applications, and its history."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models.database import Application, AuditLog, Borrower, User
from services.audit_service import Action
from services.auth_service import hash_password
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT, bearer_header

CNIC = "35202-1234567-1"
CNIC_DIGITS = "3520212345671"
NOTE = "Clean receipts for five years; facility is modest against turnover."


def _score(client: TestClient, payload: dict, **extra) -> dict:
    response = client.post("/score", json={**payload, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _manager(db_session_factory) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(User(username="manager1", hashed_password=hash_password("a-long-password"), role="manager"))
        db.commit()
    finally:
        db.close()
    return bearer_header(username="manager1", role="manager")


# --- linkage at scoring -------------------------------------------------------------


def test_an_application_without_a_borrower_opens_one(client: TestClient) -> None:
    body = _score(client, STRONG_APPLICANT, contact_phone="+923001234567", business_sector="Retail")

    assert body["borrower_created"] is True
    assert body["borrower_public_id"] == f"BRW-{body['borrower_id']:06d}"

    borrower = client.get(f"/borrowers/{body['borrower_public_id']}").json()
    assert borrower["business_name"] == STRONG_APPLICANT["business_name"]
    assert borrower["owner_name"] == STRONG_APPLICANT["applicant_name"]
    assert borrower["contact_phone"] == "+923001234567"
    assert borrower["business_sector"] == "Retail"
    assert borrower["years_in_operation"] == STRONG_APPLICANT["years_in_operation"]
    assert borrower["status"] == "active"
    assert borrower["identifier_type"] is None and borrower["identifier_masked"] is None

    stored = client.get(f"/score/applications/{body['application_id']}").json()
    assert stored["borrower_id"] == body["borrower_id"]
    assert stored["borrower_public_id"] == body["borrower_public_id"]


def test_the_same_name_alone_never_links_two_applications(client: TestClient) -> None:
    first = _score(client, STRONG_APPLICANT)
    second = _score(client, STRONG_APPLICANT)

    assert first["borrower_id"] != second["borrower_id"]
    assert second["borrower_created"] is True


def test_naming_the_borrower_files_a_second_application_under_it(client: TestClient) -> None:
    first = _score(client, STRONG_APPLICANT)
    second = _score(
        client,
        {**STRONG_APPLICANT, "loan_amount_pkr": 900_000},
        borrower_public_id=first["borrower_public_id"],
    )

    assert second["borrower_created"] is False
    assert second["borrower_id"] == first["borrower_id"]
    assert second["application_id"] != first["application_id"]


def test_the_same_identifier_finds_the_same_borrower(client: TestClient) -> None:
    first = _score(
        client, STRONG_APPLICANT, borrower_identifier_type="CNIC", borrower_identifier=CNIC
    )
    # Typed without dashes the second time, and under a different trading name.
    second = _score(
        client,
        {**MID_APPLICANT, "business_name": "Siddiqui Fabrics"},
        borrower_identifier_type="CNIC",
        borrower_identifier=CNIC_DIGITS,
    )

    assert first["borrower_created"] is True and second["borrower_created"] is False
    assert second["borrower_id"] == first["borrower_id"]
    borrower = client.get(f"/borrowers/{first['borrower_id']}").json()
    # The borrower keeps the name it was opened with; the application keeps its own.
    assert borrower["business_name"] == STRONG_APPLICANT["business_name"]
    assert borrower["identifier_type"] == "CNIC"
    assert borrower["identifier_masked"] == "*********5671"
    assert CNIC_DIGITS not in str(borrower)


def test_a_later_application_refreshes_the_borrower_and_audits_it(
    client: TestClient, db_session_factory
) -> None:
    first = _score(client, STRONG_APPLICANT, contact_phone="+923001234567")
    _score(
        client,
        {**STRONG_APPLICANT, "years_in_operation": 13},
        borrower_public_id=first["borrower_public_id"],
        contact_phone="+923009999999",
    )

    borrower = client.get(f"/borrowers/{first['borrower_id']}").json()
    assert borrower["contact_phone"] == "+923009999999"
    assert borrower["years_in_operation"] == 13

    db = db_session_factory()
    try:
        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == Action.BORROWER_UPDATED)
        ).one()
    finally:
        db.close()
    assert entry.previous_state == {"contact_phone": "+923001234567", "years_in_operation": 12.0}
    assert entry.new_state == {"contact_phone": "+923009999999", "years_in_operation": 13.0}


def test_an_unknown_borrower_reference_is_refused_and_nothing_is_stored(
    client: TestClient,
) -> None:
    response = client.post("/score", json={**STRONG_APPLICANT, "borrower_public_id": "BRW-000999"})

    assert response.status_code == 404
    assert client.get("/score/applications").json() == []
    assert client.get("/borrowers").json() == []


def test_a_borrower_reference_with_someone_elses_identifier_is_refused(
    client: TestClient,
) -> None:
    first = _score(
        client, STRONG_APPLICANT, borrower_identifier_type="CNIC", borrower_identifier=CNIC
    )
    response = client.post(
        "/score",
        json={
            **MID_APPLICANT,
            "borrower_public_id": first["borrower_public_id"],
            "borrower_identifier_type": "CNIC",
            "borrower_identifier": "3520299999999",
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"borrower_identifier": CNIC},  # no type
        {"borrower_identifier_type": "CNIC"},  # no value
        {"borrower_identifier_type": "CNIC", "borrower_identifier": "12345"},
        {"borrower_identifier_type": "NTN", "borrower_identifier": CNIC},
        {"borrower_identifier_type": "PASSPORT", "borrower_identifier": "AB1234567"},
        {"borrower_public_id": "12"},
    ],
)
def test_a_malformed_borrower_reference_is_rejected(client: TestClient, extra: dict) -> None:
    response = client.post("/score", json={**STRONG_APPLICANT, **extra})
    assert response.status_code == 422


def test_a_rejected_identifier_is_not_echoed_back(client: TestClient) -> None:
    response = client.post(
        "/score",
        json={**STRONG_APPLICANT, "borrower_identifier": CNIC, "applicant_name": "Ayesha Siddiqui"},
    )
    assert response.status_code == 422
    assert CNIC not in response.text


def test_the_identifier_is_masked_in_the_audit_trail(client: TestClient) -> None:
    _score(client, STRONG_APPLICANT, borrower_identifier_type="CNIC", borrower_identifier=CNIC)

    trail = client.get("/audit/logs").text
    assert CNIC_DIGITS not in trail and CNIC not in trail
    assert "*********5671" in trail


# --- the borrowers API --------------------------------------------------------------


def test_create_a_borrower_ahead_of_its_first_application(
    client: TestClient, db_session_factory
) -> None:
    created = client.post(
        "/borrowers",
        json={
            "business_name": "Qureshi Tiles",
            "owner_name": "Hamza Qureshi",
            "borrower_identifier_type": "NTN",
            "borrower_identifier": "1234567-8",
            "business_sector": "Construction",
        },
    )
    assert created.status_code == 201, created.text
    borrower = created.json()
    assert borrower["public_id"] == f"BRW-{borrower['id']:06d}"
    assert borrower["identifier_masked"] == "****5678"

    scored = _score(client, STRONG_APPLICANT, borrower_public_id=borrower["public_id"])
    assert scored["borrower_id"] == borrower["id"] and scored["borrower_created"] is False

    db = db_session_factory()
    try:
        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == Action.BORROWER_CREATED)
        ).one()
    finally:
        db.close()
    assert entry.entity_id == str(borrower["id"])
    assert entry.details == {"source": "borrowers_api"}


def test_an_identifier_can_belong_to_one_borrower_only(client: TestClient) -> None:
    body = {
        "business_name": "Qureshi Tiles",
        "owner_name": "Hamza Qureshi",
        "borrower_identifier_type": "NTN",
        "borrower_identifier": "1234567",
    }
    first = client.post("/borrowers", json=body).json()
    again = client.post("/borrowers", json={**body, "business_name": "Other Name"})

    assert again.status_code == 409
    assert first["public_id"] in again.json()["detail"]


def test_many_borrowers_may_have_no_identifier(client: TestClient, db_session_factory) -> None:
    for name in ("Shop One", "Shop Two", "Shop Three"):
        assert (
            client.post("/borrowers", json={"business_name": name, "owner_name": "Owner"}).status_code
            == 201
        )
    db = db_session_factory()
    try:
        assert db.scalars(select(Borrower).where(Borrower.identifier.is_(None))).all().__len__() == 3
    finally:
        db.close()


def test_search_is_by_name_or_reference(client: TestClient) -> None:
    strong = _score(client, STRONG_APPLICANT)
    _score(client, WEAK_APPLICANT)

    assert len(client.get("/borrowers").json()) == 2
    by_name = client.get("/borrowers", params={"q": "siddiqui"}).json()
    assert [row["id"] for row in by_name] == [strong["borrower_id"]]
    by_ref = client.get("/borrowers", params={"q": strong["borrower_public_id"]}).json()
    assert [row["id"] for row in by_ref] == [strong["borrower_id"]]
    assert client.get("/borrowers", params={"q": "nobody"}).json() == []


def test_unknown_borrowers_are_404(client: TestClient) -> None:
    for ref in ("999", "BRW-000999", "not-a-ref"):
        assert client.get(f"/borrowers/{ref}").status_code == 404
        assert client.get(f"/borrowers/{ref}/history").status_code == 404


def test_borrowers_need_a_login(client: TestClient) -> None:
    anonymous = {"Authorization": ""}
    assert client.get("/borrowers", headers=anonymous).status_code == 401
    assert client.get("/borrowers/1/history", headers=anonymous).status_code == 401
    assert (
        client.post(
            "/borrowers", json={"business_name": "xx", "owner_name": "yy"}, headers=anonymous
        ).status_code
        == 401
    )


def test_a_manager_corrects_a_borrower_and_an_analyst_cannot(
    client: TestClient, db_session_factory
) -> None:
    scored = _score(client, STRONG_APPLICANT)
    ref = scored["borrower_public_id"]
    analyst = bearer_header(username="analyst1", role="analyst")
    db = db_session_factory()
    try:
        db.add(User(username="analyst1", hashed_password=hash_password("a-long-password"), role="analyst"))
        db.commit()
    finally:
        db.close()

    assert client.patch(f"/borrowers/{ref}", json={"owner_name": "X Y"}, headers=analyst).status_code == 403

    updated = client.patch(
        f"/borrowers/{ref}",
        json={"owner_name": "Ayesha S. Siddiqui", "contact_phone": "+923451112223"},
        headers=_manager(db_session_factory),
    )
    assert updated.status_code == 200
    assert updated.json()["owner_name"] == "Ayesha S. Siddiqui"
    assert updated.json()["business_name"] == STRONG_APPLICANT["business_name"]  # not sent, kept
    # The application keeps the name it was scored with.
    assert (
        client.get(f"/score/applications/{scored['application_id']}").json()["applicant_name"]
        == STRONG_APPLICANT["applicant_name"]
    )


def test_an_inactive_borrower_takes_no_new_application(client: TestClient) -> None:
    scored = _score(client, STRONG_APPLICANT)
    ref = scored["borrower_public_id"]
    assert client.patch(f"/borrowers/{ref}", json={"status": "inactive"}).status_code == 200

    refused = client.post("/score", json={**STRONG_APPLICANT, "borrower_public_id": ref})
    assert refused.status_code == 409
    assert len(client.get("/score/applications").json()) == 1

    client.patch(f"/borrowers/{ref}", json={"status": "active"})
    assert client.post("/score", json={**STRONG_APPLICANT, "borrower_public_id": ref}).status_code == 201


def test_a_patch_that_changes_nothing_writes_no_audit_entry(
    client: TestClient, db_session_factory
) -> None:
    scored = _score(client, STRONG_APPLICANT)
    client.patch(
        f"/borrowers/{scored['borrower_public_id']}",
        json={"business_name": STRONG_APPLICANT["business_name"]},
    )
    db = db_session_factory()
    try:
        assert db.scalars(select(AuditLog).where(AuditLog.action == Action.BORROWER_UPDATED)).all() == []
    finally:
        db.close()


# --- history ------------------------------------------------------------------------


def test_history_gathers_every_application_score_month_and_alert(client: TestClient) -> None:
    first = _score(client, MID_APPLICANT)
    ref = first["borrower_public_id"]
    second = _score(client, STRONG_APPLICANT, borrower_public_id=ref)
    other = _score(client, WEAK_APPLICANT)  # a different borrower

    client.post(
        f"/score/applications/{first['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
    )
    for month, status in ((1, "On Time"), (2, "Default")):
        response = client.post(
            "/ews/monitor",
            json={
                "borrower_id": first["application_id"],
                "month_number": month,
                "installment_status": status,
                "bureau_balance": 1,
                "pos_cash_balance": 10_000_000,
            },
        )
        assert response.status_code == 201, response.text

    history = client.get(f"/borrowers/{ref}/history")
    assert history.status_code == 200, history.text
    body = history.json()

    assert body["borrower"]["public_id"] == ref
    rows = body["applications"]
    assert [row["application_id"] for row in rows] == [
        first["application_id"],
        second["application_id"],
    ]
    assert other["application_id"] not in [row["application_id"] for row in rows]

    assert rows[0]["risk_score"] == first["risk_score"]
    assert rows[0]["decision"] == "Manual Review" and rows[0]["final_decision"] == "Approved"
    assert rows[0]["review_decision"] == "Approved" and rows[0]["reviewed_by"] == "admin"
    assert rows[0]["model_version"] == first["model_version"]
    assert rows[0]["scoring_engine"] == "surrogate"
    assert [month["month_number"] for month in rows[0]["monitoring"]] == [1, 2]
    assert len(rows[0]["alerts"]) == 1 and rows[0]["alerts"][0]["alert_status"] == "Active"
    assert rows[1]["decision"] == second["decision"]
    assert rows[1]["monitoring"] == [] and rows[1]["alerts"] == []

    summary = body["summary"]
    assert summary["applications"] == 2
    assert summary["latest_score"] == second["risk_score"]
    assert summary["lowest_score"] == min(first["risk_score"], second["risk_score"])
    assert summary["highest_score"] == max(first["risk_score"], second["risk_score"])
    assert summary["approved_facilities"] == 2
    assert summary["monitored_months"] == 2
    assert summary["open_alerts"] == 1 and summary["total_alerts"] == 1
    assert summary["model_versions_used"] == [first["model_version"]]
    assert summary["scoring_engines_used"] == ["surrogate"]
    assert summary["first_application_at"] == rows[0]["created_at"]
    assert summary["latest_application_at"] == rows[1]["created_at"]

    # The numeric id reaches the same record.
    assert client.get(f"/borrowers/{first['borrower_id']}/history").json() == body


def test_history_of_a_borrower_with_no_application_is_empty(client: TestClient) -> None:
    borrower = client.post(
        "/borrowers", json={"business_name": "Qureshi Tiles", "owner_name": "Hamza Qureshi"}
    ).json()
    body = client.get(f"/borrowers/{borrower['public_id']}/history").json()

    assert body["applications"] == []
    assert body["summary"]["applications"] == 0
    assert body["summary"]["latest_score"] is None
    assert body["summary"]["model_versions_used"] == []


def test_the_facility_history_route_still_takes_an_application_id(client: TestClient) -> None:
    """``/ews/borrowers/{id}/history`` predates borrowers and is unchanged."""
    first = _score(client, STRONG_APPLICANT)
    second = _score(client, STRONG_APPLICANT, borrower_public_id=first["borrower_public_id"])
    client.post(
        "/ews/monitor",
        json={
            "borrower_id": second["application_id"],
            "month_number": 1,
            "installment_status": "On Time",
            "bureau_balance": 1,
            "pos_cash_balance": 10_000_000,
        },
    )
    assert client.get(f"/ews/borrowers/{first['application_id']}/history").json() == []
    months = client.get(f"/ews/borrowers/{second['application_id']}/history").json()
    assert [month["month_number"] for month in months] == [1]


# --- constraints --------------------------------------------------------------------


def test_an_application_cannot_exist_without_a_borrower(
    client: TestClient, db_session_factory
) -> None:
    application_id = _score(client, STRONG_APPLICANT)["application_id"]
    db = db_session_factory()
    try:
        template = db.get(Application, application_id)
        orphan = Application(
            **{
                column.name: getattr(template, column.name)
                for column in Application.__table__.columns
                if column.name not in ("id", "borrower_id")
            }
        )
        db.add(orphan)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_an_identifier_needs_its_type_in_the_database_too(db_session_factory) -> None:
    db = db_session_factory()
    try:
        db.add(Borrower(business_name="xx", owner_name="yy", identifier="1234567", status="active"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
