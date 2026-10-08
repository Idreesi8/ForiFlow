"""Migration 0008 and the EWS 2.1 workflow on real PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (CI sets it).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from main import app
from models.database import Base, get_db
from scripts.migrate_sqlite_to_postgres import EXPECTED_0007, OPTIONAL, migrate
from tests.conftest import STRONG_APPLICANT, decide, seed_test_admin
from tests.test_postgres_phase1 import POSTGRES_URL, _alembic, _reset

pytestmark = pytest.mark.postgres

APPLICATION = (
    "INSERT INTO applications (id, borrower_id, applicant_name, business_name, loan_amount_pkr, "
    "tenure_months, monthly_digital_payments, payment_history_score, inventory_turnover, "
    "order_consistency, existing_debt_pkr, cash_flow_proxy, years_in_operation, num_employees, "
    "risk_score, decision, decision_status, decision_source, risk_band, created_at) VALUES "
    "(:id, :id, 'Owner', :name, 1200000, 24, 150000, 90, 5, 60, 0, 200000, 5, 6, 76.5, "
    "'Approved', 'Approved', 'legacy_auto', 'Low Risk', now() - interval '90 days')"
)


def _insert_legacy(connection, *, extra_open_alert: bool = False, duplicate_month: bool = False) -> None:
    """Three approved facilities as release 2.0 stored them."""
    for app_id in (1, 2, 3):
        connection.execute(
            text(
                "INSERT INTO borrowers (id, public_id, business_name, owner_name, status, "
                "created_at, updated_at) VALUES (:id, :ref, 'Shop', 'Owner', 'active', now(), now())"
            ),
            {"id": app_id, "ref": f"BRW-{app_id:06d}"},
        )
        connection.execute(text(APPLICATION), {"id": app_id, "name": f"Shop {app_id}"})
    months = [(1, 1, "On Time", 76.5), (1, 2, "Late 60-89", 50.5), (2, 1, "Default", 31.5), (3, 1, "On Time", 76.5)]
    if duplicate_month:
        months.append((3, 1, "Late 1-29", 70.5))
    for borrower, month, status, score in months:
        connection.execute(
            text(
                "INSERT INTO ews_tracking (borrower_id, month_number, installment_status, "
                "bureau_balance, pos_cash_balance, monthly_score, data_source_primary) "
                "VALUES (:b, :m, :s, 1000000, 200000, :score, 'ECIB')"
            ),
            {"b": borrower, "m": month, "s": status, "score": score},
        )
    alerts = [
        (1, 26.0, "Active", None),
        (2, 45.0, "In Review", "idreesi"),
        (3, 20.0, "Resolved", "idreesi"),
    ]
    if extra_open_alert:
        alerts.append((1, 30.0, "In Review", "zakria"))
    for borrower, drop, status, who in alerts:
        connection.execute(
            text(
                "INSERT INTO alerts (borrower_id, baseline_score, current_score, score_drop, "
                "estimated_days_to_default, alert_status, triggered_at, assigned_to, resolved_by, "
                "resolved_at, resolution_note) VALUES (:b, 76.5, 76.5 - :drop, :drop, 45, :status, "
                "now() - interval '10 days', :who, "
                "CASE WHEN :status = 'Resolved' THEN :who END, "
                "CASE WHEN :status = 'Resolved' THEN now() END, "
                "CASE WHEN :status = 'Resolved' THEN 'Paid arrears.' END)"
            ),
            {"b": borrower, "drop": drop, "status": status, "who": who},
        )
    for table in ("borrowers", "applications"):
        connection.execute(
            text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT MAX(id) FROM {table}))")
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


def _at_0007(engine, **legacy) -> None:
    _reset(engine)
    _alembic("0007_policy_human_decision")
    with engine.begin() as connection:
        _insert_legacy(connection, **legacy)


@pytest.fixture(name="migrated")
def migrated_fixture(pg_engine):
    """A 2.0 database with three monitored facilities, upgraded to head."""
    _at_0007(pg_engine)
    _alembic("head")
    return pg_engine


def _rows(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql)).all()]


# --- the migration ------------------------------------------------------------------


def test_legacy_observations_are_kept_and_marked_unknown(migrated) -> None:
    rows = _rows(
        migrated,
        "SELECT borrower_id, month_number, installment_status, monthly_score, score_source, "
        "record_status, observation_date, created_by FROM ews_tracking ORDER BY id",
    )
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (1, 1, "On Time", 76.5), (1, 2, "Late 60-89", 50.5), (2, 1, "Default", 31.5), (3, 1, "On Time", 76.5),
    ]
    assert {(r[4], r[5]) for r in rows} == {("legacy_unknown", "active")}
    assert {(r[6], r[7]) for r in rows} == {(None, None)}  # never recorded, not invented


def test_alert_statuses_are_renamed_and_nothing_is_invented(migrated) -> None:
    rows = _rows(
        migrated,
        "SELECT borrower_id, alert_status, acknowledged_by, acknowledged_at, severity, "
        "reason_codes, resolved_by FROM alerts ORDER BY id",
    )
    assert rows == [
        (1, "Open", None, None, None, None, None),
        (2, "Acknowledged", "idreesi", None, None, None, None),
        (3, "Resolved", None, None, None, None, "idreesi"),
    ]


def test_the_migration_is_audited(migrated) -> None:
    (details,) = _rows(
        migrated,
        "SELECT details FROM audit_logs WHERE action = 'migration.applied' "
        "AND entity_id = '0008_ews_history_alerts'",
    )[0]
    assert details["observations_marked_legacy_unknown"] == 4
    assert details["duplicate_months_kept_as_superseded"] == 0
    assert details["alert_statuses_renamed"] == {"Active -> Open": 1, "In Review -> Acknowledged": 1}


def test_the_schema_matches_the_models(migrated) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_the_database_enforces_history_and_one_open_alert(migrated) -> None:
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ews_tracking (borrower_id, month_number, installment_status, "
                    "bureau_balance, pos_cash_balance, monthly_score, data_source_primary, "
                    "score_source, record_status) VALUES (1, 1, 'On Time', 1, 1, 70, 'ECIB', "
                    "'ews_rule_adjusted', 'active')"
                )
            )
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO alerts (borrower_id, baseline_score, current_score, score_drop, "
                    "estimated_days_to_default, alert_status, triggered_at) "
                    "VALUES (1, 76.5, 40, 36.5, 30, 'Action Required', now())"
                )
            )
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ews_tracking (borrower_id, month_number, installment_status, "
                    "bureau_balance, pos_cash_balance, monthly_score, data_source_primary, "
                    "score_source, record_status) VALUES (1, 9, 'On Time', 1, 1, 70, 'ECIB', "
                    "'officer_override', 'active')"
                )
            )  # an override without a reason
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(text("UPDATE alerts SET alert_status = 'Active' WHERE id = 3"))


def test_duplicate_months_are_kept_as_history(pg_engine) -> None:
    _at_0007(pg_engine, duplicate_month=True)
    _alembic("head")
    rows = _rows(
        pg_engine,
        "SELECT id, installment_status, record_status, superseded_by_observation_id, correction_reason "
        "FROM ews_tracking WHERE borrower_id = 3 ORDER BY id",
    )
    (old_id, old_status, old_record, old_link, old_note), (new_id, new_status, new_record, _, _) = rows
    assert (old_status, old_record, old_link) == ("On Time", "superseded", new_id)
    assert "Migration 0008" in old_note
    assert (new_status, new_record) == ("Late 1-29", "active")


def test_two_open_alerts_on_one_facility_stop_the_migration(pg_engine) -> None:
    _at_0007(pg_engine, extra_open_alert=True)
    with pytest.raises(RuntimeError, match="more than one open alert"):
        _alembic("head")
    assert _rows(pg_engine, "SELECT version_num FROM alembic_version") == [("0007_policy_human_decision",)]
    assert _rows(pg_engine, "SELECT COUNT(*) FROM alerts WHERE alert_status = 'In Review'") == [(2,)]


def test_downgrade_and_upgrade_again_keep_the_history(migrated) -> None:
    _alembic("0007_policy_human_decision", down=True)
    assert _rows(migrated, "SELECT alert_status FROM alerts ORDER BY id") == [
        ("Active",), ("In Review",), ("Resolved",)
    ]
    assert _rows(migrated, "SELECT COUNT(*) FROM ews_tracking") == [(4,)]
    _alembic("head")
    assert _rows(migrated, "SELECT alert_status FROM alerts ORDER BY id") == [
        ("Open",), ("Acknowledged",), ("Resolved",)
    ]


# --- the API on PostgreSQL ----------------------------------------------------------


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


def test_legacy_ews_records_read_honestly(pg_client: TestClient) -> None:
    alerts = {a["id"]: a for a in pg_client.get("/ews/alerts").json()}
    assert alerts[1]["alert_status"] == "Open" and alerts[1]["is_legacy"] is True
    assert alerts[1]["severity"] is None and alerts[1]["reason_codes"] is None
    assert alerts[2]["acknowledged_by"] == "idreesi" and alerts[2]["acknowledged_at"] is None
    assert alerts[3]["alert_status"] == "Resolved"

    months = pg_client.get("/ews/facilities/1/observations").json()
    assert [m["score_source"] for m in months] == ["legacy_unknown", "legacy_unknown"]
    assert months[0]["score_source_label"] == "Unknown (recorded before 2.1)"

    overview = pg_client.get("/ews/overview").json()
    assert overview["monitored_facilities"] == 3
    assert overview["state_counts"] == {"NORMAL": 1, "WATCH": 0, "WARNING": 0, "CRITICAL": 2}
    assert overview["open_alerts"] == 2

    timeline = pg_client.get("/ews/facilities/1/timeline").json()
    assert {e["source"] for e in timeline["events"]} == {"record"}
    assert "predate the audit trail" in timeline["note"]
    # Every legacy application is still readable.
    assert len(pg_client.get("/score/applications").json()) == 3


def test_a_legacy_open_alert_is_enriched_by_the_next_month(pg_client: TestClient) -> None:
    body = pg_client.post(
        "/ews/monitor",
        json={"borrower_id": 1, "month_number": 3, "installment_status": "Late 60-89",
              "days_late": 75, "bureau_balance": 1_000_000, "pos_cash_balance": 200_000},
    )
    assert body.status_code == 201, body.text
    alert = body.json()["alert"]
    assert alert["id"] == 1 and alert["severity"] == "CRITICAL"
    assert alert["reason_codes"] and alert["is_legacy"] is False
    assert len(pg_client.get("/ews/alerts", params={"open_only": True}).json()) == 2


def test_the_phase_three_workflow_on_postgres(pg_client: TestClient) -> None:
    scored = pg_client.post("/score", json=STRONG_APPLICANT).json()
    facility = scored["application_id"]
    decide(pg_client, facility)
    payload = {"borrower_id": facility, "installment_status": "On Time",
               "bureau_balance": 2_000_000, "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"]}
    for month, factor in ((1, 1.0), (2, 0.7), (3, 0.4)):
        response = pg_client.post(
            "/ews/observations",
            json={**payload, "month_number": month,
                  "pos_cash_balance": STRONG_APPLICANT["cash_flow_proxy"] * factor},
        )
        assert response.status_code == 201, response.text
    assert pg_client.post("/ews/monitor", json={**payload, "month_number": 3}).status_code == 409

    trend = pg_client.get(f"/ews/facilities/{facility}/trend").json()
    assert trend["direction"] == "Deteriorating" and len(trend["points"]) == 4
    alert = pg_client.get("/ews/alerts", params={"facility_id": facility}).json()[0]
    assert "RISK_TREND_DETERIORATING" in alert["reason_codes"]

    url = f"/ews/alerts/{alert['id']}"
    assert pg_client.post(f"{url}/acknowledge").status_code == 200
    due = (date.today() + timedelta(days=7)).isoformat()
    assert pg_client.post(f"{url}/assign", json={"assigned_to": "admin", "due_date": due}).status_code == 200
    assert pg_client.post(f"{url}/action-required", json={"action_note": "Call the owner."}).status_code == 200

    # Month 3's POS figure was wrong. Correcting it removes the deterioration,
    # and the alert that rested on month 3 closes itself, with a note.
    month3 = pg_client.get(f"/ews/facilities/{facility}/observations").json()[-1]
    corrected = pg_client.post(
        f"/ews/observations/{month3['id']}/correct",
        json={**{k: v for k, v in payload.items() if k != "borrower_id"},
              "correction_reason": "POS export had missed two settlement days."},
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["ews_state"] == "NORMAL"
    assert corrected.json()["trend"]["direction"] == "Stable"
    assert len(pg_client.get(f"/ews/facilities/{facility}/observations").json()) == 4
    final = pg_client.get(url).json()
    assert final["alert_status"] == "Resolved"
    assert "month 3 was corrected" in final["resolution_note"]
    assert [h["action"] for h in pg_client.get(f"{url}/history").json()] == [
        "ews.alert_created", "ews.alert_acknowledged", "ews.alert_assigned",
        "ews.alert_action_required", "ews.alert_auto_resolved",
    ]
    assert pg_client.post(f"{url}/resolve", json={"note": "Settlements recovered."}).status_code == 409


# --- a SQLite file from before 2.1 ---------------------------------------------------


def test_a_pre_2_1_sqlite_file_copies_with_legacy_markers(pg_engine, tmp_path: Path) -> None:
    _reset(pg_engine)
    _alembic("head")
    path = tmp_path / "foriflow.db"
    connection = sqlite3.connect(str(path))
    try:
        for table, columns in {**EXPECTED_0007, "borrowers": OPTIONAL["borrowers"]}.items():
            connection.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        connection.execute(
            "INSERT INTO applications (id, applicant_name, business_name, loan_amount_pkr, "
            "tenure_months, monthly_digital_payments, payment_history_score, inventory_turnover, "
            "order_consistency, existing_debt_pkr, cash_flow_proxy, years_in_operation, "
            "num_employees, risk_score, decision, created_at, decision_status, decision_source, "
            "borrower_id) VALUES (1, 'O', 'Shop', 1000000, 12, 1, 90, 5, 60, 0, 200000, 5, 6, 76.5, "
            "'Approved', '2026-09-01 10:00:00', 'Approved', 'legacy_auto', 1)"
        )
        connection.execute(
            "INSERT INTO borrowers (id, public_id, business_name, owner_name, status, created_at, "
            "updated_at) VALUES (1, 'BRW-000001', 'Shop', 'O', 'active', '2026-09-01', '2026-09-01')"
        )
        connection.execute(
            "INSERT INTO ews_tracking (id, borrower_id, month_number, installment_status, "
            "bureau_balance, pos_cash_balance, monthly_score, data_source_primary) "
            "VALUES (1, 1, 1, 'Late 60-89', 1, 1, 50.5, 'ECIB')"
        )
        connection.execute(
            "INSERT INTO alerts (id, borrower_id, baseline_score, current_score, score_drop, "
            "estimated_days_to_default, alert_status, triggered_at, assigned_to) "
            "VALUES (1, 1, 76.5, 50.5, 26, 45, 'In Review', '2026-09-20 10:00:00', 'idreesi')"
        )
        connection.commit()
    finally:
        connection.close()
    copied = migrate(path, POSTGRES_URL)
    assert copied["ews_tracking"] == 1 and copied["alerts"] == 1
    assert _rows(pg_engine, "SELECT score_source, record_status FROM ews_tracking") == [
        ("legacy_unknown", "active")
    ]
    assert _rows(pg_engine, "SELECT alert_status, acknowledged_by FROM alerts") == [
        ("Acknowledged", "idreesi")
    ]
