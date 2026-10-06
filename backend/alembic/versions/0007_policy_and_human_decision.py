"""A versioned credit policy and an explicit human decision on every application.

Model, policy and human are now three separate records:

* ``credit_policies``: versioned cut-offs and authority limits. The demo
  policy (0-40 decline, 41-70 manual review, 71-100 approve; manager limit from
  ``MANAGER_APPROVAL_LIMIT_PKR`` or PKR 2,000,000) is inserted as version 1.0
  and made active. A partial unique index allows one active version.
* ``applications`` gains the model assessment (``raw_pd``, ``calibrated_pd``,
  ``risk_band``), the policy recommendation (``policy_id``, ``policy_version``,
  ``policy_evaluation``, ``reason_codes``) and the human decision
  (``decision_status``, ``decision_source``, escalation fields, re-score links).

Existing applications
---------------------
No row is deleted, and no decision or policy is invented:

* ``policy_id`` / ``policy_version`` stay NULL. No policy version was recorded
  when they were scored, so none is claimed now.
* ``risk_band`` is the band the stored recommendation already names (Rejected
  is High Risk, Manual Review is Medium Risk, Approved is Low Risk).
* ``calibrated_pd`` is copied from the stored explanation where it is there;
  ``raw_pd`` was never stored and stays NULL.
* ``decision_status`` records what each row's own columns already said under
  the rule in force when it was scored:
    - Manual Review with an officer decision: that decision, source ``officer``.
    - Manual Review without one: ``Pending``.
    - Approved or Rejected band: that outcome, source ``legacy_auto``. Before
      2.0 the band alone was final, so facilities already approved and being
      monitored stay approved. No officer is recorded for them because none
      decided.

From this revision on, every new application is ``Pending`` until an authorised
officer decides it, whatever the policy recommends.

Revision ID: 0007_policy_human_decision
Revises: 0006_borrowers_audit_models
Create Date: 2026-10-07
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from config import manager_approval_limit_pkr

revision: str = "0007_policy_human_decision"
down_revision: Union[str, Sequence[str], None] = "0006_borrowers_audit_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

DEMO_VERSION = "1.0"
DEMO_NAME = "Demo Credit Policy"
DEMO_DECLINE_MAX = 40.0
DEMO_MANUAL_REVIEW_MAX = 70.0
BAND_OF = {"Rejected": "High Risk", "Manual Review": "Medium Risk", "Approved": "Low Risk"}


def stored_calibrated_pd(explanation_json: str | None) -> float | None:
    """The calibrated probability inside a stored explanation, if readable."""
    if not explanation_json:
        return None
    try:
        value = json.loads(explanation_json).get("probability_of_default")
    except (ValueError, AttributeError):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
        return float(value)
    return None


def legacy_decision(band: str, review_decision: str | None) -> tuple[str, str | None]:
    """``(decision_status, decision_source)`` a pre-2.0 row already implied."""
    if band == "Manual Review":
        return (review_decision, "officer") if review_decision else ("Pending", None)
    return band, "legacy_auto"


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    op.create_table(
        "credit_policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decline_max_score", sa.Float(), nullable=False),
        sa.Column("manual_review_max_score", sa.Float(), nullable=False),
        sa.Column("manager_approval_limit_pkr", sa.Float(), nullable=False),
        sa.Column("decline_override_admin_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(length=64), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')", name="ck_credit_policies_status"
        ),
        sa.CheckConstraint(
            "decline_max_score >= 0 AND decline_max_score < manual_review_max_score "
            "AND manual_review_max_score <= 100",
            name="ck_credit_policies_bands",
        ),
        sa.CheckConstraint(
            "manager_approval_limit_pkr >= 0", name="ck_credit_policies_manager_limit"
        ),
    )
    op.create_index(
        "uq_credit_policies_one_active",
        "credit_policies",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    policies = sa.table(
        "credit_policies",
        sa.column("id", sa.Integer),
        sa.column("version", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("status", sa.String),
        sa.column("decline_max_score", sa.Float),
        sa.column("manual_review_max_score", sa.Float),
        sa.column("manager_approval_limit_pkr", sa.Float),
        sa.column("decline_override_admin_only", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.String),
        sa.column("activated_at", sa.DateTime(timezone=True)),
        sa.column("activated_by", sa.String),
    )
    limit = manager_approval_limit_pkr()
    policy_id = bind.execute(
        policies.insert()
        .values(
            version=DEMO_VERSION,
            name=DEMO_NAME,
            description=(
                "Default demo policy: the cut-offs ForiFlow has always used. "
                "Configurable; not validated for Pakistani SME lending."
            ),
            status="active",
            decline_max_score=DEMO_DECLINE_MAX,
            manual_review_max_score=DEMO_MANUAL_REVIEW_MAX,
            manager_approval_limit_pkr=limit,
            decline_override_admin_only=True,
            created_at=now,
            created_by="system",
            activated_at=now,
            activated_by="system",
        )
        .returning(policies.c.id)
    ).scalar_one()

    for column in (
        sa.Column("raw_pd", sa.Float(), nullable=True),
        sa.Column("calibrated_pd", sa.Float(), nullable=True),
        sa.Column("risk_band", sa.String(length=16), nullable=True),
        sa.Column("policy_id", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=True),
        sa.Column("policy_evaluation", JSON_TYPE, nullable=True),
        sa.Column("reason_codes", JSON_TYPE, nullable=True),
        sa.Column("decision_status", sa.String(length=16), nullable=True),
        sa.Column("decision_source", sa.String(length=16), nullable=True),
        sa.Column("escalated_by", sa.String(length=64), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_note", sa.Text(), nullable=True),
        sa.Column("supersedes_application_id", sa.Integer(), nullable=True),
        sa.Column("superseded_by_application_id", sa.Integer(), nullable=True),
    ):
        op.add_column("applications", column)

    # --- existing applications: record what their own columns already said ----
    applications = sa.table(
        "applications",
        sa.column("id", sa.Integer),
        sa.column("risk_band", sa.String),
        sa.column("calibrated_pd", sa.Float),
        sa.column("decision_status", sa.String),
        sa.column("decision_source", sa.String),
    )
    existing = bind.execute(
        sa.text(
            "SELECT id, decision, review_decision, shap_explanation_json "
            "FROM applications ORDER BY id"
        )
    ).mappings().all()
    counts: dict[str, int] = {}
    for row in existing:
        decision_status, source = legacy_decision(row["decision"], row["review_decision"])
        bind.execute(
            applications.update()
            .where(applications.c.id == row["id"])
            .values(
                risk_band=BAND_OF.get(row["decision"]),
                calibrated_pd=stored_calibrated_pd(row["shap_explanation_json"]),
                decision_status=decision_status,
                decision_source=source,
            )
        )
        key = f"{decision_status} ({source or 'undecided'})"
        counts[key] = counts.get(key, 0) + 1

    op.alter_column("applications", "decision_status", nullable=False)
    op.create_check_constraint(
        "ck_applications_decision_status",
        "applications",
        "decision_status IN ('Pending', 'Escalated', 'Approved', 'Rejected', 'Superseded')",
    )
    op.create_check_constraint(
        "ck_applications_decision_source",
        "applications",
        "decision_source IS NULL OR decision_source IN ('officer', 'legacy_auto')",
    )
    op.create_foreign_key(
        "fk_applications_policy_id",
        "applications",
        "credit_policies",
        ["policy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_applications_supersedes",
        "applications",
        "applications",
        ["supersedes_application_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_applications_superseded_by",
        "applications",
        "applications",
        ["superseded_by_application_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_applications_policy_id", "applications", ["policy_id"])
    op.create_index("ix_applications_decision_status", "applications", ["decision_status"])
    op.create_index(
        "ix_applications_supersedes_application_id",
        "applications",
        ["supersedes_application_id"],
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
    policy_state = {
        "version": DEMO_VERSION,
        "name": DEMO_NAME,
        "status": "active",
        "decline_max_score": DEMO_DECLINE_MAX,
        "manual_review_max_score": DEMO_MANUAL_REVIEW_MAX,
        "manager_approval_limit_pkr": limit,
        "decline_override_admin_only": True,
    }
    bind.execute(
        audit.insert(),
        [
            {
                "occurred_at": now,
                "username": "system",
                "action": "policy.created",
                "entity_type": "credit_policy",
                "entity_id": str(policy_id),
                "previous_state": None,
                "new_state": policy_state,
                "details": {"source": "seeded demo policy (migration 0007)"},
            },
            {
                "occurred_at": now,
                "username": "system",
                "action": "policy.activated",
                "entity_type": "credit_policy",
                "entity_id": str(policy_id),
                "previous_state": {"active": None},
                "new_state": {"active": DEMO_VERSION},
                "details": None,
            },
            {
                "occurred_at": now,
                "username": "system",
                "action": "migration.applied",
                "entity_type": "migration",
                "entity_id": revision,
                "previous_state": None,
                "new_state": None,
                "details": {
                    "applications_backfilled": len(existing),
                    "decision_status_recorded": counts,
                    "policy_version_assigned_to_existing_applications": None,
                    "rule": (
                        "decision status taken from each row's own band and officer "
                        "decision; no policy version and no officer invented"
                    ),
                },
            },
        ],
    )


def downgrade() -> None:
    """Remove what this revision added. Officer decisions on bands that were
    final before 2.0 (stored in review_* columns) are kept; the rest is lost."""
    op.drop_index("ix_applications_supersedes_application_id", table_name="applications")
    op.drop_index("ix_applications_decision_status", table_name="applications")
    op.drop_index("ix_applications_policy_id", table_name="applications")
    op.drop_constraint("fk_applications_superseded_by", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_supersedes", "applications", type_="foreignkey")
    op.drop_constraint("fk_applications_policy_id", "applications", type_="foreignkey")
    op.drop_constraint("ck_applications_decision_source", "applications", type_="check")
    op.drop_constraint("ck_applications_decision_status", "applications", type_="check")
    for name in (
        "superseded_by_application_id",
        "supersedes_application_id",
        "escalation_note",
        "escalated_at",
        "escalated_by",
        "decision_source",
        "decision_status",
        "reason_codes",
        "policy_evaluation",
        "policy_version",
        "policy_id",
        "risk_band",
        "calibrated_pd",
        "raw_pd",
    ):
        op.drop_column("applications", name)
    op.drop_index("uq_credit_policies_one_active", table_name="credit_policies")
    op.drop_table("credit_policies")
