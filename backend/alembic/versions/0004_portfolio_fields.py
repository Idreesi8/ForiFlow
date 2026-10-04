"""Business sector on applications and the amount paid in each monitored month.

Both are nullable: rows recorded before this revision simply have no sector and
no payment amount, and the portfolio figures say how many such rows there are.

Revision ID: 0004_portfolio_fields
Revises: 0003_officer_decisions
Create Date: 2026-10-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_portfolio_fields"
down_revision: Union[str, Sequence[str], None] = "0003_officer_decisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications", sa.Column("business_sector", sa.String(length=40), nullable=True)
    )
    op.create_index("ix_applications_business_sector", "applications", ["business_sector"])
    op.add_column("ews_tracking", sa.Column("amount_paid_pkr", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("ews_tracking", "amount_paid_pkr")
    op.drop_index("ix_applications_business_sector", table_name="applications")
    op.drop_column("applications", "business_sector")
