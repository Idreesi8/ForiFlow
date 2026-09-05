"""Initial ForiFlow schema — applications, alerts, ews_tracking.

Matches ``models.database`` as of the SQLite create_all schema. No extra
unique constraints are added in this revision.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("applicant_name", sa.String(length=120), nullable=False),
        sa.Column("business_name", sa.String(length=160), nullable=False),
        sa.Column("loan_amount_pkr", sa.Float(), nullable=False),
        sa.Column("tenure_months", sa.Integer(), nullable=False),
        sa.Column("monthly_digital_payments", sa.Float(), nullable=False),
        sa.Column("payment_history_score", sa.Float(), nullable=False),
        sa.Column("inventory_turnover", sa.Float(), nullable=False),
        sa.Column("order_consistency", sa.Float(), nullable=False),
        sa.Column("existing_debt_pkr", sa.Float(), nullable=False),
        sa.Column("cash_flow_proxy", sa.Float(), nullable=False),
        sa.Column("years_in_operation", sa.Float(), nullable=False),
        sa.Column("num_employees", sa.Integer(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("shap_explanation_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_created_at", "applications", ["created_at"])
    op.create_index("ix_applications_decision", "applications", ["decision"])
    op.create_index("ix_applications_risk_score", "applications", ["risk_score"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("borrower_id", sa.Integer(), nullable=False),
        sa.Column("baseline_score", sa.Float(), nullable=False),
        sa.Column("current_score", sa.Float(), nullable=False),
        sa.Column("score_drop", sa.Float(), nullable=False),
        sa.Column("estimated_days_to_default", sa.Integer(), nullable=False),
        sa.Column("alert_status", sa.String(length=32), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["borrower_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_alert_status", "alerts", ["alert_status"])
    op.create_index("ix_alerts_borrower_id", "alerts", ["borrower_id"])
    op.create_index("ix_alerts_triggered_at", "alerts", ["triggered_at"])

    op.create_table(
        "ews_tracking",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("borrower_id", sa.Integer(), nullable=False),
        sa.Column("month_number", sa.Integer(), nullable=False),
        sa.Column("installment_status", sa.String(length=32), nullable=False),
        sa.Column("bureau_balance", sa.Float(), nullable=False),
        sa.Column("pos_cash_balance", sa.Float(), nullable=False),
        sa.Column("monthly_score", sa.Float(), nullable=False),
        sa.Column("data_source_primary", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["borrower_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ews_tracking_borrower_id", "ews_tracking", ["borrower_id"])
    op.create_index("ix_ews_tracking_month_number", "ews_tracking", ["month_number"])


def downgrade() -> None:
    op.drop_index("ix_ews_tracking_month_number", table_name="ews_tracking")
    op.drop_index("ix_ews_tracking_borrower_id", table_name="ews_tracking")
    op.drop_table("ews_tracking")
    op.drop_index("ix_alerts_triggered_at", table_name="alerts")
    op.drop_index("ix_alerts_borrower_id", table_name="alerts")
    op.drop_index("ix_alerts_alert_status", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_applications_risk_score", table_name="applications")
    op.drop_index("ix_applications_decision", table_name="applications")
    op.drop_index("ix_applications_created_at", table_name="applications")
    op.drop_table("applications")
