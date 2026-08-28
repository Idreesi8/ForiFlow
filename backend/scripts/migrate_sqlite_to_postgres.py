"""Copy existing SQLite rows into PostgreSQL without changing IDs or FKs.

Run from ``backend/`` after Postgres is up and Alembic has created the schema::

    python -m scripts.migrate_sqlite_to_postgres --sqlite ./foriflow.db

Docker (legacy volume still mounted at /data)::

    python -m scripts.migrate_sqlite_to_postgres --sqlite /data/foriflow.db

Aborts if the SQLite schema does not match the expected column set, if a
type cannot be copied without coercion, or if Postgres already has rows.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from config import database_url, is_sqlite_url

# Column order matches models.database. Types are SQLite affinities we accept.
EXPECTED: dict[str, tuple[str, ...]] = {
    "applications": (
        "id",
        "applicant_name",
        "business_name",
        "loan_amount_pkr",
        "tenure_months",
        "monthly_digital_payments",
        "payment_history_score",
        "inventory_turnover",
        "order_consistency",
        "existing_debt_pkr",
        "cash_flow_proxy",
        "years_in_operation",
        "num_employees",
        "risk_score",
        "decision",
        "shap_explanation_json",
        "created_at",
    ),
    "alerts": (
        "id",
        "borrower_id",
        "baseline_score",
        "current_score",
        "score_drop",
        "estimated_days_to_default",
        "alert_status",
        "triggered_at",
        "resolved_at",
    ),
    "ews_tracking": (
        "id",
        "borrower_id",
        "month_number",
        "installment_status",
        "bureau_balance",
        "pos_cash_balance",
        "monthly_score",
        "data_source_primary",
    ),
}

# SQLite declared types we will copy without rewriting values.
_INT = {"INT", "INTEGER", "BIGINT"}
_FLOAT = {"REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION", "NUMERIC", "DECIMAL"}
_TEXT = {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "CLOB", "STRING"}
_TIME = {"DATETIME", "TIMESTAMP", "DATE"}
_COMPATIBLE = _INT | _FLOAT | _TEXT | _TIME

TABLE_ORDER = ("applications", "alerts", "ews_tracking")

# Present on SQLite after Step 2 create_all; absent on a pre-auth file.
OPTIONAL: dict[str, tuple[str, ...]] = {
    "users": (
        "id",
        "username",
        "hashed_password",
        "role",
        "created_at",
    ),
}


class MigrationError(RuntimeError):
    """Raised when the SQLite file cannot be copied safely."""


def _affinity(declared: str) -> str:
    upper = (declared or "").upper()
    for prefix in ("VARCHAR", "NVARCHAR", "CHAR"):
        if upper.startswith(prefix):
            return "VARCHAR"
    return upper.split("(")[0].strip() or "TEXT"


def sqlite_columns(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise MigrationError(f"SQLite table {table!r} is missing.")
    return [(str(row[1]), _affinity(str(row[2]))) for row in rows]


def assert_schema(connection: sqlite3.Connection) -> None:
    """Stop if column names differ or a type is not in the allowed set."""
    existing_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    extra = existing_tables - set(EXPECTED) - set(OPTIONAL) - {"alembic_version"}
    if extra:
        raise MigrationError(
            f"SQLite has unexpected tables {sorted(extra)}. Refusing to copy."
        )
    missing = set(EXPECTED) - existing_tables
    if missing:
        raise MigrationError(
            f"SQLite is missing tables {sorted(missing)}. Refusing to copy."
        )

    tables_to_check = dict(EXPECTED)
    for name, columns in OPTIONAL.items():
        if name in existing_tables:
            tables_to_check[name] = columns

    for table, expected in tables_to_check.items():
        cols = sqlite_columns(connection, table)
        names = tuple(name for name, _type in cols)
        if names != expected:
            raise MigrationError(
                f"Table {table!r} columns {names} do not match expected {expected}."
            )
        for name, declared in cols:
            if declared not in _COMPATIBLE and not declared.startswith("VARCHAR"):
                raise MigrationError(
                    f"Table {table!r} column {name!r} has type {declared!r} "
                    "which this script will not coerce."
                )


def migrate(sqlite_path: Path, postgres_url: str) -> dict[str, int]:
    if not sqlite_path.is_file():
        raise MigrationError(f"SQLite file not found: {sqlite_path}")
    if is_sqlite_url(postgres_url):
        raise MigrationError(
            "Destination URL is still SQLite. Set POSTGRES_* or FORIFLOW_DATABASE_URL."
        )

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    try:
        assert_schema(sqlite_conn)
        existing_tables = {
            row[0]
            for row in sqlite_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        copy_tables: dict[str, tuple[str, ...]] = dict(EXPECTED)
        for name, columns in OPTIONAL.items():
            if name in existing_tables:
                copy_tables[name] = columns
        table_order = tuple(copy_tables)

        pg = create_engine(postgres_url, future=True)
        with pg.connect() as probe:
            for table in table_order:
                count = probe.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                if count:
                    raise MigrationError(
                        f"Postgres table {table!r} already has {count} row(s). "
                        "Refusing to copy so existing data is not duplicated."
                    )

        copied: dict[str, int] = {}
        with pg.begin() as connection:
            for table in table_order:
                columns = copy_tables[table]
                col_sql = ", ".join(columns)
                placeholders = ", ".join(f":{name}" for name in columns)
                rows = sqlite_conn.execute(f"SELECT {col_sql} FROM {table}").fetchall()
                if rows:
                    insert = text(
                        f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
                    )
                    connection.execute(
                        insert, [dict(zip(columns, row, strict=True)) for row in rows]
                    )
                copied[table] = len(rows)
            for table in table_order:
                connection.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                        f"(SELECT MAX(id) IS NOT NULL FROM {table}))"
                    )
                )
        pg.dispose()
        return copied
    finally:
        sqlite_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path("foriflow.db"),
        help="Path to the existing SQLite file.",
    )
    parser.add_argument(
        "--postgres-url",
        default="",
        help="SQLAlchemy Postgres URL. Defaults to config.database_url().",
    )
    args = parser.parse_args(argv)
    dest = args.postgres_url.strip() or database_url()
    try:
        copied = migrate(args.sqlite, dest)
    except MigrationError as exc:
        print(f"MIGRATION STOPPED: {exc}", file=sys.stderr)
        return 1
    print("Copied SQLite -> Postgres (IDs preserved):")
    for table, count in copied.items():
        print(f"  {table}: {count} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
