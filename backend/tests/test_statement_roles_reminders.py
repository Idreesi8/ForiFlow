"""Statement-backed turnover, the manager role, and payment reminders."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from models.database import Application, User
from routers.portfolio import _add_months
from services.auth_service import hash_password
from services.statement_service import StatementError, parse_statement
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, bearer_header

SAMPLE = (
    Path(__file__).resolve().parents[2] / "docs" / "samples" / "sample-wallet-statement.csv"
).read_text(encoding="utf-8")
NOTE = "Clean POS receipts for five years; facility is 28% of turnover."


def _statement(rows: list[tuple[str, str, float]], header: str = "date,type,amount") -> str:
    return header + "\n" + "\n".join(f"{d},{t},{a}" for d, t, a in rows)


def _three_months(inflow: float = 100_000, outflow: float = 60_000) -> list[tuple[str, str, float]]:
    rows = []
    for month in ("01", "02", "03"):
        rows += [(f"2026-{month}-02", "CR", inflow), (f"2026-{month}-27", "DR", outflow)]
    return rows


# --- the parser ------------------------------------------------------------------


def test_monthly_medians_come_from_full_months_only() -> None:
    rows = _three_months() + [("2026-04-03", "CR", 900_000)]  # April is partial
    summary = parse_statement(_statement(rows))

    assert summary.full_months == 3
    assert summary.suggested_monthly_digital_payments == 100_000
    assert summary.suggested_cash_flow_proxy == 40_000
    assert summary.inflow_variation == 0
    assert summary.suggested_order_consistency == 100
    assert summary.inflow_to_outflow == pytest.approx(100 / 60, abs=1e-4)


def test_credit_and_debit_columns_and_local_formats_are_read() -> None:
    text = "Txn Date,Credit,Debit\n" + "\n".join(
        f'{day}/{month}/2026,"PKR 1,00,000",\n27/{month}/2026,,"60,000"'
        for month in ("01", "02", "03")
        for day in ("02",)
    )
    summary = parse_statement(text)

    assert summary.suggested_monthly_digital_payments == 100_000
    assert summary.suggested_cash_flow_proxy == 40_000


def test_failed_transactions_are_left_out() -> None:
    rows = _three_months()
    text = "date,type,amount,status\n" + "\n".join(f"{d},{t},{a},SUCCESS" for d, t, a in rows)
    text += "\n2026-02-10,CR,5000000,FAILED"
    summary = parse_statement(text)

    assert summary.failed_transactions == 1
    assert summary.suggested_monthly_digital_payments == 100_000
    assert any("failed" in warning for warning in summary.warnings)


def test_a_single_large_inflow_is_flagged() -> None:
    rows = _three_months() + [("2026-02-15", "CR", 500_000)]
    summary = parse_statement(_statement(rows))

    assert any("One inflow of PKR 500,000" in warning for warning in summary.warnings)
    # The median is not moved by one unusual month.
    assert summary.suggested_monthly_digital_payments == 100_000


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("amount,type\n100,CR", "No date column"),
        ("date,note\n2026-01-01,x", "No amount found"),
        ("date,type,amount\n2026-01-02,CR,100\n2026-01-27,DR,50", "At least 3 are needed"),
        ("date,type,amount\nnot-a-date,CR,100", "No readable transactions"),
    ],
)
def test_unusable_statements_say_what_is_wrong(text: str, message: str) -> None:
    with pytest.raises(StatementError, match=message):
        parse_statement(text)


def test_the_sample_statement_parses() -> None:
    summary = parse_statement(SAMPLE)

    assert summary.full_months == 6
    assert [month.month for month in summary.months][0] == "2026-04"
    assert summary.suggested_monthly_digital_payments > summary.suggested_cash_flow_proxy > 0


# --- evidence stored with the application ------------------------------------------


def test_statement_endpoint_stores_nothing(client: TestClient) -> None:
    body = client.post("/score/statement", json={"csv": SAMPLE}).json()

    assert body["full_months"] == 6
    assert client.get("/score/applications").json() == []
    assert client.post("/score/statement", json={"csv": "x,y\n1,2"}).status_code == 422


def test_evidence_is_recomputed_by_the_api(client: TestClient) -> None:
    summary = parse_statement(SAMPLE)
    payload = {
        **STRONG_APPLICANT,
        "monthly_digital_payments": summary.suggested_monthly_digital_payments,
        "cash_flow_proxy": summary.suggested_cash_flow_proxy,
        "statement_csv": SAMPLE,
    }
    scored = client.post("/score", json=payload).json()
    stored = client.get(f"/score/applications/{scored['application_id']}").json()

    assert stored["turnover_evidence"]["matches_statement"] is True
    assert stored["turnover_evidence"]["transactions"] == summary.transactions
    assert "statement_csv" not in stored


def test_edited_figures_are_marked_as_not_matching(client: TestClient) -> None:
    payload = {**STRONG_APPLICANT, "statement_csv": SAMPLE}  # typed 3.2M, statement ~354k
    scored = client.post("/score", json=payload).json()
    stored = client.get(f"/score/applications/{scored['application_id']}").json()

    assert stored["turnover_evidence"]["matches_statement"] is False


def test_typed_turnover_has_no_evidence_and_bad_statements_are_refused(
    client: TestClient,
) -> None:
    scored = client.post("/score", json=STRONG_APPLICANT).json()
    stored = client.get(f"/score/applications/{scored['application_id']}").json()
    assert stored["turnover_evidence"] is None

    refused = client.post("/score", json={**STRONG_APPLICANT, "statement_csv": "a,b\n1,2"})
    assert refused.status_code == 422
    assert "Statement:" in refused.json()["detail"]


@pytest.mark.parametrize("phone", ["0300-1234567", "12345", "+92 300 1234567", "abc"])
def test_contact_phone_must_be_digits(client: TestClient, phone: str) -> None:
    response = client.post("/score", json={**STRONG_APPLICANT, "contact_phone": phone})
    assert response.status_code == 422


# --- the manager role ----------------------------------------------------------------


def _officer(db_session_factory, username: str, role: str) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(User(username=username, hashed_password=hash_password("a-long-password"), role=role))
        db.commit()
    finally:
        db.close()
    return bearer_header(username=username, role=role)


def test_a_manager_decides_reviews_and_resolves_alerts(
    client: TestClient, db_session_factory
) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    pending = client.post("/score", json=MID_APPLICANT).json()

    decided = client.post(
        f"/score/applications/{pending['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
        headers=manager,
    )
    assert decided.status_code == 200
    assert decided.json()["reviewed_by"] == "manager1"

    alert = client.post(
        "/ews/monitor",
        json={
            "borrower_id": pending["application_id"],
            "month_number": 1,
            "installment_status": "Default",
            "bureau_balance": 1,
            "pos_cash_balance": 1,
        },
    ).json()["alert"]
    resolved = client.patch(
        f"/ews/alerts/{alert['id']}/resolve", json={"note": "Handed to remedial."}, headers=manager
    )
    assert resolved.status_code == 200 and resolved.json()["resolved_by"] == "manager1"


def test_a_manager_cannot_manage_accounts(client: TestClient, db_session_factory) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")

    assert client.get("/auth/users", headers=manager).status_code == 403
    created = client.post(
        "/auth/users",
        json={"username": "newbie", "password": "a-long-password", "role": "analyst"},
        headers=manager,
    )
    assert created.status_code == 403


def test_an_admin_can_create_a_manager(client: TestClient) -> None:
    created = client.post(
        "/auth/users",
        json={"username": "manager2", "password": "a-long-password", "role": "manager"},
    )
    assert created.status_code == 201 and created.json()["role"] == "manager"


def test_an_analyst_still_cannot_decide(client: TestClient, db_session_factory) -> None:
    analyst = _officer(db_session_factory, "analyst9", "analyst")
    pending = client.post("/score", json=MID_APPLICANT).json()
    denied = client.post(
        f"/score/applications/{pending['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
        headers=analyst,
    )
    assert denied.status_code == 403
    assert "admin or manager" in denied.json()["detail"]


# --- reminders --------------------------------------------------------------------


def test_month_arithmetic_handles_short_months() -> None:
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert _add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def _backdate(db_session_factory, application_id: int, days: int) -> None:
    from datetime import timedelta

    from models.database import utcnow

    db = db_session_factory()
    try:
        application = db.get(Application, application_id)
        application.created_at = utcnow() - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def _reminders(client: TestClient) -> dict[int, dict[str, Any]]:
    response = client.get("/portfolio/reminders")
    assert response.status_code == 200, response.text
    return {row["application_id"]: row for row in response.json()}


def _month(client: TestClient, application_id: int, month: int, **fields: Any) -> None:
    payload = {
        "borrower_id": application_id,
        "month_number": month,
        "installment_status": "On Time",
        "bureau_balance": 1,
        "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"],
        **fields,
    }
    assert client.post("/ews/monitor", json=payload).status_code == 201


def test_a_new_facility_has_no_reminder_yet(client: TestClient) -> None:
    client.post("/score", json=STRONG_APPLICANT)
    assert _reminders(client) == {}
    assert client.get("/portfolio/reminders", headers={"Authorization": ""}).status_code == 401


def test_due_soon_overdue_and_arrears(client: TestClient, db_session_factory) -> None:
    installment = STRONG_APPLICANT["loan_amount_pkr"] / STRONG_APPLICANT["tenure_months"]
    soon = client.post(
        "/score", json={**STRONG_APPLICANT, "contact_phone": "+923001234567"}
    ).json()["application_id"]
    overdue = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    behind = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    _backdate(db_session_factory, soon, 25)      # first installment due in a few days
    _backdate(db_session_factory, overdue, 45)   # first installment about two weeks late
    _backdate(db_session_factory, behind, 35)
    _month(client, behind, 1, amount_paid_pkr=installment / 2)  # recorded, half paid

    rows = _reminders(client)
    assert rows[soon]["kind"] == "due_soon"
    assert 0 <= rows[soon]["days_until_due"] <= 7
    assert rows[soon]["contact_phone"] == "+923001234567"
    assert rows[soon]["installment_number"] == 1

    assert rows[overdue]["kind"] == "overdue"
    assert rows[overdue]["days_until_due"] < 0
    assert "was due on" in rows[overdue]["message_en"]
    assert "wajib-ul-ada thi" in rows[overdue]["message_ur"]

    assert rows[behind]["kind"] == "arrears"
    assert rows[behind]["arrears_pkr"] == pytest.approx(installment / 2, abs=0.01)
    assert rows[behind]["due_date"] is None
    # Most urgent first.
    assert list(rows) == [overdue, behind, soon]


def test_recording_the_month_clears_the_reminder(client: TestClient, db_session_factory) -> None:
    installment = STRONG_APPLICANT["loan_amount_pkr"] / STRONG_APPLICANT["tenure_months"]
    facility = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    _backdate(db_session_factory, facility, 45)
    assert _reminders(client)[facility]["kind"] == "overdue"

    _month(client, facility, 1, amount_paid_pkr=installment)
    assert facility not in _reminders(client)


def test_defaulted_and_unapproved_facilities_get_no_reminder(
    client: TestClient, db_session_factory
) -> None:
    defaulted = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    pending = client.post("/score", json=MID_APPLICANT).json()["application_id"]
    _backdate(db_session_factory, defaulted, 80)
    _backdate(db_session_factory, pending, 80)
    _month(client, defaulted, 1, installment_status="Default", amount_paid_pkr=0)

    assert _reminders(client) == {}
