"""Migration 0007 and the Phase 2 workflow on real PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (CI sets it).
"""

from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from main import app
from models.database import Base, get_db
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT, decide, seed_test_admin
from tests.test_postgres_phase1 import POSTGRES_URL, _alembic, _reset

pytestmark = pytest.mark.postgres

ENSEMBLE = "ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26"

# Five applications as release 1.10 stored them: (id, band, officer decision,
# decided by, explanation).
LEGACY = [
    (1, "Approved", None, None, {"model_version": ENSEMBLE, "probability_of_default": 0.0712}),
    (2, "Rejected", None, None, {"model_version": ENSEMBLE, "probability_of_default": 0.828}),
    (3, "Manual Review", "Approved", "idreesi", {"model_version": ENSEMBLE}),
    (4, "Manual Review", "Rejected", "idreesi", None),
    (5, "Manual Review", None, None, {"probability_of_default": "not a number"}),
]


def _insert_legacy(connection) -> None:
    for app_id, band, review, reviewer, explanation in LEGACY:
        connection.execute(
            text(
                "INSERT INTO borrowers (id, public_id, business_name, owner_name, status, "
                "created_at, updated_at) VALUES (:id, :ref, 'Shop', 'Owner', 'active', now(), now())"
            ),
            {"id": app_id, "ref": f"BRW-{app_id:06d}"},
        )
        connection.execute(
            text(
                "INSERT INTO applications (id, borrower_id, applicant_name, business_name, "
                "loan_amount_pkr, tenure_months, monthly_digital_payments, payment_history_score, "
                "inventory_turnover, order_consistency, existing_debt_pkr, cash_flow_proxy, "
                "years_in_operation, num_employees, risk_score, decision, shap_explanation_json, "
                "model_version, scoring_engine, review_decision, review_note, reviewed_by, "
                "reviewed_at, scored_by, created_at) VALUES (:id, :id, 'Owner', 'Shop', 500000, 12, "
                "150000, 95, 5, 60, 0, 150000, 5, 6, :score, :band, :explanation, :model, 'ml', "
                ":review, :note, :reviewer, CASE WHEN :review IS NULL THEN NULL ELSE now() END, "
                "'idreesi', now())"
            ),
            {
                "id": app_id,
                "score": {"Approved": 75.9, "Rejected": 4.6, "Manual Review": 56.7}[band],
                "band": band,
                "explanation": json.dumps(explanation) if explanation else None,
                "model": ENSEMBLE,
                "review": review,
                "note": "Decided on the file." if review else None,
                "reviewer": reviewer,
            },
        )
    connection.execute(
        text(
            "INSERT INTO ews_tracking (borrower_id, month_number, installment_status, "
            "bureau_balance, pos_cash_balance, monthly_score, data_source_primary) "
            "VALUES (1, 1, 'On Time', 1, 1, 75.9, 'ECIB')"
        )
    )
    for table in ("borrowers", "applications"):
        connection.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"(SELECT MAX(id) FROM {table}))"
            )
        )


@pytest.fixture(name="pg_engine", scope="module")
def pg_engine_fixture():
    if not POSTGRES_URL:
        pytest.skip("FORIFLOW_TEST_POSTGRES_URL is not set")
    engine = create_engine(POSTGRES_URL, future=True, pool_pre_ping=True)
    yield engine
    _reset(engine)
    _alembic("head")
    engine.dispose()


@pytest.fixture(name="migrated")
def migrated_fixture(pg_engine, monkeypatch):
    """A 1.10 database with five legacy applications, upgraded to head."""
    monkeypatch.setenv("MANAGER_APPROVAL_LIMIT_PKR", "1500000")
    _reset(pg_engine)
    _alembic("0006_borrowers_audit_models")
    with pg_engine.begin() as connection:
        _insert_legacy(connection)
    _alembic("head")
    return pg_engine


# --- the migration ------------------------------------------------------------------


def test_the_demo_policy_is_seeded_active_with_the_configured_limit(migrated) -> None:
    with migrated.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT version, name, status, decline_max_score, manual_review_max_score, "
                "manager_approval_limit_pkr, decline_override_admin_only, created_by, "
                "activated_at IS NOT NULL AS activated FROM credit_policies"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("1.0", "Demo Credit Policy", "active", 40.0, 70.0, 1_500_000.0, True, "system", True)
    ]


