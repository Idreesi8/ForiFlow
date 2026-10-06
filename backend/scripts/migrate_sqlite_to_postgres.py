"""Copy existing SQLite rows into PostgreSQL without changing IDs or FKs.

Run from ``backend/`` after Postgres is up and Alembic has created the schema::

    python -m scripts.migrate_sqlite_to_postgres --sqlite ./foriflow.db

Docker (legacy volume still mounted at /data)::

    python -m scripts.migrate_sqlite_to_postgres --sqlite /data/foriflow.db

Aborts if the SQLite schema does not match the expected column set, if a
type cannot be copied without coercion, or if Postgres already has rows.

A file from before borrowers existed (migration 0006) has no borrower for its
applications. Each one is given its own borrower as it is copied, by the same
rule the migration uses: created in application-id order from the application's
own details, never merged on a name.
"""

from __future__ import annotations

import argparse
import json
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

# The same tables after migration 0003 (officer decisions and alert handling).
# A SQLite file created by this version has these; an older file has EXPECTED.
_APP = EXPECTED["applications"]
EXPECTED_0003: dict[str, tuple[str, ...]] = {
    "applications": (
        *_APP[: _APP.index("created_at")],
        "scored_by",
        "review_decision",
        "review_note",
        "reviewed_by",
        "reviewed_at",
        "created_at",
    ),
    "alerts": (*EXPECTED["alerts"], "assigned_to", "resolved_by", "resolution_note"),
}

# After migration 0004 (business sector, amount paid per monitored month).
_APP3 = EXPECTED_0003["applications"]
EXPECTED_0004: dict[str, tuple[str, ...]] = {
    "applications": (
        *_APP3[: _APP3.index("scored_by")],
        "business_sector",
        *_APP3[_APP3.index("scored_by") :],
    ),
    "alerts": EXPECTED_0003["alerts"],
    "ews_tracking": (*EXPECTED["ews_tracking"], "amount_paid_pkr"),
}

# After migration 0005 (turnover evidence and a contact number).
_APP4 = EXPECTED_0004["applications"]
EXPECTED_0005: dict[str, tuple[str, ...]] = {
    **EXPECTED_0004,
    "applications": (
        *_APP4[: _APP4.index("scored_by")],
        "turnover_evidence_json",
        "contact_phone",
        *_APP4[_APP4.index("scored_by") :],
    ),
}

# After migration 0006 (borrower link and the model that scored each application).
_APP5 = EXPECTED_0005["applications"]
EXPECTED_0006: dict[str, tuple[str, ...]] = {
    **EXPECTED_0005,
    "applications": (
        "id",
        "borrower_id",
        *_APP5[1 : _APP5.index("business_sector")],
        "model_version",
        "scoring_engine",
        "model_version_id",
        *_APP5[_APP5.index("business_sector") :],
    ),
}

# After migration 0007 (model assessment, policy recommendation, human decision).
_APP6 = EXPECTED_0006["applications"]
_NEW_0007 = (
    "raw_pd",
    "calibrated_pd",
    "risk_band",
    "policy_id",
    "policy_version",
    "policy_evaluation",
    "reason_codes",
    "decision_status",
    "decision_source",
    "escalated_by",
    "escalated_at",
    "escalation_note",
    "supersedes_application_id",
    "superseded_by_application_id",
)
EXPECTED_0007: dict[str, tuple[str, ...]] = {
    **EXPECTED_0006,
    "applications": (
        *_APP6[: _APP6.index("business_sector")],
        *_NEW_0007,
        *_APP6[_APP6.index("business_sector") :],
    ),
}

# SQLite declared types we will copy without rewriting values.
_INT = {"INT", "INTEGER", "BIGINT"}
_FLOAT = {"REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION", "NUMERIC", "DECIMAL"}
_TEXT = {"TEXT", "VARCHAR", "NVARCHAR", "CHAR", "CLOB", "STRING"}
_TIME = {"DATETIME", "TIMESTAMP", "DATE"}
_JSON = {"JSON"}
_BOOL = {"BOOLEAN"}
_COMPATIBLE = _INT | _FLOAT | _TEXT | _TIME | _JSON | _BOOL

# Parents before children, so every foreign key finds its row.
TABLE_ORDER = (
    "users",
    "borrowers",
    "model_versions",
    "credit_policies",
    "applications",
    "alerts",
    "ews_tracking",
    "audit_logs",
)

