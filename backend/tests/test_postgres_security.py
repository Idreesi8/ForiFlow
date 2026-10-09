"""Migration 0010 (security hardening) and the 2.3 controls on real PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (CI sets it).
"""

from __future__ import annotations

import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from main import app
from models.database import get_db
from services.auth_service import hash_password
from tests.conftest import STRONG_APPLICANT, TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME, seed_test_admin
from tests.test_postgres_phase1 import POSTGRES_URL, _alembic, _reset

pytestmark = pytest.mark.postgres


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
def migrated_fixture(pg_engine):
    """A 2.2 database with two officer accounts, upgraded to head."""
    _reset(pg_engine)
    _alembic("0009_model_provenance")
    with pg_engine.begin() as connection:
        for name, role in (("legacy_admin", "admin"), ("legacy_analyst", "analyst")):
            connection.execute(
                text(
                    "INSERT INTO users (username, hashed_password, role, created_at) "
                    "VALUES (:name, :hash, :role, now())"
                ),
                {"name": name, "hash": hash_password("orchard-pebble-signal-3"), "role": role},
            )
    _alembic("head")
    return pg_engine


def _rows(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql)).all()]


def test_existing_accounts_stay_enabled_and_the_migration_is_audited(migrated) -> None:
    assert _rows(migrated, "SELECT username, is_active FROM users ORDER BY id") == [
        ("legacy_admin", True),
        ("legacy_analyst", True),
    ]
    details = _rows(
        migrated,
        "SELECT details FROM audit_logs WHERE action = 'migration.applied' "
        "AND entity_id = '0010_security_hardening'",
    )
    assert details[0][0]["accounts_left_enabled"] == 2
    assert _rows(migrated, "SELECT COUNT(*) FROM login_attempts") == [(0,)]
    assert _rows(migrated, "SELECT COUNT(*) FROM revoked_tokens") == [(0,)]


def test_the_downgrade_round_trips_without_losing_accounts(migrated) -> None:
    _alembic("0009_model_provenance", down=True)
    assert _rows(migrated, "SELECT COUNT(*) FROM users") == [(2,)]
    _alembic("head")
    assert _rows(migrated, "SELECT COUNT(*) FROM users WHERE is_active") == [(2,)]


def test_the_schema_matches_the_models(migrated) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from models.database import Base

    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_logs SET username = 'someone-else'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ],
)
def test_the_database_refuses_to_change_the_audit_trail(migrated, statement: str) -> None:
    before = _rows(migrated, "SELECT COUNT(*), MAX(id) FROM audit_logs")
    with pytest.raises(DBAPIError, match="append-only"):
        with migrated.begin() as connection:
            connection.execute(text(statement))
    assert _rows(migrated, "SELECT COUNT(*), MAX(id) FROM audit_logs") == before


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


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/auth/login", json={"username": username, "password": password}, headers={"Authorization": ""}
    )


def test_lockout_logout_and_disable_work_on_postgres(pg_client: TestClient, migrated) -> None:
    for _ in range(5):
        assert _login(pg_client, "legacy_analyst", "wrong-password-xyz").status_code == 401
    assert _login(pg_client, "legacy_analyst", "orchard-pebble-signal-3").status_code == 429
    assert _rows(migrated, "SELECT failed_count, locked_until > now() FROM login_attempts") == [(5, True)]

    token = _login(pg_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).json()["access_token"]
    mine = {"Authorization": f"Bearer {token}"}
    assert pg_client.post("/score", json=STRONG_APPLICANT, headers=mine).status_code == 201
    assert pg_client.post("/auth/logout", headers=mine).status_code == 204
    assert pg_client.get("/auth/me", headers=mine).status_code == 401
    assert _rows(migrated, "SELECT COUNT(*) FROM revoked_tokens") == [(1,)]

    analyst_id = _rows(migrated, "SELECT id FROM users WHERE username = 'legacy_analyst'")[0][0]
    response = pg_client.patch(f"/auth/users/{analyst_id}/status", json={"is_active": False})
    assert response.status_code == 200
    assert _rows(migrated, f"SELECT is_active FROM users WHERE id = {analyst_id}") == [(False,)]
    events = [
        row[0]
        for row in _rows(
            migrated,
            "SELECT action FROM audit_logs WHERE action LIKE 'auth.%' OR action LIKE 'user.%' ORDER BY id",
        )
    ]
    assert "auth.login_locked" in events and "auth.logout" in events and "user.disabled" in events
    stored = json.dumps(_rows(migrated, "SELECT details, new_state FROM audit_logs"), default=str)
    assert token not in stored and TEST_ADMIN_PASSWORD not in stored