def test_existing_applications_keep_what_their_own_record_said(migrated) -> None:
    with migrated.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, decision, decision_status, decision_source, review_decision, "
                "reviewed_by, risk_band, calibrated_pd, raw_pd, policy_id, policy_version, "
                "policy_evaluation, reason_codes, risk_score, model_version "
                "FROM applications ORDER BY id"
            )
        ).mappings().all()

    assert [(r["id"], r["decision"], r["decision_status"], r["decision_source"]) for r in rows] == [
        (1, "Approved", "Approved", "legacy_auto"),  # the band alone was final then
        (2, "Rejected", "Rejected", "legacy_auto"),
        (3, "Manual Review", "Approved", "officer"),
        (4, "Manual Review", "Rejected", "officer"),
        (5, "Manual Review", "Pending", None),
    ]
    # No officer is invented for the two the band decided.
    assert [r["reviewed_by"] for r in rows] == [None, None, "idreesi", "idreesi", None]
    assert [r["review_decision"] for r in rows] == [None, None, "Approved", "Rejected", None]
    # No policy version is claimed for any of them.
    assert all(r["policy_id"] is None and r["policy_version"] is None for r in rows)
    assert all(r["policy_evaluation"] is None and r["reason_codes"] is None for r in rows)
    assert [r["risk_band"] for r in rows] == [
        "Low Risk", "High Risk", "Medium Risk", "Medium Risk", "Medium Risk"]
    # Copied where it was stored; never made up.
    assert [r["calibrated_pd"] for r in rows] == [0.0712, 0.828, None, None, None]
    assert all(r["raw_pd"] is None for r in rows)
    assert [r["risk_score"] for r in rows] == [75.9, 4.6, 56.7, 56.7, 56.7]
    assert all(r["model_version"] == ENSEMBLE for r in rows)


def test_the_migration_is_audited(migrated) -> None:
    with migrated.connect() as connection:
        entries = connection.execute(
            text(
                "SELECT action, username, details FROM audit_logs "
                "WHERE action LIKE 'policy.%' OR entity_id = '0007_policy_human_decision' "
                "ORDER BY id"
            )
        ).all()
    assert [(e.action, e.username) for e in entries] == [
        ("policy.created", "system"),
        ("policy.activated", "system"),
        ("migration.applied", "system"),
    ]
    details = entries[2].details
    assert details["applications_backfilled"] == 5
    assert details["decision_status_recorded"] == {
        "Approved (legacy_auto)": 1,
        "Rejected (legacy_auto)": 1,
        "Approved (officer)": 1,
        "Rejected (officer)": 1,
        "Pending (undecided)": 1,
    }
    assert details["policy_version_assigned_to_existing_applications"] is None


def test_the_schema_matches_the_models(migrated) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_constraints_on_policies_and_decisions(migrated) -> None:
    inspector = inspect(migrated)
    columns = {c["name"]: c for c in inspector.get_columns("applications")}
    assert columns["decision_status"]["nullable"] is False
    assert columns["policy_id"]["nullable"] is True
    assert str(columns["policy_evaluation"]["type"]) == "JSONB"

    policy = text(
        "INSERT INTO credit_policies (version, name, status, decline_max_score, "
        "manual_review_max_score, manager_approval_limit_pkr, decline_override_admin_only, "
        "created_at, created_by) VALUES (:version, 'x policy', :status, :low, :high, :limit, "
        "true, now(), 'test')"
    )
    good = {"version": "t1", "status": "draft", "low": 40, "high": 70, "limit": 1}
    with migrated.begin() as connection:
        connection.execute(policy, good)
    for change, message in (
        ({"version": "t2", "status": "active"}, "uq_credit_policies_one_active"),
        ({"version": "t1"}, "credit_policies_version_key"),
        ({"version": "t3", "low": 70, "high": 70}, "ck_credit_policies_bands"),
        ({"version": "t4", "high": 101}, "ck_credit_policies_bands"),
        ({"version": "t5", "limit": -1}, "ck_credit_policies_manager_limit"),
        ({"version": "t6", "status": "deleted"}, "ck_credit_policies_status"),
    ):
        with pytest.raises(IntegrityError, match=message):
            with migrated.begin() as connection:
                connection.execute(policy, {**good, **change})

    for statement, message in (
        ("UPDATE applications SET decision_status = 'Maybe' WHERE id = 1", "ck_applications_decision_status"),
        ("UPDATE applications SET decision_source = 'robot' WHERE id = 1", "ck_applications_decision_source"),
        ("UPDATE applications SET policy_id = 999 WHERE id = 1", "fk_applications_policy_id"),
        ("UPDATE applications SET supersedes_application_id = 999 WHERE id = 1", "fk_applications_supersedes"),
    ):
        with pytest.raises(IntegrityError, match=message):
            with migrated.begin() as connection:
                connection.execute(text(statement))


def test_downgrade_and_upgrade_again_keep_the_applications(migrated) -> None:
    _alembic("0006_borrowers_audit_models", down=True)
    inspector = inspect(migrated)
    assert "credit_policies" not in inspector.get_table_names()
    assert "decision_status" not in {c["name"] for c in inspector.get_columns("applications")}
    with migrated.connect() as connection:
        kept = connection.execute(
            text("SELECT id, decision, review_decision FROM applications ORDER BY id")
        ).all()
    assert [tuple(row) for row in kept] == [(a, b, c) for a, b, c, _, _ in LEGACY]

    _alembic("head")
    with migrated.connect() as connection:
        statuses = connection.execute(
            text("SELECT decision_status FROM applications ORDER BY id")
        ).scalars().all()
    assert statuses == ["Approved", "Rejected", "Approved", "Rejected", "Pending"]


# --- the workflow on PostgreSQL -----------------------------------------------------


