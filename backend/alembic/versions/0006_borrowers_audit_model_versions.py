"""Borrowers, an append-only audit trail and model version tracking.

Three additions, and no existing row is removed or rewritten:

* ``borrowers``: the business behind one or more applications.
  ``applications.borrower_id`` points to it and is NOT NULL once backfilled.
* ``audit_logs``: who did what and when. Triggers refuse UPDATE, DELETE and
  TRUNCATE, so the table can only grow.
* ``model_versions`` plus ``applications.model_version``, ``scoring_engine``
  and ``model_version_id``: which model produced each score.

Backfill of existing applications
---------------------------------
Until now every application stood alone, with no CNIC, NTN or other identifier
that could say two of them were the same business. So each existing application
gets **its own borrower**, created in application-id order from that
application's own business name, applicant name, contact number, sector and
years in operation. Applications are never merged on a matching name: two shops
can share a name, and guessing would file one business's history under another.
An officer can file new applications under an existing borrower from now on.

``model_version`` is copied from the explanation stored with each application
(it has carried the version string since scoring), and ``scoring_engine`` is
read off that string. Where no explanation is readable both stay NULL rather
than being guessed. ``model_version_id`` stays NULL for all of them: the
artefact fingerprint was not recorded at the time and cannot be recovered.

One ``migration.applied`` audit entry records the counts.

Revision ID: 0006_borrowers_audit_models
Revises: 0005_roles_and_evidence
Create Date: 2026-10-07
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_borrowers_audit_models"
down_revision: Union[str, Sequence[str], None] = "0005_roles_and_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

APPEND_ONLY_SQL: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit_logs is append-only';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_logs_no_change BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()
    """,
    """
    CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_append_only()
    """,
)


def engine_of(model_version: str | None) -> str | None:
    """Read the scoring engine off a stored version string, or None if unclear."""
    if not model_version:
        return None
    if model_version.startswith("ensemble-"):
        return "ml"
    if model_version.startswith("surrogate-"):
        return "surrogate"
    return None


def stored_model_version(explanation_json: str | None) -> str | None:
    """The version string inside a stored explanation, if it can be read."""
    if not explanation_json:
        return None
    try:
        value = json.loads(explanation_json).get("model_version")
    except (ValueError, AttributeError):
        return None
    return value[:120] if isinstance(value, str) and value else None


