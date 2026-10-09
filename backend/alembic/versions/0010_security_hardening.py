"""Security hardening: account status, sign-in throttling, token revocation.

* ``users.is_active`` (boolean, default true). Every existing account stays
  enabled; an admin can disable one later. Nothing is deleted.
* ``login_attempts``: recent failed sign-ins per typed username, for the
  temporary lockout. Starts empty.
* ``revoked_tokens``: the ids (``jti``) of signed-out tokens until they
  expire. Starts empty. No token is stored.

No credit, model, EWS or policy data is touched. Tokens issued before 2.3 are
refused afterwards (they carry no ``jti``), so officers sign in again once.

Revision ID: 0010_security_hardening
Revises: 0009_model_provenance
Create Date: 2026-10-09
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_security_hardening"
down_revision: Union[str, Sequence[str], None] = "0009_model_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_table(
        "login_attempts",
        sa.Column("username_key", sa.String(length=64), primary_key=True),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"])

    bind = op.get_bind()
    accounts = bind.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one()
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
        audit.insert(),
        [
            {
                "occurred_at": datetime.now(timezone.utc),
                "username": "system",
                "action": "migration.applied",
                "entity_type": "migration",
                "entity_id": revision,
                "details": {
                    "accounts_left_enabled": accounts,
                    "rule": (
                        "is_active added (all existing accounts enabled); login_attempts "
                        "and revoked_tokens created empty; no credit data changed"
                    ),
                },
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_table("login_attempts")
    op.drop_column("users", "is_active")
