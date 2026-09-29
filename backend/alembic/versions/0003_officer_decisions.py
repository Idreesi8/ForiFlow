"""Record who scored an application, the officer decision on Manual Review
cases, and who handled each EWS alert.

Revision ID: 0003_officer_decisions
Revises: 0002_users
Create Date: 2026-09-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_officer_decisions"
down_revision: Union[str, Sequence[str], None] = "0002_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("scored_by", sa.String(length=64), nullable=True))
    op.add_column(
        "applications", sa.Column("review_decision", sa.String(length=32), nullable=True)
    )
    op.add_column("applications", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "applications", sa.Column("reviewed_by", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "applications",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_applications_review_decision",
        "applications",
        "review_decision IS NULL OR review_decision IN ('Approved', 'Rejected')",
    )

    op.add_column("alerts", sa.Column("assigned_to", sa.String(length=64), nullable=True))
    op.add_column("alerts", sa.Column("resolved_by", sa.String(length=64), nullable=True))
    op.add_column("alerts", sa.Column("resolution_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "resolution_note")
    op.drop_column("alerts", "resolved_by")
    op.drop_column("alerts", "assigned_to")

    op.drop_constraint("ck_applications_review_decision", "applications", type_="check")
    op.drop_column("applications", "reviewed_at")
    op.drop_column("applications", "reviewed_by")
    op.drop_column("applications", "review_note")
    op.drop_column("applications", "review_decision")
    op.drop_column("applications", "scored_by")
