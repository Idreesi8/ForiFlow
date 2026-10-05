"""The group audit of the model, and approval authority by facility size."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ml.fairness_audit import FOUR_FIFTHS, MIN_GROUP_ROWS, audit_attribute, group_row
from ml.features import load_fairness_audit, load_model_evaluation
from models.database import User
from services.auth_service import hash_password
from tests.conftest import MID_APPLICANT, bearer_header

NOTE = "Clean receipts for five years; facility is modest against turnover."

# --- the audit arithmetic -----------------------------------------------------------


def test_group_row_counts_each_kind_of_wrong_decision() -> None:
    # Scores: two approved (>70), one in review, two rejected (<=40).
    scores = np.array([90.0, 80.0, 55.0, 40.0, 10.0])
    y = np.array([0, 1, 0, 0, 1])
    predicted = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    row = group_row("g", scores, 1.0 - scores / 100.0, predicted, y)

    assert row["rows"] == 5 and row["defaults"] == 2
    assert row["approval_rate"] == pytest.approx(2 / 5)
    assert row["rejection_rate"] == pytest.approx(2 / 5)
    # Three good payers, one rejected; two defaulters, one approved.
    assert row["good_payers_rejected"] == pytest.approx(1 / 3)
    assert row["defaulters_approved"] == pytest.approx(1 / 2)
    assert row["observed_default_rate"] == pytest.approx(0.4)
    assert row["predicted_default_rate"] == pytest.approx(0.3)
    assert row["calibration_gap"] == pytest.approx(-0.1)
    assert row["small_group"] is True


def test_a_gap_counts_only_when_larger_than_the_group_size_explains() -> None:
    rows = 400
    scores = np.full(rows, 50.0)
    y = np.zeros(rows, dtype=int)
    y[:80] = 1  # 20% default
    close = group_row("close", scores, 1 - scores / 100, np.full(rows, 0.22), y)
    far = group_row("far", scores, 1 - scores / 100, np.full(rows, 0.30), y)

    assert close["gap_beyond_noise"] is False
    assert far["gap_beyond_noise"] is True


def test_four_fifths_uses_the_best_group_and_ignores_small_ones() -> None:
    size = MIN_GROUP_ROWS
    # A: half approved. B: 30% approved (ratio 0.6). C: tiny and all approved.
    scores = np.concatenate(
        [
            np.where(np.arange(size) < size // 2, 90.0, 50.0),
            np.where(np.arange(size) < int(size * 0.3), 90.0, 50.0),
            np.full(5, 90.0),
        ]
    )
    labels = pd.Series(["A"] * size + ["B"] * size + ["C"] * 5)
    y = np.tile([0, 1], len(scores) // 2 + 1)[: len(scores)]
    block = audit_attribute(
        "x", "", labels, ["A", "B", "C"], scores, 1 - scores / 100, np.full(len(y), 0.5), y
    )

    assert block["reference_group"] == "A"  # not the 5-loan group
    by_name = {row["group"]: row for row in block["groups"]}
    assert by_name["B"]["approval_ratio"] == pytest.approx(0.6)
    assert by_name["B"]["below_four_fifths"] is True
    assert by_name["C"]["below_four_fifths"] is False
    assert block["groups_below_four_fifths"] == ["B"]
    assert 0.6 < FOUR_FIFTHS


# --- the recorded audit -------------------------------------------------------------


def test_fairness_needs_a_login(client: TestClient) -> None:
    assert client.get("/model/fairness", headers={"Authorization": ""}).status_code == 401


@pytest.mark.skipif(load_fairness_audit() is None, reason="ml.fairness_audit not run")
def test_recorded_audit_is_consistent(client: TestClient) -> None:
    body = client.get("/model/fairness").json()

    assert body["rows"] == body["overall"]["rows"]
    assert {block["attribute"] for block in body["attributes"]} == {
        "Age",
        "Income",
        "Housing",
        "Loan purpose",
    }
    for block in body["attributes"]:
        # Every hold-out loan falls in exactly one group of each attribute.
        assert sum(row["rows"] for row in block["groups"]) == body["rows"]
        assert sum(row["defaults"] for row in block["groups"]) == body["overall"]["defaults"]
        reference = next(r for r in block["groups"] if r["group"] == block["reference_group"])
        assert reference["approval_ratio"] == pytest.approx(1.0)
        assert not reference["small_group"]
    assert any("Gender" in line for line in body["not_audited"])


@pytest.mark.skipif(
    load_fairness_audit() is None or load_model_evaluation() is None,
    reason="recorded results missing",
)
def test_audit_belongs_to_the_evaluated_model() -> None:
    audit, evaluation = load_fairness_audit(), load_model_evaluation()

    assert audit["model_trained_at"] == evaluation["model_trained_at"]
    assert audit["rows"] == evaluation["rows"]["holdout"]
    assert audit["overall"]["observed_default_rate"] == pytest.approx(
        evaluation["default_rate"]["holdout"]
    )


# --- approval authority by size -----------------------------------------------------


def _officer(db_session_factory, username: str, role: str) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(User(username=username, hashed_password=hash_password("a-long-password"), role=role))
        db.commit()
    finally:
        db.close()
    return bearer_header(username=username, role=role)


def _review(client: TestClient, application_id: int, decision: str, headers=None):
    return client.post(
        f"/score/applications/{application_id}/review",
        json={"decision": decision, "note": NOTE},
        headers=headers,
    )


def test_summary_says_who_may_approve(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1200000")
    at_limit = client.post("/score", json=MID_APPLICANT).json()["application_id"]
    above = client.post(
        "/score", json={**MID_APPLICANT, "loan_amount_pkr": 1_200_001}
    ).json()["application_id"]

    first = client.get(f"/score/applications/{at_limit}").json()
    second = client.get(f"/score/applications/{above}").json()
    assert first["manager_approval_limit_pkr"] == 1_200_000
    assert first["approval_authority"] == "manager"
    assert second["approval_authority"] == "admin"


def test_a_manager_cannot_approve_above_the_limit(
    client: TestClient, db_session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1000000")
    manager = _officer(db_session_factory, "manager1", "manager")
    pending = client.post("/score", json=MID_APPLICANT).json()
    assert pending["decision"] == "Manual Review"

    denied = _review(client, pending["application_id"], "Approved", manager)
    assert denied.status_code == 403
    assert "1,200,000" in denied.json()["detail"] and "1,000,000" in denied.json()["detail"]
    # Nothing was recorded, so the admin can still decide it.
    assert client.get(f"/score/applications/{pending['application_id']}").json()[
        "review_decision"
    ] is None
    approved = _review(client, pending["application_id"], "Approved")
    assert approved.status_code == 200 and approved.json()["reviewed_by"] == "admin"


def test_a_manager_can_reject_above_the_limit(
    client: TestClient, db_session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1000000")
    manager = _officer(db_session_factory, "manager1", "manager")
    pending = client.post("/score", json=MID_APPLICANT).json()

    rejected = _review(client, pending["application_id"], "Rejected", manager)
    assert rejected.status_code == 200 and rejected.json()["review_decision"] == "Rejected"


def test_a_manager_approves_up_to_the_limit(
    client: TestClient, db_session_factory, monkeypatch
) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1200000")
    manager = _officer(db_session_factory, "manager1", "manager")
    pending = client.post("/score", json=MID_APPLICANT).json()

    assert _review(client, pending["application_id"], "Approved", manager).status_code == 200


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_a_bad_limit_is_refused(monkeypatch, value: str) -> None:
    from config import manager_approval_limit_pkr

    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", value)
    with pytest.raises(RuntimeError):
        manager_approval_limit_pkr()
