"""Portfolio summary: collections, arrears, portfolio at risk, concentration."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT

NOTE = "Clean POS receipts for five years; facility is 28% of turnover."
INSTALLMENT = STRONG_APPLICANT["loan_amount_pkr"] / STRONG_APPLICANT["tenure_months"]


def _score(client: TestClient, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    response = client.post("/score", json={**payload, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _month(client: TestClient, borrower: dict[str, Any], month: int, **fields: Any) -> None:
    payload = {
        "borrower_id": borrower["application_id"],
        "month_number": month,
        "installment_status": "On Time",
        "bureau_balance": 1_000_000,
        "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"],
        **fields,
    }
    assert client.post("/ews/monitor", json=payload).status_code == 201


def _summary(client: TestClient) -> dict[str, Any]:
    response = client.get("/portfolio/summary")
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_needs_a_login(client: TestClient) -> None:
    assert client.get("/portfolio/summary", headers={"Authorization": ""}).status_code == 401


def test_an_empty_portfolio_reports_zeros_not_errors(client: TestClient) -> None:
    body = _summary(client)

    assert body["approved_facilities"] == 0
    assert body["disbursed_pkr"] == 0
    assert body["collection_rate"] is None
    assert body["par30"] is None
    assert body["sectors"] == []
    assert [row["facilities"] for row in body["latest_status"]] == [0] * 5


def test_collections_and_arrears_follow_the_recorded_months(client: TestClient) -> None:
    facility = _score(client, STRONG_APPLICANT, business_sector="Textile & Garments")
    assert facility["decision"] == "Approved"
    _month(client, facility, 1, amount_paid_pkr=INSTALLMENT)
    _month(client, facility, 2, amount_paid_pkr=INSTALLMENT / 2, installment_status="Late 1-29")
    _month(client, facility, 3)  # status only, no amount

    body = _summary(client)
    loan = STRONG_APPLICANT["loan_amount_pkr"]
    assert body["approved_facilities"] == body["monitored_facilities"] == 1
    assert body["disbursed_pkr"] == loan
    assert body["due_pkr"] == pytest.approx(2 * INSTALLMENT, abs=0.01)
    assert body["collected_pkr"] == pytest.approx(1.5 * INSTALLMENT, abs=0.01)
    assert body["collection_rate"] == 75.0
    assert body["overdue_pkr"] == pytest.approx(0.5 * INSTALLMENT, abs=0.01)
    assert body["outstanding_pkr"] == pytest.approx(loan - 1.5 * INSTALLMENT, abs=0.01)
    assert (body["months_with_amount"], body["months_without_amount"]) == (2, 1)
    # Month 3 is the latest and it is On Time, so nothing is at risk.
    assert body["par30"] == 0.0


def test_an_overpayment_does_not_hide_another_facilitys_arrears(client: TestClient) -> None:
    ahead = _score(client, STRONG_APPLICANT)
    behind = _score(client, STRONG_APPLICANT)
    _month(client, ahead, 1, amount_paid_pkr=2 * INSTALLMENT)
    _month(client, behind, 1, amount_paid_pkr=0, installment_status="Late 30-59")

    body = _summary(client)
    assert body["collection_rate"] == 100.0
    assert body["overdue_pkr"] == pytest.approx(INSTALLMENT, abs=0.01)


def test_a_payment_rounded_to_whole_rupees_is_not_arrears(client: TestClient) -> None:
    facility = _score(client, {**STRONG_APPLICANT, "loan_amount_pkr": 250_000, "tenure_months": 12})
    _month(client, facility, 1, amount_paid_pkr=20_833)  # installment is 20,833.33

    assert _summary(client)["overdue_pkr"] == 0


def test_par30_uses_the_latest_month_of_each_facility(client: TestClient) -> None:
    healthy = _score(client, STRONG_APPLICANT)
    late = _score(client, STRONG_APPLICANT)
    defaulted = _score(client, STRONG_APPLICANT)
    _month(client, healthy, 1, amount_paid_pkr=INSTALLMENT)
    _month(client, late, 1, amount_paid_pkr=0, installment_status="Late 60-89")
    _month(client, defaulted, 1, amount_paid_pkr=0, installment_status="Late 30-59")
    _month(client, defaulted, 2, amount_paid_pkr=0, installment_status="Default")

    body = _summary(client)
    loan = STRONG_APPLICANT["loan_amount_pkr"]
    at_risk = 2 * loan
    assert body["par30"] == round(at_risk / (3 * loan - INSTALLMENT) * 100, 1)
    assert body["defaulted_facilities"] == 1
    assert body["defaulted_outstanding_pkr"] == loan
    by_status = {row["status"]: row["facilities"] for row in body["latest_status"]}
    assert by_status == {
        "On Time": 1, "Late 1-29": 0, "Late 30-59": 0, "Late 60-89": 1, "Default": 1
    }


def test_decision_matrix_separates_model_band_from_final_outcome(client: TestClient) -> None:
    _score(client, STRONG_APPLICANT)
    _score(client, WEAK_APPLICANT)
    approved_mr = _score(client, MID_APPLICANT)
    _score(client, MID_APPLICANT)  # left pending
    client.post(
        f"/score/applications/{approved_mr['application_id']}/review",
        json={"decision": "Approved", "note": NOTE},
    )

    rows = {row["model_decision"]: row for row in _summary(client)["decision_matrix"]}
    assert rows["Approved"] | {"model_decision": ""} == {
        "model_decision": "", "approved": 1, "rejected": 0, "pending": 0
    }
    assert (rows["Manual Review"]["approved"], rows["Manual Review"]["pending"]) == (1, 1)
    assert rows["Rejected"]["rejected"] == 1


def test_sectors_report_concentration_and_unrecorded_rows(client: TestClient) -> None:
    textile = _score(client, STRONG_APPLICANT, business_sector="Textile & Garments")
    _score(client, WEAK_APPLICANT, business_sector="Textile & Garments")
    _score(client, STRONG_APPLICANT)  # scored without a sector
    _month(client, textile, 1, amount_paid_pkr=0, installment_status="Default")

    sectors = {row["sector"]: row for row in _summary(client)["sectors"]}
    assert set(sectors) == {"Textile & Garments", "Not recorded"}
    row = sectors["Textile & Garments"]
    assert (row["applications"], row["approved"], row["approval_rate"]) == (2, 1, 50.0)
    assert row["approved_exposure_pkr"] == STRONG_APPLICANT["loan_amount_pkr"]
    assert row["overdue_pkr"] == pytest.approx(INSTALLMENT, abs=0.01)
    assert row["open_alerts"] == 1
    assert sectors["Not recorded"]["open_alerts"] == 0


def test_an_unknown_sector_is_refused(client: TestClient) -> None:
    response = client.post("/score", json={**STRONG_APPLICANT, "business_sector": "Mining"})
    assert response.status_code == 422


def test_sector_and_amount_are_returned_with_the_records(client: TestClient) -> None:
    facility = _score(client, STRONG_APPLICANT, business_sector="Retail")
    _month(client, facility, 1, amount_paid_pkr=12_345)

    stored = client.get(f"/score/applications/{facility['application_id']}").json()
    assert stored["business_sector"] == "Retail"
    history = client.get(f"/ews/borrowers/{facility['application_id']}/history").json()
    records = history["records"] if isinstance(history, dict) else history
    assert records[0]["amount_paid_pkr"] == 12_345
