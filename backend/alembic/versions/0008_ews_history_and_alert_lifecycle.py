"""EWS: immutable monthly history, score provenance and an alert lifecycle.

``ews_tracking`` (one row per facility-month observation) gains its date, days
late, where its score came from, who recorded it and in which request, and the
links of a correction. A recorded month is no longer overwritten: a
correction adds a row and marks the original ``superseded``. A partial unique
index allows one ``active`` row per facility and month.

``alerts`` gains severity, reason codes, evidence, recommended actions, the
observations it rests on, and the lifecycle fields (acknowledged, assigned,
due date, action note). A partial unique index allows one open alert per
facility.

Existing rows
-------------
Nothing is deleted and nothing is invented:

* Observations recorded before this revision get ``score_source =
  'legacy_unknown'`` (whether a score was typed or derived was not stored)
  and ``record_status = 'active'``. Date, days late, author and request stay
  NULL because they were never recorded.
* If a facility somehow has two rows for one month (the old code overwrote,
  so this should not happen), the older rows are kept and marked
  ``superseded`` by the newest, with a correction reason saying so.
* Alert statuses are renamed: ``Active`` -> ``Open``, ``In Review`` ->
  ``Acknowledged``. For an alert that was In Review, ``acknowledged_by`` is the
  officer who took it (its ``assigned_to``); the time was not recorded and
  stays NULL. ``Resolved`` is unchanged.
* Legacy alerts keep ``severity``, ``reason_codes`` and ``evidence`` NULL: they
  were raised by a score drop alone and no reasons were stored.

The migration refuses to run if a facility has more than one open alert,
because choosing which to close is an officer's decision.

Revision ID: 0008_ews_history_alerts
Revises: 0007_policy_human_decision
Create Date: 2026-10-08
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_ews_history_alerts"
down_revision: Union[str, Sequence[str], None] = "0007_policy_human_decision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

OPEN = "('Open', 'Acknowledged', 'Action Required')"
STATUS_RENAMES = (("Active", "Open"), ("In Review", "Acknowledged"))
DUPLICATE_NOTE = (
    "Migration 0008 found more than one row for this month; the newest is kept "
    "active and this one is kept as history."
)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    # --- refuse what an officer must decide --------------------------------------
    crowded = bind.execute(
        sa.text(
            "SELECT borrower_id, COUNT(*) FROM alerts "
            "WHERE alert_status IN ('Active', 'In Review') "
            "GROUP BY borrower_id HAVING COUNT(*) > 1"
        )
    ).all()
    if crowded:
        listing = ", ".join(f"application {row[0]} ({row[1]} open)" for row in crowded)
        raise RuntimeError(
            "Migration 0008 stopped: these facilities have more than one open alert: "
            f"{listing}. Resolve the extra alerts, then run the migration again."
        )

    # --- ews_tracking ------------------------------------------------------------------
    for column in (
        sa.Column("observation_date", sa.Date(), nullable=True),
        sa.Column("days_late", sa.Integer(), nullable=True),
        sa.Column("score_source", sa.String(length=32), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("rule_score", sa.Float(), nullable=True),
        sa.Column("record_status", sa.String(length=16), nullable=True),
        sa.Column("supersedes_observation_id", sa.Integer(), nullable=True),
        sa.Column("superseded_by_observation_id", sa.Integer(), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("assessment", JSON_TYPE, nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
    ):
        op.add_column("ews_tracking", column)

    legacy_observations = bind.execute(
        sa.text(
            "UPDATE ews_tracking SET score_source = 'legacy_unknown', record_status = 'active'"
        )
    ).rowcount

    duplicates = 0
    groups = bind.execute(
        sa.text(
            "SELECT borrower_id, month_number FROM ews_tracking "
            "GROUP BY borrower_id, month_number HAVING COUNT(*) > 1"
        )
    ).all()
    for borrower_id, month_number in groups:
        ids = [
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT id FROM ews_tracking WHERE borrower_id = :b AND month_number = :m "
                    "ORDER BY id"
                ),
                {"b": borrower_id, "m": month_number},
            ).all()
        ]
        newest = ids[-1]
        for older in ids[:-1]:
            bind.execute(
                sa.text(
                    "UPDATE ews_tracking SET record_status = 'superseded', "
                    "superseded_by_observation_id = :newest, correction_reason = :note "
                    "WHERE id = :id"
                ),
                {"newest": newest, "note": DUPLICATE_NOTE, "id": older},
            )
            duplicates += 1

    op.alter_column("ews_tracking", "score_source", nullable=False)
    op.alter_column("ews_tracking", "record_status", nullable=False)
    op.create_check_constraint(
        "ck_ews_tracking_record_status",
        "ews_tracking",
        "record_status IN ('active', 'superseded')",
    )
    op.create_check_constraint(
        "ck_ews_tracking_score_source",
        "ews_tracking",
        "score_source IN ('ews_rule_adjusted', 'officer_override', "
        "'latest_foriflow_assessment', 'origination_assessment', 'legacy_unknown')",
    )
    op.create_check_constraint(
        "ck_ews_tracking_override_reason",
        "ews_tracking",
        "score_source <> 'officer_override' OR override_reason IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_ews_tracking_supersedes",
        "ews_tracking",
        "ews_tracking",
        ["supersedes_observation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_ews_tracking_superseded_by",
        "ews_tracking",
        "ews_tracking",
        ["superseded_by_observation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_ews_tracking_active_month",
        "ews_tracking",
        ["borrower_id", "month_number"],
        unique=True,
        postgresql_where=sa.text("record_status = 'active'"),
        sqlite_where=sa.text("record_status = 'active'"),
    )

    # --- alerts --------------------------------------------------------------------------
    for column in (
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("reason_codes", JSON_TYPE, nullable=True),
        sa.Column("evidence", JSON_TYPE, nullable=True),
        sa.Column("previous_score", sa.Float(), nullable=True),
        sa.Column("recommended_actions", JSON_TYPE, nullable=True),
        sa.Column("observation_id", sa.Integer(), nullable=True),
        sa.Column("last_observation_id", sa.Integer(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=64), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_by", sa.String(length=64), nullable=True),
        sa.Column("action_due_date", sa.Date(), nullable=True),
        sa.Column("action_note", sa.Text(), nullable=True),
    ):
        op.add_column("alerts", column)

    renamed: dict[str, int] = {}
    bind.execute(
        sa.text(
            "UPDATE alerts SET acknowledged_by = assigned_to "
            "WHERE alert_status = 'In Review' AND assigned_to IS NOT NULL"
        )
    )
    for old, new in STATUS_RENAMES:
        renamed[f"{old} -> {new}"] = bind.execute(
            sa.text("UPDATE alerts SET alert_status = :new WHERE alert_status = :old"),
            {"new": new, "old": old},
        ).rowcount
    legacy_alerts = bind.execute(sa.text("SELECT COUNT(*) FROM alerts")).scalar_one()

    op.create_check_constraint(
        "ck_alerts_status",
        "alerts",
        "alert_status IN ('Open', 'Acknowledged', 'Action Required', 'Resolved', 'Dismissed')",
    )
    op.create_check_constraint(
        "ck_alerts_severity",
        "alerts",
        "severity IS NULL OR severity IN ('WARNING', 'CRITICAL')",
    )
    op.create_foreign_key(
        "fk_alerts_observation_id",
        "alerts",
        "ews_tracking",
        ["observation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_alerts_last_observation_id",
        "alerts",
        "ews_tracking",
        ["last_observation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_alerts_severity", "alerts", ["severity"])
    op.create_index(
        "uq_alerts_one_open_per_facility",
        "alerts",
        ["borrower_id"],
        unique=True,
        postgresql_where=sa.text(f"alert_status IN {OPEN}"),
        sqlite_where=sa.text(f"alert_status IN {OPEN}"),
    )

    audit = sa.table(
        "audit_logs",
        sa.column("occurred_at", sa.DateTime(timezone=True)),
        sa.column("username", sa.String),
        sa.column("action", sa.String),
        sa.column("entity_type", sa.String),
        sa.column("entity_id", sa.String),
        sa.column("previous_state", JSON_TYPE),
        sa.column("new_state", JSON_TYPE),
        sa.column("details", JSON_TYPE),
    )
    bind.execute(
        audit.insert(),
        [
            {
                "occurred_at": now,
                "username": "system",
                "action": "migration.applied",
                "entity_type": "migration",
                "entity_id": revision,
                "previous_state": None,
                "new_state": None,
                "details": {
                    "observations_marked_legacy_unknown": legacy_observations,
                    "duplicate_months_kept_as_superseded": duplicates,
                    "alerts_on_file": legacy_alerts,
                    "alert_statuses_renamed": renamed,
                    "rule": (
                        "no row deleted; legacy observations marked legacy_unknown; "
                        "alert statuses renamed; no severity, reason, date or author invented"
                    ),
                },
            }
        ],
    )


def downgrade() -> None:
    """Remove what this revision added.

    Refused while corrections exist: pre-2.1 code expects one row per month
    and would read a superseded row as a second copy. Dismissed and Action
    Required have no pre-2.1 name and become Resolved and In Review.
    """
    bind = op.get_bind()
    superseded = bind.execute(
        sa.text("SELECT COUNT(*) FROM ews_tracking WHERE record_status = 'superseded'")
    ).scalar_one()
    if superseded:
        raise RuntimeError(
            f"Downgrade from 0008 stopped: {superseded} corrected observation(s) are on "
            "file and pre-2.1 code cannot tell them from the current month."
        )
    op.drop_index("uq_alerts_one_open_per_facility", table_name="alerts")
    op.drop_index("ix_alerts_severity", table_name="alerts")
    op.drop_constraint("fk_alerts_last_observation_id", "alerts", type_="foreignkey")
    op.drop_constraint("fk_alerts_observation_id", "alerts", type_="foreignkey")
    op.drop_constraint("ck_alerts_severity", "alerts", type_="check")
    op.drop_constraint("ck_alerts_status", "alerts", type_="check")
    for old, new in (
        ("Open", "Active"),
        ("Acknowledged", "In Review"),
        ("Action Required", "In Review"),
        ("Dismissed", "Resolved"),
    ):
        bind.execute(
            sa.text("UPDATE alerts SET alert_status = :new WHERE alert_status = :old"),
            {"new": new, "old": old},
        )
    for name in (
        "action_note",
        "action_due_date",
        "assigned_by",
        "assigned_at",
        "acknowledged_by",
        "acknowledged_at",
        "last_observation_id",
        "observation_id",
        "recommended_actions",
        "previous_score",
        "evidence",
        "reason_codes",
        "severity",
    ):
        op.drop_column("alerts", name)

    op.drop_index("uq_ews_tracking_active_month", table_name="ews_tracking")
    op.drop_constraint("fk_ews_tracking_superseded_by", "ews_tracking", type_="foreignkey")
    op.drop_constraint("fk_ews_tracking_supersedes", "ews_tracking", type_="foreignkey")
    op.drop_constraint("ck_ews_tracking_override_reason", "ews_tracking", type_="check")
    op.drop_constraint("ck_ews_tracking_score_source", "ews_tracking", type_="check")
    op.drop_constraint("ck_ews_tracking_record_status", "ews_tracking", type_="check")
    for name in (
        "request_id",
        "created_at",
        "created_by",
        "assessment",
        "correction_reason",
        "superseded_by_observation_id",
        "supersedes_observation_id",
        "record_status",
        "rule_score",
        "override_reason",
        "score_source",
        "days_late",
        "observation_date",
    ):
        op.drop_column("ews_tracking", name)
