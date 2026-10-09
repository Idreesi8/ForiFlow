"""Migration 0006 and the Phase 1 tables on real PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (CI sets it).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from main import app
from models.database import Base, get_db
from scripts.migrate_sqlite_to_postgres import EXPECTED_0005, MigrationError, migrate
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, seed_test_admin

pytestmark = pytest.mark.postgres

POSTGRES_URL = os.getenv("FORIFLOW_TEST_POSTGRES_URL", "").strip()
ENSEMBLE = "ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26"
TABLES = (
    "alembic_version",
    # 0010 security state.
    "login_attempts",
    "revoked_tokens",
    "ews_tracking",
    "alerts",
    "applications",
    "borrowers",
    "model_versions",
    "credit_policies",
    "audit_logs",
    "users",
)

# Three applications as release 1.9 stored them: no borrower, the model version
# only inside the explanation JSON (or nowhere).
LEGACY = [
    (1, "Ayesha Siddiqui", "Siddiqui Textiles", "Retail", "+923001234567", 12.0, 75.9,
     "Approved", json.dumps({"model_version": ENSEMBLE})),
    (2, "Ali Khan", "Khan Traders", None, None, 5.0, 56.7,
     "Manual Review", json.dumps({"model_version": "surrogate-linear-v1"})),
    # Same business name as application 1, on purpose.
    (3, "Someone Else", "Siddiqui Textiles", None, None, 2.0, 30.1, "Rejected", None),
]


def _alembic(revision: str, *, down: bool = False) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", POSTGRES_URL.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    (command.downgrade if down else command.upgrade)(cfg, revision)


def _reset(engine) -> None:
    with engine.begin() as connection:
        for table in TABLES:
            connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))


def _insert_legacy(connection) -> None:
    for app_id, owner, business, sector, phone, years, score, decision, explanation in LEGACY:
        connection.execute(
            text(
                "INSERT INTO applications (id, applicant_name, business_name, loan_amount_pkr, "
                "tenure_months, monthly_digital_payments, payment_history_score, "
                "inventory_turnover, order_consistency, existing_debt_pkr, cash_flow_proxy, "
                "years_in_operation, num_employees, risk_score, decision, "
                "shap_explanation_json, business_sector, contact_phone, created_at) VALUES "
                "(:id, :owner, :business, 500000, 12, 150000, 95, 5, 60, 0, 150000, :years, 6, "
                ":score, :decision, :explanation, :sector, :phone, "
                "TIMESTAMPTZ '2026-09-01 10:00:00+00' + (:id || ' days')::interval)"
            ),
            {
                "id": app_id, "owner": owner, "business": business, "sector": sector,
                "phone": phone, "years": years, "score": score, "decision": decision,
                "explanation": explanation,
            },
        )
    connection.execute(
        text(
            "INSERT INTO ews_tracking (borrower_id, month_number, installment_status, "
            "bureau_balance, pos_cash_balance, monthly_score, data_source_primary) "
            "VALUES (1, 1, 'Late 60-89', 1, 1, 40.0, 'ECIB')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO alerts (borrower_id, baseline_score, current_score, score_drop, "
            "estimated_days_to_default, alert_status, triggered_at) "
            "VALUES (1, 75.9, 40.0, 35.9, 54, 'Active', now())"
        )
    )


@pytest.fixture(name="pg_engine", scope="module")
def pg_engine_fixture():
    if not POSTGRES_URL:
        pytest.skip("FORIFLOW_TEST_POSTGRES_URL is not set")
    engine = create_engine(POSTGRES_URL, future=True, pool_pre_ping=True)
    yield engine
    # Leave a clean head schema for whichever module runs next.
    _reset(engine)
    _alembic("head")
    engine.dispose()


@pytest.fixture(name="migrated")
def migrated_fixture(pg_engine):
    """A 1.9 database holding three legacy applications, upgraded to head."""
    _reset(pg_engine)
    _alembic("0005_roles_and_evidence")
    with pg_engine.begin() as connection:
        _insert_legacy(connection)
    _alembic("head")
    return pg_engine


# --- the backfill -------------------------------------------------------------------


def test_every_legacy_application_gets_its_own_borrower(migrated) -> None:
    with migrated.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT a.id, a.borrower_id, b.public_id, b.business_name, b.owner_name, "
                "b.contact_phone, b.business_sector, b.years_in_operation, b.status, "
                "b.identifier, b.created_at = a.created_at AS same_date "
                "FROM applications a JOIN borrowers b ON b.id = a.borrower_id ORDER BY a.id"
            )
        ).mappings().all()
        borrowers = connection.execute(text("SELECT COUNT(*) FROM borrowers")).scalar_one()

    assert borrowers == 3 and len(rows) == 3
    # In application-id order, and never merged although 1 and 3 share a name.
    assert [row["borrower_id"] for row in rows] == [1, 2, 3]
    assert [row["public_id"] for row in rows] == ["BRW-000001", "BRW-000002", "BRW-000003"]
    assert rows[0]["business_name"] == rows[2]["business_name"] == "Siddiqui Textiles"
    assert rows[0]["owner_name"] == "Ayesha Siddiqui" and rows[2]["owner_name"] == "Someone Else"
    assert rows[0]["contact_phone"] == "+923001234567" and rows[0]["business_sector"] == "Retail"
    assert rows[1]["years_in_operation"] == 5.0
    assert all(row["status"] == "active" and row["identifier"] is None for row in rows)
    assert all(row["same_date"] for row in rows)


def test_the_stored_model_version_is_preserved_not_guessed(migrated) -> None:
    with migrated.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT model_version, scoring_engine, model_version_id, risk_score, decision "
                "FROM applications ORDER BY id"
            )
        ).all()

    assert [(r.model_version, r.scoring_engine) for r in rows] == [
        (ENSEMBLE, "ml"),
        ("surrogate-linear-v1", "surrogate"),
        (None, None),  # nothing stored, so nothing is claimed
    ]
    assert all(r.model_version_id is None for r in rows)
    # What was already there is untouched.
    assert [(r.risk_score, r.decision) for r in rows] == [
        (75.9, "Approved"),
        (56.7, "Manual Review"),
        (30.1, "Rejected"),
    ]


def test_monitoring_and_alerts_survive_the_upgrade(migrated) -> None:
    with migrated.connect() as connection:
        month = connection.execute(text("SELECT borrower_id, monthly_score FROM ews_tracking")).one()
        alert = connection.execute(text("SELECT borrower_id, score_drop FROM alerts")).one()
    assert tuple(month) == (1, 40.0) and tuple(alert) == (1, 35.9)


def test_the_migration_writes_one_audit_entry(migrated) -> None:
    with migrated.connect() as connection:
        entries = connection.execute(
            text(
                "SELECT username, action, entity_type, entity_id, details FROM audit_logs "
                "WHERE entity_id = '0006_borrowers_audit_models'"
            )
        ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.username, entry.action, entry.entity_type) == (
        "system",
        "migration.applied",
        "migration",
    )
    assert entry.entity_id == "0006_borrowers_audit_models"
    assert entry.details["applications_backfilled"] == 3  # JSONB comes back as a dict
    assert entry.details["model_versions_copied_from_stored_explanations"] == {
        ENSEMBLE: 1,
        "surrogate-linear-v1": 1,
        "unrecorded": 1,
    }


def test_the_schema_matches_the_models(migrated) -> None:
    """Alembic sees nothing left to change between the models and the database."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