# Present on SQLite after Step 2 create_all; absent on a pre-auth file.
OPTIONAL: dict[str, tuple[str, ...]] = {
    "users": (
        "id",
        "username",
        "hashed_password",
        "role",
        "created_at",
    ),
    # Present from migration 0006.
    "borrowers": (
        "id",
        "public_id",
        "business_name",
        "owner_name",
        "identifier_type",
        "identifier",
        "contact_phone",
        "business_sector",
        "years_in_operation",
        "status",
        "created_at",
        "updated_at",
    ),
    "model_versions": (
        "id",
        "version",
        "engine",
        "artifact_sha256",
        "training_dataset",
        "feature_set",
        "feature_set_version",
        "trained_at",
        "metrics",
        "status",
        "fallback_reason",
        "registered_at",
    ),
    # Present from migration 0007.
    "credit_policies": (
        "id",
        "version",
        "name",
        "description",
        "status",
        "decline_max_score",
        "manual_review_max_score",
        "manager_approval_limit_pkr",
        "decline_override_admin_only",
        "created_at",
        "created_by",
        "activated_at",
        "activated_by",
        "retired_at",
    ),
    "audit_logs": (
        "id",
        "occurred_at",
        "user_id",
        "username",
        "role",
        "action",
        "entity_type",
        "entity_id",
        "previous_state",
        "new_state",
        "details",
        "ip_address",
        "request_id",
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


def assert_schema(connection: sqlite3.Connection) -> dict[str, tuple[str, ...]]:
    """Stop if column names differ or a type is not in the allowed set.

    Returns the column tuple to copy for each table present.
    """
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

    matched: dict[str, tuple[str, ...]] = {}
    for table, expected in tables_to_check.items():
        cols = sqlite_columns(connection, table)
        names = tuple(name for name, _type in cols)
        if names not in (
            expected,
            EXPECTED_0003.get(table),
            EXPECTED_0004.get(table),
            EXPECTED_0005.get(table),
            EXPECTED_0006.get(table),
            EXPECTED_0007.get(table),
        ):
            raise MigrationError(
                f"Table {table!r} columns {names} do not match expected {expected}."
            )
        for name, declared in cols:
            if declared not in _COMPATIBLE and not declared.startswith("VARCHAR"):
                raise MigrationError(
                    f"Table {table!r} column {name!r} has type {declared!r} "
                    "which this script will not coerce."
                )
        matched[table] = names
    return matched


def _stored_model_version(explanation_json: str | None) -> str | None:
    """The version string inside a stored explanation, if it can be read."""
    if not explanation_json:
        return None
    try:
        value = json.loads(explanation_json).get("model_version")
    except (ValueError, AttributeError):
        return None
    return value[:120] if isinstance(value, str) and value else None


def _engine_of(model_version: str | None) -> str | None:
    """Read the scoring engine off a version string, or None if unclear."""
    if not model_version:
        return None
    if model_version.startswith("ensemble-"):
        return "ml"
    if model_version.startswith("surrogate-"):
        return "surrogate"
    return None


_BAND_OF = {"Rejected": "High Risk", "Manual Review": "Medium Risk", "Approved": "Low Risk"}


def _with_legacy_decision(row: dict) -> dict:
    """Give a pre-2.0 application the decision status its record already implied.

    Mirrors migration 0007. Before 2.0 an Approved or Rejected band was final
    by itself, so those rows are marked decided with source ``legacy_auto``: no
    officer is invented for them. A Manual Review row keeps the officer's
    decision if one was recorded and is Pending otherwise.
    """
    band, review = row["decision"], row.get("review_decision")
    if band == "Manual Review":
        status, source = (review, "officer") if review else ("Pending", None)
    else:
        status, source = band, "legacy_auto"
    return {
        **row,
        "decision_status": status,
        "decision_source": source,
        "risk_band": _BAND_OF.get(band),
    }


def _with_new_borrowers(connection, applications: list[dict]) -> list[dict]:
    """Open one borrower per legacy application and return the linked rows.

    Mirrors the backfill in migration 0006: in application-id order, from the
    application's own details, never merged on a name.
    """
    linked: list[dict] = []
    for row in applications:
        borrower_id = connection.execute(
            text(
                "INSERT INTO borrowers (business_name, owner_name, contact_phone, "
                "business_sector, years_in_operation, status, created_at, updated_at) "
                "VALUES (:business_name, :owner_name, :contact_phone, :business_sector, "
                ":years_in_operation, 'active', :created_at, :created_at) RETURNING id"
            ),
            {
                "business_name": row["business_name"],
                "owner_name": row["applicant_name"],
                "contact_phone": row.get("contact_phone"),
                "business_sector": row.get("business_sector"),
                "years_in_operation": row["years_in_operation"],
                "created_at": row["created_at"],
            },
        ).scalar_one()
        connection.execute(
            text("UPDATE borrowers SET public_id = :public_id WHERE id = :id"),
            {"public_id": f"BRW-{borrower_id:06d}", "id": borrower_id},
        )
        version = _stored_model_version(row.get("shap_explanation_json"))
        linked.append(
            {
                **row,
                "borrower_id": borrower_id,
                "model_version": version,
                "scoring_engine": _engine_of(version),
            }
        )
    return linked


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
        copy_tables = assert_schema(sqlite_conn)
        table_order = tuple(table for table in TABLE_ORDER if table in copy_tables)
        # A file from before migration 0006: its applications have no borrower.
        needs_borrowers = "borrower_id" not in copy_tables["applications"]
        # A file from before migration 0007: no recorded decision status.
        needs_decision_status = "decision_status" not in copy_tables["applications"]
        if needs_borrowers and "borrowers" in copy_tables:
            raise MigrationError(
                "SQLite has a borrowers table but applications without borrower_id."
            )

        pg = create_engine(postgres_url, future=True)
        with pg.connect() as probe:
            must_be_empty = (*table_order, "borrowers") if needs_borrowers else table_order
            for table in dict.fromkeys(must_be_empty):
                # Applying the migrations to an empty database writes their own
                # audit entries and the demo policy; those are expected.
                clause = ""
                if table == "audit_logs":
                    clause = " WHERE username <> 'system'"
                elif table == "credit_policies":
                    clause = " WHERE created_by <> 'system'"
                count = probe.execute(text(f"SELECT COUNT(*) FROM {table}{clause}")).scalar_one()
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
                rows = [
                    dict(zip(columns, row, strict=True))
                    for row in sqlite_conn.execute(
                        f"SELECT {col_sql} FROM {table} ORDER BY id"
                    ).fetchall()
                ]
                if table == "audit_logs":
                    # Its ids would collide with the migration's own entry, and
                    # an audit id means nothing outside its own database.
                    columns = tuple(name for name in columns if name != "id")
                    rows = [{name: row[name] for name in columns} for row in rows]
                if table == "applications" and needs_borrowers:
                    columns = (*columns, "borrower_id", "model_version", "scoring_engine")
                    rows = _with_new_borrowers(connection, rows)
                    copied["borrowers"] = len(rows)
                if table == "applications" and needs_decision_status:
                    columns = (*columns, "decision_status", "decision_source", "risk_band")
                    rows = [_with_legacy_decision(row) for row in rows]
                if table == "applications":
                    # A row can point at a later one (superseded_by), so the
                    # links are filled in after every row exists.
                    links = [
                        (row["id"], row.get("superseded_by_application_id"))
                        for row in rows
                        if row.get("superseded_by_application_id") is not None
                    ]
                    rows = [
                        {**row, "superseded_by_application_id": None}
                        if "superseded_by_application_id" in row
                        else row
                        for row in rows
                    ]
                if table == "credit_policies":
                    # The source's policies replace the demo one seeded by the
                    # migration; no application in this empty database uses it.
                    connection.execute(text("DELETE FROM credit_policies"))
                    rows = [
                        {**row, "decline_override_admin_only": bool(row["decline_override_admin_only"])}
                        for row in rows
                    ]
                if rows:
                    placeholders = ", ".join(f":{name}" for name in columns)
                    connection.execute(
                        text(
                            f"INSERT INTO {table} ({', '.join(columns)}) "
                            f"VALUES ({placeholders})"
                        ),
                        rows,
                    )
                copied[table] = len(rows)
                if table == "applications":
                    for application_id, later_id in links:
                        connection.execute(
                            text(
                                "UPDATE applications SET superseded_by_application_id = :later "
                                "WHERE id = :id"
                            ),
                            {"later": later_id, "id": application_id},
                        )
            for table in dict.fromkeys((*table_order, *(("borrowers",) if needs_borrowers else ()))):
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
