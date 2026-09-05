"""Scoring payload parity between in-memory SQLite and PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (Step 1 validation).

Uses the shared ``client`` TestClient for both backends, swapping ``get_db``
only for the Postgres half. Two simultaneous TestClient fixtures would share
``app.dependency_overrides`` and silently send both posts to one database.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from main import app
from models.database import get_db
from tests.conftest import MID_APPLICANT, STRONG_APPLICANT, WEAK_APPLICANT, seed_test_admin

pytestmark = pytest.mark.postgres

POSTGRES_URL = os.getenv("FORIFLOW_TEST_POSTGRES_URL", "").strip()


def _score_fields(body: dict) -> dict:
    explanation = body.get("explanation") or {}
    contributions = [
        {
            "feature": item["feature"],
            "contribution": round(float(item["contribution"]), 6),
        }
        for item in explanation.get("feature_contributions", [])
    ]
    return {
        "risk_score": round(float(body["risk_score"]), 6),
        "decision": body["decision"],
        "risk_band": body["risk_band"],
        "confidence": body.get("confidence"),
        "model_version": body.get("model_version"),
        "monthly_installment_pkr": body["monthly_installment_pkr"],
        "contributions": contributions,
        "base_value": explanation.get("base_value"),
    }


@pytest.fixture(name="postgres_session_factory", scope="module")
def postgres_session_factory_fixture() -> Generator[sessionmaker[Session], None, None]:
    if not POSTGRES_URL:
        pytest.skip("FORIFLOW_TEST_POSTGRES_URL is not set")

    from alembic import command
    from alembic.config import Config

    engine = create_engine(POSTGRES_URL, future=True, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS ews_tracking CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS alerts CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS applications CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS users CASCADE"))

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", POSTGRES_URL.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    bootstrap = factory()
    try:
        seed_test_admin(bootstrap)
    finally:
        bootstrap.close()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.mark.parametrize("payload", [STRONG_APPLICANT, MID_APPLICANT, WEAK_APPLICANT])
def test_postgres_score_matches_sqlite(
    client: TestClient,
    postgres_session_factory: sessionmaker[Session],
    payload: dict,
) -> None:
    sqlite_response = client.post("/score", json=payload)
    assert sqlite_response.status_code == 201, sqlite_response.text
    sqlite_fields = _score_fields(sqlite_response.json())

    def override_postgres_db() -> Generator[Session, None, None]:
        db = postgres_session_factory()
        try:
            yield db
        finally:
            db.close()

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = override_postgres_db
    try:
        postgres_response = client.post("/score", json=payload)
        assert postgres_response.status_code == 201, postgres_response.text
        assert sqlite_fields == _score_fields(postgres_response.json())

        application_id = postgres_response.json()["application_id"]
        stored = client.get(f"/score/applications/{application_id}")
        assert stored.status_code == 200
        assert stored.json()["risk_score"] == postgres_response.json()["risk_score"]
    finally:
        app.dependency_overrides[get_db] = previous


def test_ews_tracking_has_no_borrower_month_unique(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Step 1 schema must match SQLite: no extra unique constraint."""
    db = postgres_session_factory()
    try:
        rows = db.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'ews_tracking'::regclass AND contype = 'u'"
            )
        ).fetchall()
    finally:
        db.close()
    assert rows == []
