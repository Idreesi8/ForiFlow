"""Phase 2: the model assesses, the policy recommends, an officer decides."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from main import app
from models.database import Application, AuditLog, CreditPolicy, User
from schemas import Decision, RiskBand, ShapFeatureContribution, SMEApplicant
from services import policy_rules, policy_service
from services.audit_service import Action
from services.auth_service import hash_password
from services.policy_rules import DEMO_BANDS, ScoreBands
from services.reason_codes import MAX_CODES, MIN_POINTS, REASON_CODES, reason_codes_for
from services.scoring_service import ScoringService, get_scoring_service
from tests.conftest import (
    MID_APPLICANT,
    STRONG_APPLICANT,
    WEAK_APPLICANT,
    bearer_header,
    decide,
)

NOTE = "Checked the statement against the stated turnover; recorded here."
POLICY_V2 = {
    "version": "2.0",
    "name": "Pilot Credit Policy",
    "description": "Tighter bands for the pilot.",
    "decline_max_score": 50,
    "manual_review_max_score": 80,
    "manager_approval_limit_pkr": 1_000_000,
    "decline_override_admin_only": True,
}


def _officer(db_session_factory, username: str, role: str) -> dict[str, str]:
    db = db_session_factory()
    try:
        db.add(User(username=username, hashed_password=hash_password("a-long-password"), role=role))
        db.commit()
    finally:
        db.close()
    return bearer_header(username=username, role=role)


def _score(client: TestClient, payload: dict, **extra) -> dict:
    response = client.post("/score", json={**payload, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _act(client: TestClient, application_id: int, decision: str, headers=None, route="decision"):
    return client.post(
        f"/score/applications/{application_id}/{route}",
        json={"decision": decision, "note": NOTE},
        headers=headers,
    )


def _entries(db_session_factory, **filters) -> list[AuditLog]:
    db = db_session_factory()
    try:
        statement = select(AuditLog).order_by(AuditLog.id)
        for name, value in filters.items():
            statement = statement.where(getattr(AuditLog, name) == value)
        return list(db.scalars(statement).all())
    finally:
        db.close()


def _row(db_session_factory, application_id: int) -> Application:
    db = db_session_factory()
    try:
        return db.get(Application, application_id)
    finally:
        db.close()


def _activate_v2(client: TestClient, **overrides) -> dict:
    created = client.post("/policy/versions", json={**POLICY_V2, **overrides})
    assert created.status_code == 201, created.text
    activated = client.post(f"/policy/versions/{created.json()['id']}/activate")
    assert activated.status_code == 200, activated.text
    return activated.json()


# === POLICY =========================================================================


def test_the_default_demo_policy_loads_with_the_cut_offs_always_used(client: TestClient) -> None:
    policy = client.get("/policy/active").json()

    assert (policy["version"], policy["name"]) == ("1.0", "Demo Credit Policy")
    assert policy["status"] == "active" and policy["is_active"] is True
    assert policy["decline_max_score"] == 40.0
    assert policy["manual_review_max_score"] == 70.0
    assert policy["approve_above_score"] == 70.0
    assert policy["manager_approval_limit_pkr"] == 2_000_000
    assert policy["decline_override_admin_only"] is True
    assert policy["created_by"] == "system" and policy["activated_at"] is not None
    # It says what it is.
    assert "demo" in policy["notice"].lower() and "not" in policy["notice"].lower()
    assert "not validated" in policy["description"]
    assert [row["version"] for row in client.get("/policy/versions").json()] == ["1.0"]


@pytest.mark.parametrize(
    ("score", "recommendation", "band"),
    [
        (0.0, Decision.REJECTED, RiskBand.HIGH),
        (40.0, Decision.REJECTED, RiskBand.HIGH),
        (40.01, Decision.MANUAL_REVIEW, RiskBand.MEDIUM),
        (70.0, Decision.MANUAL_REVIEW, RiskBand.MEDIUM),
        (70.01, Decision.APPROVED, RiskBand.LOW),
        (100.0, Decision.APPROVED, RiskBand.LOW),
    ],
)
def test_demo_thresholds_split_the_score_as_before(
    score: float, recommendation: Decision, band: RiskBand
) -> None:
    assert policy_rules.recommendation_for(score, DEMO_BANDS) is recommendation
    assert policy_rules.risk_band_for(score, DEMO_BANDS) is band


def test_other_cut_offs_give_other_recommendations_for_the_same_score() -> None:
    strict = ScoreBands(decline_max_score=60, manual_review_max_score=90)
    assert policy_rules.recommendation_for(55, DEMO_BANDS) is Decision.MANUAL_REVIEW
    assert policy_rules.recommendation_for(55, strict) is Decision.REJECTED
    assert policy_rules.recommendation_for(85, DEMO_BANDS) is Decision.APPROVED
    assert policy_rules.recommendation_for(85, strict) is Decision.MANUAL_REVIEW
    assert policy_rules.triggered_rule(55, strict) == {
        "rule": "score_at_or_below_decline_max",
        "threshold": 60,
        "comparison": "<=",
        "risk_score": 55,
    }


@pytest.mark.parametrize("bands", [(50, 50), (60, 40), (-1, 50), (10, 101)])
def test_bands_out_of_order_are_refused(bands: tuple[float, float]) -> None:
    with pytest.raises(ValueError):
        ScoreBands(decline_max_score=bands[0], manual_review_max_score=bands[1])


def test_the_score_does_not_depend_on_the_policy() -> None:
    """Cut-offs label a score; they never change it."""
    service = ScoringService()
    applicant = SMEApplicant(**MID_APPLICANT)
    demo = service.score(applicant)
    strict = service.score(applicant, ScoreBands(decline_max_score=65, manual_review_max_score=90))

    assert demo.risk_score == strict.risk_score
    assert demo.decision is Decision.MANUAL_REVIEW and strict.decision is Decision.REJECTED
    assert [c.contribution for c in service.explain(demo)] == [
        c.contribution for c in service.explain(strict)
    ]


def test_an_admin_creates_a_draft_that_changes_nothing_until_activated(client: TestClient) -> None:
    before = _score(client, MID_APPLICANT)
    created = client.post("/policy/versions", json=POLICY_V2)

    assert created.status_code == 201, created.text
    draft = created.json()
    assert draft["status"] == "draft" and draft["is_active"] is False
    assert draft["created_by"] == "admin" and draft["activated_at"] is None
    assert client.get("/policy/active").json()["version"] == "1.0"
    assert _score(client, MID_APPLICANT)["policy_version"] == before["policy_version"] == "1.0"


def test_activation_retires_the_previous_version_and_only_one_is_active(
    client: TestClient, db_session_factory
) -> None:
    activated = _activate_v2(client)

    assert activated["status"] == "active" and activated["activated_by"] == "admin"
    versions = {row["version"]: row for row in client.get("/policy/versions").json()}
    assert versions["1.0"]["status"] == "retired" and versions["1.0"]["retired_at"] is not None
    assert versions["2.0"]["status"] == "active"
    assert [v for v, row in versions.items() if row["is_active"]] == ["2.0"]
    # Nothing was deleted.
    assert set(versions) == {"1.0", "2.0"}

    again = client.post(f"/policy/versions/{activated['id']}/activate")
    assert again.status_code == 409

    # A retired version can serve again; it is the same immutable version.
    back = client.post(f"/policy/versions/{versions['1.0']['id']}/activate")
    assert back.status_code == 200 and back.json()["retired_at"] is None
    assert client.get("/policy/active").json()["version"] == "1.0"


def test_the_database_allows_only_one_active_policy(client: TestClient, db_session_factory) -> None:
    client.get("/policy/active")
    db = db_session_factory()
    try:
        db.add(
            CreditPolicy(
                version="9.9",
                name="Second active",
                status="active",
                decline_max_score=40,
                manual_review_max_score=70,
                manager_approval_limit_pkr=1,
                created_by="test",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_a_version_is_never_edited_or_deleted(client: TestClient) -> None:
    client.post("/policy/versions", json=POLICY_V2)
    same_number = client.post("/policy/versions", json={**POLICY_V2, "decline_max_score": 10})
    assert same_number.status_code == 409 and "never edited" in same_number.json()["detail"]

    routes = client.get("/openapi.json").json()["paths"]
    policy_routes = {path: sorted(methods) for path, methods in routes.items() if "/policy" in path}
    assert policy_routes == {
        "/policy/active": ["get"],
        "/policy/versions": ["get", "post"],
        "/policy/versions/{policy_id}/activate": ["post"],
    }
    for method in (client.put, client.patch, client.delete):
        assert method("/policy/versions/1").status_code in (404, 405)


@pytest.mark.parametrize(
    "bad",
    [
        {"decline_max_score": 80, "manual_review_max_score": 80},
        {"decline_max_score": 90},
        {"manual_review_max_score": 101},
        {"decline_max_score": -1},
        {"manager_approval_limit_pkr": -5},
        {"version": "has spaces"},
        {"name": "x"},
    ],
)
def test_an_inconsistent_policy_is_rejected(client: TestClient, bad: dict) -> None:
    assert client.post("/policy/versions", json={**POLICY_V2, **bad}).status_code == 422


@pytest.mark.parametrize("role", ["analyst", "manager"])
def test_only_an_admin_changes_policy(client: TestClient, db_session_factory, role: str) -> None:
    officer = _officer(db_session_factory, f"{role}1", role)
    draft = client.post("/policy/versions", json=POLICY_V2).json()

    assert client.post("/policy/versions", json={**POLICY_V2, "version": "3.0"}, headers=officer).status_code == 403
    assert client.post(f"/policy/versions/{draft['id']}/activate", headers=officer).status_code == 403
    assert client.get("/policy/active", headers={"Authorization": ""}).status_code == 401
    # Everyone may read the policy they work under.
    assert client.get("/policy/active", headers=officer).json()["version"] == "1.0"
    assert len(client.get("/policy/versions", headers=officer).json()) == 2
    assert _entries(db_session_factory, action=Action.POLICY_ACTIVATED)[-1].username == "system"


def test_a_new_policy_does_not_touch_applications_already_assessed(
    client: TestClient, db_session_factory
) -> None:
    """MID scores about 58: Manual Review under 1.0, Decline under 2.0 (decline_max 60)."""
    old = _score(client, MID_APPLICANT)
    assert old["decision"] == "Manual Review" and old["policy_version"] == "1.0"
    stored_before = _row(db_session_factory, old["application_id"])
    summary_before = client.get(f"/score/applications/{old['application_id']}").json()

    _activate_v2(client, decline_max_score=60, manual_review_max_score=90)
    new = _score(client, MID_APPLICANT)

    assert new["risk_score"] == old["risk_score"]  # the model did not change
    assert new["decision"] == "Rejected" and new["recommendation"] == "Decline"
    assert new["risk_band"] == "High Risk" and new["policy_version"] == "2.0"

    stored_after = _row(db_session_factory, old["application_id"])
    for field in ("decision", "risk_band", "policy_id", "policy_version", "policy_evaluation",
                  "risk_score", "model_version", "reason_codes", "shap_explanation_json"):
        assert getattr(stored_after, field) == getattr(stored_before, field), field
    summary_after = client.get(f"/score/applications/{old['application_id']}").json()
    assert summary_after == summary_before
    assert summary_after["policy"]["policy_version"] == "1.0"
    assert summary_after["manager_approval_limit_pkr"] == 2_000_000  # 2.0 says 1,000,000

    # Recomputing the old explanation still reads it against its own policy.
    refreshed = client.post(f"/explain/{old['application_id']}?refresh=true").json()
    assert refreshed["decision"] == "Manual Review" and refreshed["policy_version"] == "1.0"

    counts = {row["version"]: row["applications_assessed"] for row in client.get("/policy/versions").json()}
    assert counts == {"1.0": 1, "2.0": 1}


def test_the_environment_limit_only_seeds_the_first_policy(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "750000")
    assert client.get("/policy/active").json()["manager_approval_limit_pkr"] == 750_000

    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "9000000")  # ignored from now on
    assert client.get("/policy/active").json()["manager_approval_limit_pkr"] == 750_000
    scored = _score(client, MID_APPLICANT)
    assert scored["policy"]["authority"]["manager_approval_limit_pkr"] == 750_000


def test_policy_changes_are_audited(client: TestClient, db_session_factory) -> None:
    activated = _activate_v2(client)

    created = _entries(db_session_factory, action=Action.POLICY_CREATED)
    assert [entry.username for entry in created] == ["system", "admin"]
    assert created[1].entity_type == "credit_policy" and created[1].entity_id == str(activated["id"])
    assert created[1].new_state["decline_max_score"] == 50
    assert created[1].new_state["status"] == "draft"
    assert created[1].request_id and created[1].role == "admin"

    retired = _entries(db_session_factory, action=Action.POLICY_RETIRED)
    assert len(retired) == 1
    assert retired[0].previous_state == {"status": "active"}
    assert retired[0].new_state == {"status": "retired", "replaced_by": "2.0"}

    activations = _entries(db_session_factory, action=Action.POLICY_ACTIVATED)
    assert activations[-1].username == "admin"
    assert activations[-1].previous_state == {"status": "draft", "active": "1.0"}
    assert activations[-1].new_state["active"] == "2.0"


# === RECOMMENDATION =================================================================


@pytest.mark.parametrize(
    ("payload", "legacy", "recommendation", "band"),
    [
        (STRONG_APPLICANT, "Approved", "Approve", "Low Risk"),
        (MID_APPLICANT, "Manual Review", "Manual Review", "Medium Risk"),
        (WEAK_APPLICANT, "Rejected", "Decline", "High Risk"),
    ],
)
def test_a_score_produces_a_recommendation_and_no_decision(
    client: TestClient, payload: dict, legacy: str, recommendation: str, band: str
) -> None:
    body = _score(client, payload)

    # Model output, on its own.
    assert body["assessment"] == {
        "risk_score": body["risk_score"],
        "risk_band": band,
        "probability_of_default_raw": None,  # the fallback formula has no probability
        "probability_of_default": None,
        "model_version": "surrogate-linear-v1",
        "scoring_engine": "surrogate",
    }
    # Policy output.
    assert body["recommendation"] == recommendation and body["decision"] == legacy
    policy = body["policy"]
    assert policy["recommendation"] == recommendation
    assert (policy["policy_version"], policy["policy_name"]) == ("1.0", "Demo Credit Policy")
    assert policy["triggered_rules"][0]["risk_score"] == body["risk_score"]
    assert f"Recommendation: {recommendation}" in policy["reason"]
    assert "the decision is the officer's" in policy["reason"]
    # Human output: nothing yet, whatever was recommended.
    assert body["decision_status"] == "Pending"
    assert body["officer_decision"] == {
        "status": "Pending", "decision": None, "decided_by": None, "decided_at": None,
        "note": None, "source": None, "overrides_recommendation": None, "escalated_by": None,
        "escalated_at": None, "escalation_note": None, "superseded_by_application_id": None,
    }

    stored = client.get(f"/score/applications/{body['application_id']}").json()
    assert stored["final_decision"] is None and stored["review_decision"] is None
    assert stored["recommendation"] == recommendation
    assert stored["policy"] == policy and stored["assessment"] == body["assessment"]


def test_the_policy_snapshot_is_stored_with_the_application(
    client: TestClient, db_session_factory
) -> None:
    body = _score(client, MID_APPLICANT)
    row = _row(db_session_factory, body["application_id"])

    assert row.policy_version == "1.0" and row.policy_id is not None
    assert row.risk_band == "Medium Risk" and row.decision_status == "Pending"
    snapshot = row.policy_evaluation
    assert snapshot["recommendation"] == "Manual Review"
    assert snapshot["bands"] == {"decline_max_score": 40.0, "manual_review_max_score": 70.0}
    assert snapshot["authority_rule"] == {
        "manager_approval_limit_pkr": 2_000_000.0,
        "decline_override_admin_only": True,
    }
    assert snapshot["triggered_rules"][0]["rule"] == "score_at_or_below_manual_review_max"
    assert snapshot["authority_at_assessment"] == {
        "approve_requires": "manager",
        "reason": "within_manager_limit",
    }


def test_the_trained_model_reports_both_probabilities(ml_client: TestClient, db_session_factory) -> None:
    body = _score(ml_client, MID_APPLICANT)
    assessment = body["assessment"]

    assert assessment["scoring_engine"] == "ml"
    assert 0 < assessment["probability_of_default_raw"] < 1
    assert 0 < assessment["probability_of_default"] < 1
    # The score is still exactly 100 * (1 - raw probability): nothing changed there.
    assert body["risk_score"] == pytest.approx(
        100 * (1 - assessment["probability_of_default_raw"]), abs=0.005
    )
    assert assessment["probability_of_default"] == body["probability_of_default"]
    row = _row(db_session_factory, body["application_id"])
    assert row.raw_pd == assessment["probability_of_default_raw"]
    assert row.calibrated_pd == assessment["probability_of_default"]


def test_the_recommendation_is_audited_apart_from_the_score(
    client: TestClient, db_session_factory
) -> None:
    body = _score(client, WEAK_APPLICANT)
    entry = _entries(db_session_factory, action=Action.RECOMMENDATION_GENERATED)[0]

    assert entry.entity_type == "application" and entry.entity_id == str(body["application_id"])
    assert entry.username == "admin" and entry.request_id
    assert entry.new_state == {
        "recommendation": "Decline",
        "risk_band": "High Risk",
        "decision_status": "Pending",
    }
    assert entry.details["policy_version"] == "1.0"
    assert entry.details["approve_requires"] == "admin"
    assert entry.details["authority_reason"] == "approval_against_decline_recommendation"
    assert entry.details["reason_codes"] == [code["code"] for code in body["reason_codes"]]


def test_the_narrative_never_says_the_system_decided(client: TestClient) -> None:
    for payload in (STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT):
        narrative = _score(client, payload)["explanation"]["narrative"]
        assert "Policy recommendation:" in narrative
        assert "authorised credit officer" in narrative
        assert "outcome" not in narrative and "resulted in" not in narrative


# === HUMAN DECISION =================================================================


def test_a_recommended_approval_still_needs_an_officer(client: TestClient) -> None:
    body = _score(client, STRONG_APPLICANT)
    blocked = client.post(
        "/ews/monitor",
        json={"borrower_id": body["application_id"], "month_number": 1,
              "installment_status": "On Time", "bureau_balance": 1, "pos_cash_balance": 1},
    )
    assert blocked.status_code == 409 and "awaiting an officer decision" in blocked.json()["detail"]

    decided = _act(client, body["application_id"], "Approved")
    assert decided.status_code == 200
    record = decided.json()["officer_decision"]
    assert record["status"] == "Approved" and record["decision"] == "Approved"
    assert record["decided_by"] == "admin" and record["decided_at"] and record["note"] == NOTE
    assert record["source"] == "officer" and record["overrides_recommendation"] is False
    assert decided.json()["decision"] == "Approved"  # recommendation unchanged
    assert decided.json()["final_decision"] == "Approved"


def test_the_officer_may_decide_against_the_recommendation(client: TestClient) -> None:
    approve_recommended = _score(client, STRONG_APPLICANT)["application_id"]
    decline_recommended = _score(client, WEAK_APPLICANT)["application_id"]

    rejected = _act(client, approve_recommended, "Rejected").json()
    assert rejected["recommendation"] == "Approve" and rejected["final_decision"] == "Rejected"
    assert rejected["officer_decision"]["overrides_recommendation"] is True

    approved = _act(client, decline_recommended, "Approved").json()  # the admin may
    assert approved["recommendation"] == "Decline" and approved["final_decision"] == "Approved"
    assert approved["officer_decision"]["overrides_recommendation"] is True


def test_both_route_names_record_the_same_decision(client: TestClient) -> None:
    first = _score(client, MID_APPLICANT)["application_id"]
    second = _score(client, MID_APPLICANT)["application_id"]
    assert _act(client, first, "Approved", route="decision").json()["final_decision"] == "Approved"
    assert _act(client, second, "Approved", route="review").json()["final_decision"] == "Approved"


def test_an_analyst_decides_nothing(client: TestClient, db_session_factory) -> None:
    analyst = _officer(db_session_factory, "analyst1", "analyst")
    application_id = _score(client, STRONG_APPLICANT)["application_id"]

    for action in ("Approved", "Rejected", "Escalated"):
        assert _act(client, application_id, action, analyst).status_code == 403
    assert _act(client, application_id, "Approved", {"Authorization": ""}).status_code == 401
    assert client.get(f"/score/applications/{application_id}").json()["decision_status"] == "Pending"


def test_the_manager_limit_is_enforced_on_the_server(client: TestClient, db_session_factory) -> None:
    """The dashboard is not involved: the request goes straight to the API."""
    manager = _officer(db_session_factory, "manager1", "manager")
    _activate_v2(client, decline_max_score=40, manual_review_max_score=70)  # limit 1,000,000
    within = _score(client, {**MID_APPLICANT, "loan_amount_pkr": 1_000_000})
    above = _score(client, {**MID_APPLICANT, "loan_amount_pkr": 1_000_001,
                            "monthly_digital_payments": 420_000})

    assert within["policy"]["authority"] == {
        "approve_requires": "manager", "manager_approval_limit_pkr": 1_000_000,
        "reason": "within_manager_limit",
    }
    assert above["policy"]["authority"]["approve_requires"] == "admin"
    assert above["policy"]["authority"]["reason"] == "above_manager_limit"

    assert _act(client, within["application_id"], "Approved", manager).status_code == 200
    denied = _act(client, above["application_id"], "Approved", manager)
    assert denied.status_code == 403
    assert "1,000,001" in denied.json()["detail"] and "1,000,000" in denied.json()["detail"]
    assert client.get(f"/score/applications/{above['application_id']}").json()["decision_status"] == "Pending"

    refusal = _entries(db_session_factory, action=Action.APPROVAL_DENIED)[0]
    assert refusal.username == "manager1" and refusal.role == "manager"
    assert refusal.details["reason"] == "above_manager_limit"
    assert refusal.details["manager_approval_limit_pkr"] == 1_000_000
    assert refusal.details["policy_version"] == "2.0"

    # The manager may still reject it; or an admin approves it.
    assert _act(client, above["application_id"], "Approved").status_code == 200


def test_the_limit_follows_the_policy_the_application_was_assessed_under(
    client: TestClient, db_session_factory
) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    assessed_under_v1 = _score(client, MID_APPLICANT)  # 1,200,000 under a 2,000,000 limit
    _activate_v2(client)  # the new policy says 1,000,000

    assert _act(client, assessed_under_v1["application_id"], "Approved", manager).status_code == 200


def test_a_manager_cannot_approve_against_a_decline_recommendation(
    client: TestClient, db_session_factory
) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    body = _score(client, {**WEAK_APPLICANT, "loan_amount_pkr": 100_000})
    assert body["recommendation"] == "Decline"
    assert body["policy"]["authority"]["reason"] == "approval_against_decline_recommendation"

    denied = _act(client, body["application_id"], "Approved", manager)
    assert denied.status_code == 403 and "needs an admin" in denied.json()["detail"]
    refusal = _entries(db_session_factory, action=Action.APPROVAL_DENIED)[0]
    assert refusal.details["reason"] == "approval_against_decline_recommendation"

    assert _act(client, body["application_id"], "Rejected", manager).status_code == 200


def test_a_policy_may_let_a_manager_override_a_decline(client: TestClient, db_session_factory) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    _activate_v2(client, decline_max_score=40, manual_review_max_score=70,
                 decline_override_admin_only=False)
    body = _score(client, {**WEAK_APPLICANT, "loan_amount_pkr": 100_000})

    assert body["recommendation"] == "Decline"
    assert body["policy"]["authority"]["approve_requires"] == "manager"
    assert _act(client, body["application_id"], "Approved", manager).status_code == 200


def test_escalation_hands_the_application_to_an_admin(client: TestClient, db_session_factory) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    other = _officer(db_session_factory, "manager2", "manager")
    application_id = _score(client, MID_APPLICANT)["application_id"]

    escalated = _act(client, application_id, "Escalated", manager)
    assert escalated.status_code == 200
    body = escalated.json()
    assert body["decision_status"] == "Escalated" and body["final_decision"] is None
    record = body["officer_decision"]
    assert record["escalated_by"] == "manager1" and record["escalation_note"] == NOTE
    assert record["escalated_at"] and record["decision"] is None
    assert body["approval_authority"] == "admin"
    assert body["policy"]["authority"]["reason"] == "escalated"

    # It is with the admin now: no manager can decide it, either way.
    for action in ("Approved", "Rejected"):
        for officer in (manager, other):
            refused = _act(client, application_id, action, officer)
            assert refused.status_code == 403 and "escalated by manager1" in refused.json()["detail"]
    assert _act(client, application_id, "Escalated", other).status_code == 409
    assert application_id in [
        row["id"] for row in client.get("/score/applications", params={"pending_review": True}).json()
    ]
    assert [row["id"] for row in client.get(
        "/score/applications", params={"decision_status": "Escalated"}).json()] == [application_id]

    decided = _act(client, application_id, "Approved")
    assert decided.status_code == 200
    final = decided.json()
    assert final["decision_status"] == "Approved" and final["reviewed_by"] == "admin"
    assert final["officer_decision"]["escalated_by"] == "manager1"  # kept on the record

    actions = [e.action for e in _entries(db_session_factory, entity_type="application",
                                          entity_id=str(application_id))]
    assert actions[-6:] == [
        Action.APPLICATION_ESCALATED,
        Action.APPROVAL_DENIED, Action.APPROVAL_DENIED,
        Action.APPROVAL_DENIED, Action.APPROVAL_DENIED,
        Action.OFFICER_DECISION,
    ]
    escalation = _entries(db_session_factory, action=Action.APPLICATION_ESCALATED)[0]
    assert escalation.username == "manager1"
    assert escalation.previous_state == {"decision_status": "Pending"}
    assert escalation.new_state["decision_status"] == "Escalated"
    assert escalation.details["risk_score"] and escalation.details["policy_version"] == "1.0"
    decision = _entries(db_session_factory, action=Action.OFFICER_DECISION)[0]
    assert decision.details["was_escalated"] is True
    assert decision.details["escalated_by"] == "manager1"


def test_an_admin_does_not_escalate(client: TestClient) -> None:
    application_id = _score(client, MID_APPLICANT)["application_id"]
    response = _act(client, application_id, "Escalated")
    assert response.status_code == 409 and "final authority" in response.json()["detail"]


def test_a_decision_is_recorded_once(client: TestClient) -> None:
    application_id = _score(client, STRONG_APPLICANT)["application_id"]
    assert _act(client, application_id, "Approved").status_code == 200

    for action in ("Rejected", "Approved", "Escalated"):
        again = _act(client, application_id, action)
        assert again.status_code == 409 and "already Approved by admin" in again.json()["detail"]


def test_the_decision_record_keeps_what_was_decided_on(
    client: TestClient, db_session_factory
) -> None:
    body = _score(client, MID_APPLICANT)
    _act(client, body["application_id"], "Approved")
    _activate_v2(client, decline_max_score=60, manual_review_max_score=90)  # a later policy

    entry = _entries(db_session_factory, action=Action.OFFICER_DECISION)[0]
    assert entry.new_state["review_decision"] == "Approved"
    assert entry.new_state["reviewed_by"] == "admin" and entry.new_state["review_note"] == NOTE
    assert entry.details["recommendation"] == "Manual Review"
    assert entry.details["risk_score"] == body["risk_score"]
    assert entry.details["policy_version"] == "1.0"
    assert entry.details["model_version"] == body["model_version"]
    assert entry.details["overrides_recommendation"] is False

    stored = client.get(f"/score/applications/{body['application_id']}").json()
    assert stored["recommendation"] == "Manual Review" and stored["policy_version"] == "1.0"
    assert stored["risk_score"] == body["risk_score"] and stored["final_decision"] == "Approved"
    assert stored["officer_decision"]["decided_by"] == "admin"


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "Approved", "note": "too short"},
        {"decision": "Approved"},
        {"decision": "Manual Review", "note": NOTE},
        {"decision": "Pending", "note": NOTE},
        {"decision": "Superseded", "note": NOTE},
    ],
)
def test_a_malformed_decision_is_rejected(client: TestClient, body: dict) -> None:
    application_id = _score(client, MID_APPLICANT)["application_id"]
    assert client.post(f"/score/applications/{application_id}/decision", json=body).status_code == 422


def test_lists_and_totals_follow_the_human_decision(client: TestClient) -> None:
    approved = _score(client, STRONG_APPLICANT)["application_id"]
    _score(client, STRONG_APPLICANT)  # recommended for approval, never decided
    declined = _score(client, WEAK_APPLICANT)["application_id"]
    decide(client, approved, "Approved")
    decide(client, declined, "Rejected")

    stats = client.get("/score/stats").json()
    assert stats["model_decisions"] == {"Rejected": 1, "Manual Review": 0, "Approved": 2}
    assert stats["recommendations"] == {"Decline": 1, "Manual Review": 0, "Approve": 2}
    assert (stats["final_approved"], stats["final_rejected"], stats["pending_review"]) == (1, 1, 1)
    assert stats["approved_exposure_pkr"] == STRONG_APPLICANT["loan_amount_pkr"]

    assert [r["id"] for r in client.get(
        "/score/applications", params={"final_decision": "Approved"}).json()] == [approved]
    matrix = {row["recommendation"]: row for row in client.get(
        "/portfolio/summary").json()["decision_matrix"]}
    assert (matrix["Approve"]["approved"], matrix["Approve"]["pending"]) == (1, 1)
    assert matrix["Decline"]["rejected"] == 1


# === RE-SCORING =====================================================================


def test_a_rescore_keeps_the_earlier_assessment_and_links_the_two(
    client: TestClient, db_session_factory
) -> None:
    first = _score(client, MID_APPLICANT)
    before = _row(db_session_factory, first["application_id"])

    second = _score(
        client,
        {**MID_APPLICANT, "monthly_digital_payments": 2_000_000, "cash_flow_proxy": 600_000},
        rescore_of_application_id=first["application_id"],
    )

    assert second["application_id"] != first["application_id"]
    assert second["supersedes_application_id"] == first["application_id"]
    assert second["borrower_id"] == first["borrower_id"] and second["borrower_created"] is False
    assert second["risk_score"] > first["risk_score"]
    assert second["decision_status"] == "Pending"

    after = _row(db_session_factory, first["application_id"])
    # The earlier assessment is intact: only its status and forward link changed.
    for field in ("risk_score", "decision", "risk_band", "model_version", "scoring_engine",
                  "policy_version", "policy_evaluation", "shap_explanation_json", "reason_codes",
                  "loan_amount_pkr", "monthly_digital_payments", "cash_flow_proxy", "scored_by",
                  "created_at"):
        assert getattr(after, field) == getattr(before, field), field
    assert after.decision_status == "Superseded"
    assert after.superseded_by_application_id == second["application_id"]
    assert client.get(f"/explain/{first['application_id']}").json()["risk_score"] == first["risk_score"]


def test_a_rescore_is_audited_with_who_and_what_changed(
    client: TestClient, db_session_factory
) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    first = _score(client, MID_APPLICANT)
    second = client.post(
        "/score",
        json={**MID_APPLICANT, "monthly_digital_payments": 2_000_000,
              "rescore_of_application_id": first["application_id"]},
        headers=manager,
    ).json()

    entry = _entries(db_session_factory, action=Action.APPLICATION_RESCORED)[0]
    assert entry.entity_id == str(second["application_id"])
    assert (entry.username, entry.role) == ("manager1", "manager") and entry.occurred_at
    assert entry.previous_state == {
        "application_id": first["application_id"],
        "scored_by": "admin",
        "risk_score": first["risk_score"],
        "risk_band": "Medium Risk",
        "recommendation": "Manual Review",
        "model_version": first["model_version"],
        "scoring_engine": "surrogate",
        "policy_version": "1.0",
        "decision_status": "Pending",
    }
    assert entry.new_state["risk_score"] == second["risk_score"]
    assert entry.new_state["policy_version"] == "1.0"
    assert entry.details["inputs_changed"] == {"monthly_digital_payments": [500_000.0, 2_000_000.0]}
    assert entry.details["inputs_unchanged"] is False
    assert entry.details["score_change"] == round(second["risk_score"] - first["risk_score"], 2)
    assert entry.details["rescore_number"] == 1

    superseded = _entries(db_session_factory, action=Action.APPLICATION_SUPERSEDED)[0]
    assert superseded.entity_id == str(first["application_id"])
    assert superseded.new_state == {
        "decision_status": "Superseded",
        "superseded_by_application_id": second["application_id"],
    }
    created = [e for e in _entries(db_session_factory, action=Action.APPLICATION_CREATED)
               if e.entity_id == str(second["application_id"])][0]
    assert created.details["rescore_of_application_id"] == first["application_id"]
    assert created.details["borrower_prior_applications"] == 1


def test_a_rescore_under_a_new_policy_and_model_keeps_both_versions(
    ml_client: TestClient, ml_service, db_session_factory
) -> None:
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService()
    first = _score(ml_client, MID_APPLICANT)
    _activate_v2(ml_client)
    app.dependency_overrides[get_scoring_service] = lambda: ml_service
    second = _score(ml_client, MID_APPLICANT, rescore_of_application_id=first["application_id"])

    old, new = _row(db_session_factory, first["application_id"]), _row(db_session_factory, second["application_id"])
    assert (old.model_version, old.scoring_engine, old.policy_version) == ("surrogate-linear-v1", "surrogate", "1.0")
    assert (new.model_version, new.scoring_engine, new.policy_version) == (ml_service.model_version, "ml", "2.0")

    history = ml_client.get(f"/score/applications/{second['application_id']}/decision-history").json()
    assert [(a["application_id"], a["model_version"], a["policy_version"], a["decision_status"])
            for a in history["assessments"]] == [
        (first["application_id"], "surrogate-linear-v1", "1.0", "Superseded"),
        (second["application_id"], ml_service.model_version, "2.0", "Pending"),
    ]


def test_a_superseded_or_decided_application_is_closed(client: TestClient) -> None:
    first = _score(client, MID_APPLICANT)
    second = _score(client, MID_APPLICANT, rescore_of_application_id=first["application_id"])

    stale = _act(client, first["application_id"], "Approved")
    assert stale.status_code == 409 and str(second["application_id"]) in stale.json()["detail"]
    again = client.post("/score", json={**MID_APPLICANT, "rescore_of_application_id": first["application_id"]})
    assert again.status_code == 409 and "Superseded" in again.json()["detail"]

    decide(client, second["application_id"], "Approved")
    decided = client.post("/score", json={**MID_APPLICANT, "rescore_of_application_id": second["application_id"]})
    assert decided.status_code == 409 and "Approved" in decided.json()["detail"]
    assert client.post("/score", json={**MID_APPLICANT, "rescore_of_application_id": 9999}).status_code == 404
    assert len(client.get("/score/applications").json()) == 2


def test_a_rescore_stays_with_its_borrower(client: TestClient) -> None:
    first = _score(client, MID_APPLICANT)
    other = _score(client, STRONG_APPLICANT)
    wrong = client.post(
        "/score",
        json={**MID_APPLICANT, "rescore_of_application_id": first["application_id"],
              "borrower_public_id": other["borrower_public_id"]},
    )
    assert wrong.status_code == 409 and first["borrower_public_id"] in wrong.json()["detail"]


def test_totals_count_an_application_once_however_often_it_is_rescored(client: TestClient) -> None:
    first = _score(client, MID_APPLICANT)
    second = _score(client, MID_APPLICANT, rescore_of_application_id=first["application_id"])
    _score(client, MID_APPLICANT, rescore_of_application_id=second["application_id"])

    stats = client.get("/score/stats").json()
    assert stats["total_applications"] == 1 and stats["superseded_assessments"] == 2
    assert stats["pending_review"] == 1
    assert sum(bucket["count"] for bucket in stats["score_histogram"]) == 1
    assert len(client.get("/score/applications").json()) == 3  # all three are still on file
    assert len(client.get("/score/applications", params={"decision_status": "Superseded"}).json()) == 2


def test_repeat_applications_for_a_borrower_are_counted_in_the_trail(
    client: TestClient, db_session_factory
) -> None:
    first = _score(client, MID_APPLICANT)
    _score(client, {**MID_APPLICANT, "loan_amount_pkr": 900_000},
           borrower_public_id=first["borrower_public_id"])

    created = _entries(db_session_factory, action=Action.APPLICATION_CREATED)
    assert created[0].details["borrower_prior_applications"] == 0
    assert created[1].details["borrower_prior_applications"] == 1
    assert created[1].details["borrower_previous_application_id"] == first["application_id"]


# === DECISION HISTORY ===============================================================


def test_decision_history_tells_the_whole_story_in_order(client: TestClient, db_session_factory) -> None:
    manager = _officer(db_session_factory, "manager1", "manager")
    first = _score(client, MID_APPLICANT)
    second = _score(client, MID_APPLICANT, rescore_of_application_id=first["application_id"])
    _act(client, second["application_id"], "Escalated", manager)
    _act(client, second["application_id"], "Approved", manager)  # refused
    _act(client, second["application_id"], "Approved")

    for application_id in (first["application_id"], second["application_id"]):
        history = client.get(f"/score/applications/{application_id}/decision-history")
        assert history.status_code == 200, history.text
        body = history.json()
        assert [a["application_id"] for a in body["assessments"]] == [
            first["application_id"], second["application_id"]]
        assert body["assessments"][0]["superseded_by_application_id"] == second["application_id"]
        assert body["assessments"][1]["decision_status"] == "Approved"
        assert body["assessments"][1]["decided_by"] == "admin"
        assert [(e["application_id"], e["action"]) for e in body["events"]] == [
            (first["application_id"], "application.created"),
            (first["application_id"], "application.scored"),
            (first["application_id"], "recommendation.generated"),
            (first["application_id"], "explanation.generated"),
            (second["application_id"], "application.created"),
            (second["application_id"], "application.scored"),
            (second["application_id"], "recommendation.generated"),
            (second["application_id"], "explanation.generated"),
            (first["application_id"], "application.superseded"),
            (second["application_id"], "application.rescored"),
            (second["application_id"], "application.escalated"),
            (second["application_id"], "application.approval_denied"),
            (second["application_id"], "application.officer_decision"),
        ]
        assert body["events"][-1]["actor"] == "admin" and body["events"][-2]["actor"] == "manager1"
        assert body["note"] is None
    assert client.get("/score/applications/9999/decision-history").status_code == 404
    assert client.get(f"/score/applications/{first['application_id']}/decision-history",
                      headers={"Authorization": ""}).status_code == 401


# === REASON CODES ===================================================================


def _contribution(feature: str, points: float) -> ShapFeatureContribution:
    return ShapFeatureContribution(
        feature=feature, label=feature, value=0.0, contribution=points,
        direction="increases" if points >= 0 else "decreases", weight=0.1,
    )


def test_reason_codes_are_the_largest_risk_factors_in_order() -> None:
    codes = reason_codes_for([
        _contribution("years_in_operation", -3.0),
        _contribution("loan_to_income", -12.5),
        _contribution("payment_history_score", 6.0),  # helped: no code
    ])
    assert [(c.code, c.feature, c.points) for c in codes] == [
        ("R01", "loan_to_income", -12.5),
        ("R03", "years_in_operation", -3.0),
    ]
    assert codes[0].label == "Facility is large against annual turnover"


def test_reason_codes_are_deterministic_bounded_and_ignore_noise() -> None:
    contributions = [_contribution(feature, -5.0) for feature in sorted(REASON_CODES)]
    first, second = reason_codes_for(contributions), reason_codes_for(list(reversed(contributions)))
    assert first == second and len(first) == MAX_CODES

    assert reason_codes_for([_contribution("loan_to_income", -(MIN_POINTS - 0.01))]) == []
    assert len(reason_codes_for([_contribution("loan_to_income", -MIN_POINTS)])) == 1
    # A feature with no documented code gets none; nothing is invented for it.
    assert reason_codes_for([_contribution("not_a_model_feature", -30.0)]) == []


def test_codes_exist_only_for_features_an_explanation_can_contain(ml_service) -> None:
    from ml.features import FEATURE_NAMES
    from services.scoring_service import FEATURE_WEIGHTS

    explainable = set(FEATURE_NAMES) | set(FEATURE_WEIGHTS)
    assert set(REASON_CODES) == explainable
    assert set(ml_service.feature_names) <= set(REASON_CODES)
    # One meaning per code.
    meanings: dict[str, set[str]] = {}
    for code, label in REASON_CODES.values():
        meanings.setdefault(code, set()).add(label.split(" against ")[0])
    assert all(len(labels) == 1 for labels in meanings.values())


def test_reason_codes_come_from_the_shap_values_and_leave_them_untouched(
    ml_client: TestClient, db_session_factory
) -> None:
    body = _score(ml_client, WEAK_APPLICANT)
    explanation = body["explanation"]
    contributions = {c["feature"]: c["contribution"] for c in explanation["feature_contributions"]}

    assert body["reason_codes"] == explanation["reason_codes"] and body["reason_codes"]
    for code in body["reason_codes"]:
        assert code["points"] == contributions[code["feature"]] < 0
        assert (code["code"], code["label"]) == REASON_CODES[code["feature"]]
    # SHAP is exactly as before: base value plus contributions is the score.
    assert explanation["base_value"] + sum(contributions.values()) == pytest.approx(
        body["risk_score"], abs=0.02
    )
    assert _row(db_session_factory, body["application_id"]).reason_codes == body["reason_codes"]
    stored = ml_client.get(f"/score/applications/{body['application_id']}").json()
    assert stored["reason_codes"] == body["reason_codes"]
    assert ml_client.get(f"/explain/{body['application_id']}").json()["reason_codes"] == body["reason_codes"]


def test_an_explanation_stored_before_reason_codes_gets_them_on_read(
    client: TestClient, db_session_factory
) -> None:
    import json

    body = _score(client, WEAK_APPLICANT)
    db = db_session_factory()
    try:
        row = db.get(Application, body["application_id"])
        stored = json.loads(row.shap_explanation_json)
        for key in ("reason_codes", "recommendation", "policy_version"):
            stored.pop(key)
        row.shap_explanation_json = json.dumps(stored)
        db.commit()
    finally:
        db.close()

    read = client.get(f"/explain/{body['application_id']}").json()
    assert read["reason_codes"] == body["reason_codes"]
    assert read["recommendation"] == "Decline" and read["policy_version"] is None
    # Derived on read only: the stored record was not rewritten.
    assert "reason_codes" not in json.loads(_row(db_session_factory, body["application_id"]).shap_explanation_json)


# === the service boundaries ==========================================================


def test_policy_evaluation_is_structured_not_a_string(client: TestClient, db_session_factory) -> None:
    db = db_session_factory()
    try:
        policy = policy_service.active_policy(db)
        evaluation = policy_service.evaluate(policy, 55.5, 3_000_000)
        db.commit()
    finally:
        db.close()

    assert evaluation.recommendation is Decision.MANUAL_REVIEW
    assert evaluation.risk_band is RiskBand.MEDIUM
    assert (evaluation.policy_version, evaluation.policy_name) == ("1.0", "Demo Credit Policy")
    assert evaluation.approve_requires == "admin" and evaluation.authority_reason == "above_manager_limit"
    assert [rule["rule"] for rule in evaluation.triggered_rules] == [
        "score_at_or_below_manual_review_max", "above_manager_limit"]
    assert evaluation.manager_approval_limit_pkr == 2_000_000
    assert "Recommendation: Manual Review" in evaluation.reason


def test_the_scoring_service_holds_no_policy_rules() -> None:
    """The cut-offs and the authority rule live in the policy layer."""
    import inspect

    from services import scoring_service

    source = inspect.getsource(scoring_service)
    assert "manager_approval_limit" not in source
    assert "= 40.0" not in source and "= 70.0" not in source
    assert scoring_service.REJECT_UPPER_BOUND == policy_rules.DEMO_DECLINE_MAX_SCORE
    assert scoring_service.MANUAL_REVIEW_UPPER_BOUND == policy_rules.DEMO_MANUAL_REVIEW_MAX_SCORE