def test_constraints_indexes_and_foreign_keys(migrated) -> None:
    inspector = inspect(migrated)
    columns = {column["name"]: column for column in inspector.get_columns("applications")}
    assert columns["borrower_id"]["nullable"] is False
    assert columns["model_version"]["nullable"] is True

    foreign = {
        (fk["constrained_columns"][0], fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspector.get_foreign_keys("applications")
    }
    assert foreign == {
        ("borrower_id", "borrowers", "RESTRICT"),
        ("model_version_id", "model_versions", "RESTRICT"),
        # Added by migration 0007.
        ("policy_id", "credit_policies", "RESTRICT"),
        ("supersedes_application_id", "applications", "RESTRICT"),
        ("superseded_by_application_id", "applications", "RESTRICT"),
    }

    audit_indexes = {
        tuple(index["column_names"]) for index in inspector.get_indexes("audit_logs")
    }
    assert audit_indexes >= {
        ("occurred_at",),
        ("user_id",),
        ("action",),
        ("entity_type", "entity_id"),
    }
    assert str(inspector.get_columns("audit_logs")[8]["type"]) == "JSONB"

    with migrated.begin() as connection:
        with pytest.raises(IntegrityError, match="fk_applications_borrower_id"):
            connection.execute(text("DELETE FROM borrowers WHERE id = 1"))


def test_identifier_is_unique_but_many_may_be_empty(migrated) -> None:
    insert = text(
        "INSERT INTO borrowers (business_name, owner_name, identifier_type, identifier, "
        "status, created_at, updated_at) VALUES ('x', 'y', :kind, :value, 'active', now(), now())"
    )
    with migrated.begin() as connection:
        connection.execute(insert, {"kind": None, "value": None})
        connection.execute(insert, {"kind": None, "value": None})
        connection.execute(insert, {"kind": "NTN", "value": "1234567"})
    for kind, value, message in (
        ("NTN", "1234567", "borrowers_identifier_key"),  # taken
        (None, "7654321", "ck_borrowers_identifier"),  # a value without its type
        ("PASSPORT", "7654321", "ck_borrowers_identifier"),
    ):
        with pytest.raises(IntegrityError, match=message):
            with migrated.begin() as connection:
                connection.execute(insert, {"kind": kind, "value": value})


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET username = 'someone-else'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ],
)
def test_postgres_refuses_to_change_the_audit_trail(migrated, statement: str) -> None:
    snapshot = text("SELECT id, username, action FROM audit_logs ORDER BY id")
    with migrated.connect() as connection:
        before = connection.execute(snapshot).all()
    assert before and all(row.username == "system" for row in before)

    with pytest.raises(DBAPIError, match="append-only"):
        with migrated.begin() as connection:
            connection.execute(text(statement))
    with migrated.connect() as connection:
        assert connection.execute(snapshot).all() == before


