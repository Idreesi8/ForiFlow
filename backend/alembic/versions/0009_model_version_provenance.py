"""Model provenance: how a model version can be reproduced.

Adds ``model_versions.provenance`` (JSON, nullable): dataset identifier and
SHA-256, random seed, train / validation / final-test split with row-id
fingerprints, preprocessing version, calibration method and learner
configuration. Recorded for models trained under the 2.2 protocol.

Existing rows keep ``provenance`` NULL: that information was not recorded
when they were registered, and none is invented. Their version string, artefact
fingerprint, metrics and the applications that point at them are unchanged.

Revision ID: 0009_model_provenance
Revises: 0008_ews_history_alerts
Create Date: 2026-10-08
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_model_provenance"
down_revision: Union[str, Sequence[str], None] = "0008_ews_history_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("provenance", JSON_TYPE, nullable=True))
    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM model_versions")).scalar_one()
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
                    "model_versions_left_without_provenance": existing,
                    "rule": "column added; existing model versions unchanged, provenance not invented",
                },
            }
        ],
    )


def downgrade() -> None:
    op.drop_column("model_versions", "provenance")
