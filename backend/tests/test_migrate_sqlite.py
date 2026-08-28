"""SQLite -> Postgres copy script refuses mismatched schemas."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from models.database import Base
from scripts.migrate_sqlite_to_postgres import MigrationError, assert_schema


def test_assert_schema_accepts_sqlalchemy_sqlite(tmp_path: Path) -> None:
    path = tmp_path / "foriflow.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    Base.metadata.create_all(bind=engine)
    engine.dispose()

    connection = sqlite3.connect(str(path))
    try:
        assert_schema(connection)
    finally:
        connection.close()


def test_assert_schema_rejects_extra_column(tmp_path: Path) -> None:
    path = tmp_path / "foriflow.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    Base.metadata.create_all(bind=engine)
    engine.dispose()

    connection = sqlite3.connect(str(path))
    connection.execute("ALTER TABLE applications ADD COLUMN unexpected TEXT")
    connection.commit()
    try:
        with pytest.raises(MigrationError, match="columns"):
            assert_schema(connection)
    finally:
        connection.close()
