"""A manager role, turnover evidence and a borrower contact number.

``manager`` sits between ``admin`` and ``analyst``: it decides Manual Review
cases and resolves alerts, but does not manage officer accounts. Existing
accounts keep their role. The two new application columns are nullable.

Revision ID: 0005_roles_and_evidence
Revises: 0004_portfolio_fields
Create Date: 2026-10-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_roles_and_evidence"
down_revision: Union[str, Sequence[str], None] = "0004_portfolio_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('admin', 'manager', 'analyst')"
    )
    op.add_column(
        "applications", sa.Column("turnover_evidence_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "applications", sa.Column("contact_phone", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("applications", "contact_phone")
    op.drop_column("applications", "turnover_evidence_json")
    # Managers become analysts so the narrower constraint can be restored.
    op.execute("UPDATE users SET role = 'analyst' WHERE role = 'manager'")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'analyst')")