def test_downgrade_and_upgrade_again_keep_the_applications(migrated) -> None:
    _alembic("0005_roles_and_evidence", down=True)
    inspector = inspect(migrated)
    assert "borrowers" not in inspector.get_table_names()
    assert "audit_logs" not in inspector.get_table_names()
    assert "borrower_id" not in {c["name"] for c in inspector.get_columns("applications")}
    with migrated.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM applications")).scalar_one() == 3

    _alembic("head")
    with migrated.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM borrowers")).scalar_one() == 3
        assert connection.execute(
            text("SELECT COUNT(*) FROM applications WHERE model_version IS NOT NULL")
        ).scalar_one() == 2


# --- the workflow on PostgreSQL -----------------------------------------------------


@pytest.fixture(name="pg_client")
def pg_client_fixture(migrated, client: TestClient) -> Generator[TestClient, None, None]:
    """The API on the upgraded PostgreSQL database, legacy rows included."""
    factory = sessionmaker(bind=migrated, autoflush=False, expire_on_commit=False)
    with migrated.begin() as connection:
        for table in ("applications", "alerts", "ews_tracking"):
            connection.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"(SELECT MAX(id) FROM {table}))"
                )
            )
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


def test_legacy_applications_still_read_and_explain(pg_client: TestClient) -> None:
    listed = pg_client.get("/score/applications").json()
    assert [row["id"] for row in listed] == [3, 2, 1]
    assert listed[2]["borrower_public_id"] == "BRW-000001"
    assert listed[2]["model_version"] == ENSEMBLE and listed[2]["scoring_engine"] == "ml"
    assert listed[0]["model_version"] is None

    history = pg_client.get("/borrowers/BRW-000001/history").json()
    assert history["summary"]["applications"] == 1
    assert history["summary"]["open_alerts"] == 1
    assert history["applications"][0]["monitoring"][0]["monthly_score"] == 40.0
    assert pg_client.get("/borrowers/BRW-000003/history").json()["summary"][
        "model_versions_used"
    ] == ["unrecorded"]
    assert pg_client.get("/portfolio/summary").status_code == 200
    assert pg_client.get("/score/stats").json()["total_applications"] == 3


