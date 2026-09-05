"""Config helpers: URL assembly and docs flag."""

from __future__ import annotations

import os

from config import database_url, env_flag, is_sqlite_url


def test_sqlite_default_when_no_postgres_parts(monkeypatch) -> None:
    monkeypatch.delenv("FORIFLOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_HOST", raising=False)
    assert is_sqlite_url(database_url())
    assert database_url() == "sqlite:///./foriflow.db"


def test_explicit_url_wins(monkeypatch) -> None:
    monkeypatch.setenv("FORIFLOW_DATABASE_URL", "postgresql+psycopg2://u:p@db:5432/foriflow")
    monkeypatch.setenv("POSTGRES_HOST", "ignored")
    assert database_url().startswith("postgresql+psycopg2://")


def test_postgres_parts_build_url(monkeypatch) -> None:
    monkeypatch.delenv("FORIFLOW_DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "foriflow")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:word")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "foriflow")
    url = database_url()
    assert url.startswith("postgresql+psycopg2://foriflow:")
    assert "@db:5432/foriflow" in url
    assert "p%40ss%3Aword" in url


def test_env_flag_defaults() -> None:
    assert env_flag("FORIFLOW_ENABLE_DOCS", "true") is True
    os.environ.pop("FORIFLOW_ENABLE_DOCS_TEST", None)
    assert env_flag("FORIFLOW_ENABLE_DOCS_TEST", "false") is False