def upgrade() -> None:
    op.create_table(
        "borrowers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.String(length=16), nullable=True),
        sa.Column("business_name", sa.String(length=160), nullable=False),
        sa.Column("owner_name", sa.String(length=120), nullable=False),
        sa.Column("identifier_type", sa.String(length=8), nullable=True),
        sa.Column("identifier", sa.String(length=20), nullable=True),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("business_sector", sa.String(length=40), nullable=True),
        sa.Column("years_in_operation", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        # NULLs do not collide in a unique constraint, so any number of
        # borrowers may have no identifier.
        sa.UniqueConstraint("identifier"),
        sa.CheckConstraint(
            "(identifier IS NULL AND identifier_type IS NULL) OR "
            "(identifier IS NOT NULL AND identifier_type IS NOT NULL "
            "AND identifier_type IN ('CNIC', 'NTN'))",
            name="ck_borrowers_identifier",
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_borrowers_status"),
    )
    op.create_index("ix_borrowers_business_name", "borrowers", ["business_name"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=120), nullable=False),
        sa.Column("engine", sa.String(length=16), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("training_dataset", sa.String(length=80), nullable=True),
        sa.Column("feature_set", JSON_TYPE, nullable=True),
        sa.Column("feature_set_version", sa.String(length=16), nullable=True),
        sa.Column("trained_at", sa.String(length=32), nullable=True),
        sa.Column("metrics", JSON_TYPE, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("fallback_reason", sa.String(length=32), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("engine IN ('ml', 'surrogate')", name="ck_model_versions_engine"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_model_versions_status"),
    )
    op.create_index(
        "uq_model_versions_version_artifact",
        "model_versions",
        ["version", "artifact_sha256"],
        unique=True,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("previous_state", JSON_TYPE, nullable=True),
        sa.Column("new_state", JSON_TYPE, nullable=True),
        sa.Column("details", JSON_TYPE, nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    op.add_column("applications", sa.Column("borrower_id", sa.Integer(), nullable=True))
    op.add_column(
        "applications", sa.Column("model_version", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "applications", sa.Column("scoring_engine", sa.String(length=16), nullable=True)
    )
    op.add_column("applications", sa.Column("model_version_id", sa.Integer(), nullable=True))

    # --- backfill: one borrower per existing application, in id order ---------
    bind = op.get_bind()
    borrowers = sa.table(
        "borrowers",
        sa.column("id", sa.Integer),
        sa.column("public_id", sa.String),
        sa.column("business_name", sa.String),
        sa.column("owner_name", sa.String),
        sa.column("contact_phone", sa.String),
        sa.column("business_sector", sa.String),
        sa.column("years_in_operation", sa.Float),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    applications = sa.table(
        "applications",
        sa.column("id", sa.Integer),
        sa.column("borrower_id", sa.Integer),
        sa.column("model_version", sa.String),
        sa.column("scoring_engine", sa.String),
    )
    existing = bind.execute(
        sa.text(
            "SELECT id, business_name, applicant_name, contact_phone, business_sector, "
            "years_in_operation, created_at, shap_explanation_json "
            "FROM applications ORDER BY id"
        )
    ).mappings().all()

    versions: dict[str, int] = {}
    for row in existing:
        borrower_id = bind.execute(
            borrowers.insert()
            .values(
                business_name=row["business_name"],
                owner_name=row["applicant_name"],
                contact_phone=row["contact_phone"],
                business_sector=row["business_sector"],
                years_in_operation=row["years_in_operation"],
                status="active",
                created_at=row["created_at"],
                updated_at=row["created_at"],
            )
            .returning(borrowers.c.id)
        ).scalar_one()
        bind.execute(
            borrowers.update()
            .where(borrowers.c.id == borrower_id)
            .values(public_id=f"BRW-{borrower_id:06d}")
        )
        version = stored_model_version(row["shap_explanation_json"])
        bind.execute(
            applications.update()
            .where(applications.c.id == row["id"])
            .values(
                borrower_id=borrower_id,
                model_version=version,
                scoring_engine=engine_of(version),
            )
        )
        key = version or "unrecorded"
        versions[key] = versions.get(key, 0) + 1

    op.alter_column("applications", "borrower_id", nullable=False)
    op.create_foreign_key(
        "fk_applications_borrower_id",
        "applications",
        "borrowers",
        ["borrower_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_applications_model_version_id",
        "applications",
        "model_versions",
        ["model_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_applications_borrower_id", "applications", ["borrower_id"])
    op.create_index("ix_applications_model_version", "applications", ["model_version"])
    op.create_index(
        "ix_applications_model_version_id", "applications", ["model_version_id"]
    )

    audit = sa.table(
        "audit_logs",
        sa.column("occurred_at", sa.DateTime(timezone=True)),
        sa.column("username", sa.String),
        sa.column("action", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("entity_id", sa.String),
        sa.column("details", JSON_TYPE),
    )
    bind.execute(
        audit.insert().values(
            occurred_at=datetime.now(timezone.utc),
            username="system",
            action="migration.applied",
            entity_type="migration",
            entity_id=revision,
            details={
                "applications_backfilled": len(existing),
                "borrowers_created": len(existing),
                "rule": "one borrower per existing application; none merged by name",
                "model_versions_copied_from_stored_explanations": versions,
            },
        )
    )

    # Last, so the entry above is the only write the triggers never saw.
    if bind.dialect.name == "postgresql":
        for statement in APPEND_ONLY_SQL:
            op.execute(statement)


def downgrade() -> None:
    """Remove what this revision added. The audit trail is lost with it."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs")
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_change ON audit_logs")
    op.drop_index("ix_applications_model_version_id", table_name="applications")
    op.drop_index("ix_applications_model_version", table_name="applications")
    op.drop_index("ix_applications_borrower_id", table_name="applications")
    op.drop_constraint("fk_applications_model_version_id", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_borrower_id", "applications", type_="foreignkey")
    op.drop_column("applications", "model_version_id")
    op.drop_column("applications", "scoring_engine")
    op.drop_column("applications", "model_version")
    op.drop_column("applications", "borrower_id")
    op.drop_table("audit_logs")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_table("model_versions")
    op.drop_table("borrowers")