def test_the_main_workflow_on_postgres(pg_client: TestClient) -> None:
    """Score, link, version, explain, audit, retrieve, history."""
    first = pg_client.post(
        "/score",
        json={**MID_APPLICANT, "borrower_identifier_type": "NTN", "borrower_identifier": "7654321"},
    )
    assert first.status_code == 201, first.text
    first = first.json()
    second = pg_client.post(
        "/score", json={**STRONG_APPLICANT, "borrower_public_id": first["borrower_public_id"]}
    ).json()

    assert first["borrower_created"] is True and second["borrower_created"] is False
    assert second["borrower_id"] == first["borrower_id"]
    assert first["model_version"] == "surrogate-linear-v1"
    assert first["explanation"]["feature_contributions"]

    stored = pg_client.get(f"/score/applications/{first['application_id']}").json()
    assert stored["model_version"] == "surrogate-linear-v1"
    assert stored["scoring_engine"] == "surrogate"
    assert pg_client.get(f"/explain/{first['application_id']}").status_code == 200

    reviewed = pg_client.post(
        f"/score/applications/{first['application_id']}/review",
        json={"decision": "Approved", "note": "Statement supports the turnover."},
    )
    assert reviewed.status_code == 200
    month = pg_client.post(
        "/ews/monitor",
        json={
            "borrower_id": first["application_id"],
            "month_number": 1,
            "installment_status": "Default",
            "bureau_balance": 1,
            "pos_cash_balance": 1,
        },
    )
    assert month.status_code == 201 and month.json()["alert"] is not None

    history = pg_client.get(f"/borrowers/{first['borrower_public_id']}/history").json()
    assert [row["application_id"] for row in history["applications"]] == [
        first["application_id"],
        second["application_id"],
    ]
    assert history["summary"]["open_alerts"] == 1
    assert history["borrower"]["identifier_masked"] == "***4321"

    trail = pg_client.get(
        "/audit/logs",
        params={"entity_type": "application", "entity_id": str(first["application_id"])},
    ).json()
    assert [row["action"] for row in reversed(trail)] == [
        "application.created",
        "application.scored",
        "recommendation.generated",
        "explanation.generated",
        "application.officer_decision",
    ]
    assert trail[-1]["new_state"]["borrower_public_id"] == first["borrower_public_id"]
    assert "7654321" not in pg_client.get("/audit/logs").text

    active = pg_client.get("/model/versions/active").json()
    assert active["version"] == "surrogate-linear-v1" and active["applications_scored"] == 2


# --- the SQLite copy script ---------------------------------------------------------

_AFFINITY = {
    "id": "INTEGER", "borrower_id": "INTEGER", "tenure_months": "INTEGER",
    "num_employees": "INTEGER", "month_number": "INTEGER",
    "estimated_days_to_default": "INTEGER", "created_at": "DATETIME",
    "reviewed_at": "DATETIME", "triggered_at": "DATETIME", "resolved_at": "DATETIME",
}
_TEXT = {
    "applicant_name", "business_name", "decision", "shap_explanation_json", "scored_by",
    "review_decision", "review_note", "reviewed_by", "business_sector",
    "turnover_evidence_json", "contact_phone", "alert_status", "assigned_to", "resolved_by",
    "resolution_note", "installment_status", "data_source_primary",
}


