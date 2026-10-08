"""Migration 0009 (model provenance) on real PostgreSQL.

Skipped unless ``FORIFLOW_TEST_POSTGRES_URL`` is set (CI sets it).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text

from tests.test_postgres_phase1 import POSTGRES_URL, _alembic, _reset

pytestmark = pytest.mark.postgres

LEGACY_METRICS = {"cv_auc_roc_mean": 0.7752, "holdout_auc_roc": 0.7731, "training_rows": 32581}


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
    """A 2.1 database with the 2.1 model registered, upgraded to head."""
    _reset(pg_engine)
    _alembic("0008_ews_history_alerts")
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO model_versions (version, engine, artifact_sha256, training_dataset, "
                "feature_set, feature_set_version, trained_at, metrics, status, registered_at) "
                "VALUES ('ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26', 'ml', :sha, "
                "'credit_risk_shared', CAST(:features AS JSONB), 'abc123def456', "
                "'2026-09-25T10:38:26', CAST(:metrics AS JSONB), 'active', now())"
            ),
            {
                "sha": "a" * 64,
                "features": json.dumps(["loan_to_income", "payment_history_score", "years_in_operation"]),
                "metrics": json.dumps(LEGACY_METRICS),
            },
        )
    _alembic("head")
    return pg_engine


def _rows(engine, sql: str) -> list[tuple]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql)).all()]


def test_existing_model_versions_are_kept_without_invented_provenance(migrated) -> None:
    rows = _rows(
        migrated,
        "SELECT version, artifact_sha256, trained_at, metrics, status, provenance FROM model_versions",
    )
    assert rows == [
        (
            "ensemble-xgb-rf-credit_risk_shared-2026-09-25T10:38:26",
            "a" * 64,
            "2026-09-25T10:38:26",
            LEGACY_METRICS,
            "active",
            None,
        )
    ]
    (details,) = _rows(
        migrated,
        "SELECT details FROM audit_logs WHERE action = 'migration.applied' "
        "AND entity_id = '0009_model_provenance'",
    )[0]
    assert details["model_versions_left_without_provenance"] == 1


def test_provenance_is_stored_and_the_downgrade_round_trips(migrated) -> None:
    with migrated.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO model_versions (version, engine, artifact_sha256, metrics, provenance, "
                "status, registered_at) VALUES ('ensemble-xgb-rf-credit_risk_shared-2026-10-08T12:00:00', "
                "'ml', :sha, CAST(:metrics AS JSONB), CAST(:prov AS JSONB), 'retired', now())"
            ),
            {
                "sha": "b" * 64,
                "metrics": json.dumps({"final_test_auc_roc": 0.77}),
                "prov": json.dumps({"dataset_sha256": "c" * 64, "random_seed": 42}),
            },
        )
    assert _rows(migrated, "SELECT provenance->>'random_seed' FROM model_versions WHERE artifact_sha256 = '" + "b" * 64 + "'") == [("42",)]
    _alembic("0008_ews_history_alerts", down=True)
    assert _rows(migrated, "SELECT COUNT(*) FROM model_versions") == [(2,)]
    _alembic("head")
    assert _rows(migrated, "SELECT COUNT(*) FROM model_versions WHERE provenance IS NULL") == [(2,)]


def test_the_schema_matches_the_models(migrated) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from models.database import Base

    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_the_served_model_registers_on_postgres(migrated, ml_service, monkeypatch) -> None:
    """The real 2.2 artefacts register on JSONB (2.2.0 failed here on NaN).

    The NaN is put back into the metadata, as 2.2.0 shipped it, so the
    registry's own guard is what is tested, not only the corrected file.
    """
    from sqlalchemy.orm import Session

    from services import model_registry

    xgb_config = dict(ml_service.metadata["model_config"]["xgboost"], missing=float("nan"))
    monkeypatch.setitem(
        ml_service.metadata,
        "model_config",
        dict(ml_service.metadata["model_config"], xgboost=xgb_config),
    )

    with Session(migrated) as session:
        row = model_registry.ensure_registered(session, ml_service)
        session.commit()
        new_id = row.id
    rows = _rows(
        migrated,
        "SELECT id, status, provenance IS NOT NULL, "
        "provenance->'model_config'->'xgboost'->>'missing' FROM model_versions ORDER BY id",
    )
    assert rows[0][1:3] == ("retired", False)
    assert rows[-1] == (new_id, "active", True, "NaN")
    assert _rows(
        migrated,
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'model.registered' "
        f"AND entity_id = '{new_id}'",
    ) == [(1,)]