@pytest.fixture(name="pg_client")
def pg_client_fixture(migrated, client: TestClient) -> Generator[TestClient, None, None]:
    factory = sessionmaker(bind=migrated, autoflush=False, expire_on_commit=False)
    bootstrap = factory()
    try:
        seed_test_admin(bootstrap)
    finally:
        bootstrap.close()

    def override() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = override
    try:
        yield client
    finally:
        app.dependency_overrides[get_db] = previous


def test_legacy_applications_read_honestly_through_the_api(pg_client: TestClient) -> None:
    rows = {row["id"]: row for row in pg_client.get("/score/applications").json()}

    band_decided = rows[1]
    assert band_decided["recommendation"] == "Approve" and band_decided["final_decision"] == "Approved"
    assert band_decided["officer_decision"]["source"] == "legacy_auto"
    assert band_decided["officer_decision"]["decided_by"] is None
    assert band_decided["policy_version"] is None
    assert "before policy versions were recorded" in band_decided["policy"]["reason"]
    assert band_decided["assessment"]["probability_of_default"] == 0.0712
    assert band_decided["assessment"]["probability_of_default_raw"] is None

    assert rows[3]["officer_decision"]["source"] == "officer"
    assert rows[3]["officer_decision"]["decided_by"] == "idreesi"
    assert rows[5]["decision_status"] == "Pending"
    # An undecided legacy application is governed by the policy in force today.
    assert rows[5]["manager_approval_limit_pkr"] == 1_500_000
    assert rows[5]["approval_authority"] == "manager"

    # The facility approved before 2.0 is still a facility.
    month = pg_client.post(
        "/ews/monitor",
        json={"borrower_id": 1, "month_number": 2, "installment_status": "On Time",
              "bureau_balance": 1, "pos_cash_balance": 1_000_000},
    )
    assert month.status_code == 201, month.text
    stats = pg_client.get("/score/stats").json()
    assert (stats["final_approved"], stats["final_rejected"], stats["pending_review"]) == (2, 2, 1)
    assert pg_client.get("/portfolio/summary").json()["approved_facilities"] == 2

    already = pg_client.post(
        "/score/applications/1/decision", json={"decision": "Rejected", "note": "Trying to undo it."}
    )
    assert already.status_code == 409 and "before release 2.0" in already.json()["detail"]

    history = pg_client.get("/score/applications/1/decision-history").json()
    assert history["assessments"][0]["policy_version"] is None
    assert history["events"] == [] and "before the audit trail existed" in history["note"]

    # The legacy pending one can be decided now, and the trail says under what.
    decide(pg_client, 5, "Approved")
    assert pg_client.get("/score/applications/5").json()["officer_decision"]["source"] == "officer"


def test_the_phase_two_workflow_on_postgres(pg_client: TestClient) -> None:
    """Assess, recommend, explain, escalate, decide, audit; then change the policy."""
    scored = pg_client.post("/score", json=MID_APPLICANT)
    assert scored.status_code == 201, scored.text
    first = scored.json()
    assert first["recommendation"] == "Manual Review" and first["decision_status"] == "Pending"
    assert first["policy"]["policy_version"] == "1.0"
    assert first["policy"]["authority"]["manager_approval_limit_pkr"] == 1_500_000
    assert first["reason_codes"] and first["explanation"]["feature_contributions"]

    created = pg_client.post(
        "/policy/versions",
        json={"version": "1.1", "name": "Pilot Credit Policy", "decline_max_score": 60,
              "manual_review_max_score": 90, "manager_approval_limit_pkr": 500_000},
    )
    assert created.status_code == 201, created.text
    assert pg_client.post(f"/policy/versions/{created.json()['id']}/activate").status_code == 200
    statuses = {row["version"]: row["status"] for row in pg_client.get("/policy/versions").json()}
    assert statuses == {"1.0": "retired", "1.1": "active"}

    second = pg_client.post(
        "/score", json={**MID_APPLICANT, "rescore_of_application_id": first["application_id"]}
    ).json()
    assert second["recommendation"] == "Decline" and second["policy_version"] == "1.1"
    assert second["risk_score"] == first["risk_score"]

    kept = pg_client.get(f"/score/applications/{first['application_id']}").json()
    assert kept["recommendation"] == "Manual Review" and kept["policy_version"] == "1.0"
    assert kept["decision_status"] == "Superseded"
    assert kept["officer_decision"]["superseded_by_application_id"] == second["application_id"]

    approved = decide(pg_client, second["application_id"], "Approved")
    assert approved["officer_decision"]["overrides_recommendation"] is True

    history = pg_client.get(
        f"/score/applications/{second['application_id']}/decision-history"
    ).json()
    assert [a["policy_version"] for a in history["assessments"]] == ["1.0", "1.1"]
    assert [e["action"] for e in history["events"]][-3:] == [
        "application.superseded", "application.rescored", "application.officer_decision"]

    weak = pg_client.post("/score", json=WEAK_APPLICANT).json()
    strong = pg_client.post("/score", json=STRONG_APPLICANT).json()
    assert weak["decision_status"] == strong["decision_status"] == "Pending"
    trail = pg_client.get("/audit/logs", params={"action": "recommendation.generated"}).json()
    assert len(trail) == 4 and trail[0]["details"]["policy_version"] == "1.1"