def _legacy_sqlite(path: Path) -> None:
    """A SQLite file with the 1.9 (migration 0005) column layout and two applications."""
    connection = sqlite3.connect(str(path))
    for table, columns in EXPECTED_0005.items():
        ddl = ", ".join(
            f"{name} {_AFFINITY.get(name, 'TEXT' if name in _TEXT else 'REAL')}"
            for name in columns
        )
        connection.execute(f"CREATE TABLE {table} ({ddl})")
    for app_id, owner, business, sector, phone, years, score, decision, explanation in LEGACY[:2]:
        connection.execute(
            "INSERT INTO applications (id, applicant_name, business_name, loan_amount_pkr, "
            "tenure_months, monthly_digital_payments, payment_history_score, inventory_turnover, "
            "order_consistency, existing_debt_pkr, cash_flow_proxy, years_in_operation, "
            "num_employees, risk_score, decision, shap_explanation_json, business_sector, "
            "contact_phone, created_at) VALUES (?,?,?,500000,12,150000,95,5,60,0,150000,?,6,?,?,?,?,?,?)",
            (app_id + 40, owner, business, years, score, decision, explanation, sector, phone,
             "2026-09-01 10:00:00"),
        )
    connection.execute(
        "INSERT INTO ews_tracking (id, borrower_id, month_number, installment_status, "
        "bureau_balance, pos_cash_balance, monthly_score, data_source_primary) "
        "VALUES (1, 41, 1, 'On Time', 1, 1, 75.9, 'ECIB')"
    )
    connection.commit()
    connection.close()


def test_copying_a_legacy_sqlite_file_opens_a_borrower_per_application(
    pg_engine, tmp_path: Path
) -> None:
    _reset(pg_engine)
    _alembic("head")
    source = tmp_path / "legacy.db"
    _legacy_sqlite(source)

    copied = migrate(source, POSTGRES_URL)
    assert copied["applications"] == 2 and copied["borrowers"] == 2

    with pg_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT a.id, b.public_id, b.owner_name, a.model_version, a.scoring_engine "
                "FROM applications a JOIN borrowers b ON b.id = a.borrower_id ORDER BY a.id"
            )
        ).all()
        month = connection.execute(text("SELECT borrower_id FROM ews_tracking")).scalar_one()
    assert [tuple(row) for row in rows] == [
        (41, "BRW-000001", "Ayesha Siddiqui", ENSEMBLE, "ml"),
        (42, "BRW-000002", "Ali Khan", "surrogate-linear-v1", "surrogate"),
    ]
    assert month == 41  # ids are preserved, so the facility link still holds

    with pytest.raises(MigrationError, match="already has"):
        migrate(source, POSTGRES_URL)


def test_copying_a_current_sqlite_file_keeps_borrowers_models_and_audit(
    pg_engine, tmp_path: Path, client: TestClient, db_session_factory
) -> None:
    """Score on SQLite with today's schema, copy it, and find the same records."""
    first = client.post(
        "/score",
        json={**STRONG_APPLICANT, "borrower_identifier_type": "NTN", "borrower_identifier": "7654321"},
    ).json()
    client.post("/score", json={**MID_APPLICANT, "borrower_public_id": first["borrower_public_id"]})

    source = tmp_path / "current.db"
    session = db_session_factory()
    try:
        raw = session.connection().connection.driver_connection
        target = sqlite3.connect(str(source))
        raw.backup(target)
        target.close()
    finally:
        session.close()

    _reset(pg_engine)
    _alembic("head")
    copied = migrate(source, POSTGRES_URL)
    assert copied["borrowers"] == 1 and copied["applications"] == 2
    assert copied["model_versions"] == 1 and copied["audit_logs"] >= 7

    with pg_engine.connect() as connection:
        links = connection.execute(
            text("SELECT borrower_id, model_version, model_version_id FROM applications ORDER BY id")
        ).all()
        borrower = connection.execute(
            text("SELECT public_id, identifier_type, identifier FROM borrowers")
        ).one()
        scored = connection.execute(
            text(
                "SELECT details FROM audit_logs WHERE action = 'application.scored' ORDER BY id"
            )
        ).scalars().all()
        model = connection.execute(text("SELECT feature_set, metrics FROM model_versions")).one()
    assert [tuple(row) for row in links] == [
        (first["borrower_id"], "surrogate-linear-v1", 1),
        (first["borrower_id"], "surrogate-linear-v1", 1),
    ]
    assert tuple(borrower) == (first["borrower_public_id"], "NTN", "7654321")
    assert [entry["scoring_engine"] for entry in scored] == ["surrogate", "surrogate"]
    assert isinstance(model.feature_set, list) and model.metrics is None
