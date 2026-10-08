"""SQLAlchemy engine, session management and ORM models for ForiFlow.

ForiFlow scores Pakistani SME loan applications and monitors disbursed
facilities through an Early Warning System (EWS). All monetary columns are
stored in PKR and all timestamps are timezone-aware UTC values.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from config import database_url, is_sqlite_url

DATABASE_URL: str = database_url()

# SQLite guards each connection against cross-thread use; FastAPI serves
# requests from a thread pool, so the check has to be relaxed.
_IS_SQLITE = is_sqlite_url(DATABASE_URL)
_CONNECT_ARGS: dict[str, object] = (
    {"check_same_thread": False} if _IS_SQLITE else {}
)

engine = create_engine(
    DATABASE_URL,
    connect_args=_CONNECT_ARGS,
    pool_pre_ping=not _IS_SQLITE,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base class shared by every ForiFlow ORM model."""


# Structured state: JSONB on PostgreSQL (indexable, validated), JSON on SQLite.
JsonColumn = JSON().with_variant(JSONB(), "postgresql")


class Borrower(Base):
    """The business that borrows. One borrower has many applications.

    Only what the intake form already collects is kept here. ``identifier`` is
    the owner's CNIC or the business's NTN, digits only; it is optional, and it
    is the one thing that reliably says two applications are the same business.
    A name is not an identity, so nothing is ever linked on a name alone.
    """

    __tablename__ = "borrowers"
    __table_args__ = (
        CheckConstraint(
            "(identifier IS NULL AND identifier_type IS NULL) OR "
            "(identifier IS NOT NULL AND identifier_type IS NOT NULL "
            "AND identifier_type IN ('CNIC', 'NTN'))",
            name="ck_borrowers_identifier",
        ),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_borrowers_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stable reference shown to officers, "BRW-000012". Set from ``id`` in the
    # same transaction that inserts the row, so it is never seen empty.
    public_id: Mapped[str | None] = mapped_column(String(16), nullable=True, unique=True)
    business_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_name: Mapped[str] = mapped_column(String(120), nullable=False)
    identifier_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Unique when present. NULLs never collide, so many borrowers may have none.
    identifier: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_sector: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # As stated on the most recent application.
    years_in_operation: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    applications: Mapped[list["Application"]] = relationship(
        back_populates="borrower", order_by="Application.id"
    )

    @property
    def identifier_masked(self) -> str | None:
        """The identifier with all but its last four digits hidden."""
        return mask_identifier(self.identifier)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Borrower id={self.id} public_id={self.public_id!r}>"


def mask_identifier(identifier: str | None) -> str | None:
    """Hide all but the last four characters of a CNIC or NTN."""
    if not identifier:
        return None
    return "*" * max(len(identifier) - 4, 0) + identifier[-4:]


def borrower_public_id(borrower_id: int) -> str:
    """The officer-facing reference for a borrower row."""
    return f"BRW-{borrower_id:06d}"


class ModelVersion(Base):
    """One scoring model that has served decisions from this database.

    A row is added the first time a model scores here. ``artifact_sha256`` is
    the fingerprint of the files (or, for the fallback formula, of its weights)
    that actually produced the numbers, so a swapped file under an unchanged
    version string still shows up as a different model.
    """

    __tablename__ = "model_versions"
    __table_args__ = (
        Index(
            "uq_model_versions_version_artifact", "version", "artifact_sha256", unique=True
        ),
        CheckConstraint("engine IN ('ml', 'surrogate')", name="ck_model_versions_engine"),
        CheckConstraint("status IN ('active', 'retired')", name="ck_model_versions_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(120), nullable=False)
    # 'ml': the trained ensemble. 'surrogate': the hand-weighted fallback formula.
    engine: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    training_dataset: Mapped[str | None] = mapped_column(String(80), nullable=True)
    feature_set: Mapped[list | None] = mapped_column(JsonColumn, nullable=True)
    feature_set_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trained_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    # 'active': the model this service is scoring with now. One row at a time.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Why the fallback formula is serving, when it is: 'pinned',
    # 'artifacts_missing' or 'load_failed'. NULL for the trained ensemble.
    fallback_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    @property
    def is_active(self) -> bool:
        """True for the model the service is scoring with now."""
        return self.status == "active"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ModelVersion id={self.id} version={self.version!r} status={self.status!r}>"


class CreditPolicy(Base):
    """One version of the credit policy: the cut-offs and authority limits.

    The model produces a score; the policy says what the score recommends and
    who may approve what. A version's figures are never edited: a change is a
    new version. One version is active at a time (a partial unique index), and
    every application stores the version it was assessed under, so retiring a
    policy does not change what any past application was recommended.

    The shipped version is a demo policy. Its cut-offs are round numbers, not
    thresholds validated for Pakistani SME lending.
    """

    __tablename__ = "credit_policies"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_credit_policies_status"),
        CheckConstraint(
            "decline_max_score >= 0 AND decline_max_score < manual_review_max_score "
            "AND manual_review_max_score <= 100",
            name="ck_credit_policies_bands",
        ),
        CheckConstraint(
            "manager_approval_limit_pkr >= 0", name="ck_credit_policies_manager_limit"
        ),
        Index(
            "uq_credit_policies_one_active",
            "status",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'draft': created, never used. 'active': scoring uses it. 'retired': was active.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # Score at or below this: recommend Decline (high risk).
    decline_max_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Score above decline_max and at or below this: recommend Manual Review
    # (medium risk). Above it: recommend Approve (low risk).
    manual_review_max_score: Mapped[float] = mapped_column(Float, nullable=False)
    # Largest facility a manager may approve alone; above it an admin approves.
    manager_approval_limit_pkr: Mapped[float] = mapped_column(Float, nullable=False)
    # True: only an admin may approve against a Decline recommendation.
    decline_override_admin_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        """True for the version new assessments are made under."""
        return self.status == "active"

    @property
    def approve_above_score(self) -> float:
        """Scores above this are recommended for approval."""
        return self.manual_review_max_score

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<CreditPolicy id={self.id} version={self.version!r} status={self.status!r}>"


class AuditLog(Base):
    """One thing someone did, written once and never changed.

    Rows are only ever inserted. The ORM refuses to update or delete them
    (listeners below) and so does the database itself (triggers created with
    the table), so a bulk statement or a hand-typed ``DELETE`` fails as well.
    A wrong entry is corrected by writing another entry.

    ``user_id`` is deliberately not a foreign key: the record must outlive the
    account, and it carries the username and role as they were at the time.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 'system' for startup and migration events; the typed name on a failed login.
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_state: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    new_state: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    details: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<AuditLog id={self.id} action={self.action!r} by={self.username!r}>"


class AuditLogImmutable(RuntimeError):
    """Raised when code tries to change or remove an audit record."""


def _refuse_audit_change(mapper, connection, target) -> None:
    raise AuditLogImmutable(
        "audit_logs is append-only: write a new entry instead of changing one."
    )


event.listen(AuditLog, "before_update", _refuse_audit_change)
event.listen(AuditLog, "before_delete", _refuse_audit_change)

# The same rule inside the database, for statements that bypass the ORM.
# Migration 0006 runs AUDIT_APPEND_ONLY_POSTGRES; ``create_all`` (SQLite, used
# by the tests and the laptop fallback) runs the SQLite pair through the hooks.
AUDIT_APPEND_ONLY_POSTGRES: tuple[str, ...] = (
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
AUDIT_APPEND_ONLY_SQLITE: tuple[str, ...] = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_update BEFORE UPDATE ON audit_logs
    BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_logs_no_delete BEFORE DELETE ON audit_logs
    BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END
    """,
)
for _statement in AUDIT_APPEND_ONLY_SQLITE:
    event.listen(
        AuditLog.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite")
    )
for _statement in AUDIT_APPEND_ONLY_POSTGRES:
    event.listen(
        AuditLog.__table__,
        "after_create",
        DDL(_statement).execute_if(dialect="postgresql"),
    )


class Application(Base):
    """A scored SME credit application.

    Holds the raw applicant features, the model output (``risk_score`` and
    ``decision``) and the serialised SHAP explanation so that a credit officer
    can retrieve the stored rationale later for an SBP-oriented review.
    ForiFlow is not SBP-certified.
    """

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(
            "review_decision IS NULL OR review_decision IN ('Approved', 'Rejected')",
            name="ck_applications_review_decision",
        ),
        CheckConstraint(
            "decision_status IN ('Pending', 'Escalated', 'Approved', 'Rejected', 'Superseded')",
            name="ck_applications_decision_status",
        ),
        CheckConstraint(
            "decision_source IS NULL OR decision_source IN ('officer', 'legacy_auto')",
            name="ck_applications_decision_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The business this application belongs to. RESTRICT: a borrower with
    # applications cannot be removed, only marked inactive.
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("borrowers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    applicant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    business_name: Mapped[str] = mapped_column(String(160), nullable=False)

    loan_amount_pkr: Mapped[float] = mapped_column(Float, nullable=False)
    tenure_months: Mapped[int] = mapped_column(Integer, nullable=False)

    monthly_digital_payments: Mapped[float] = mapped_column(Float, nullable=False)
    payment_history_score: Mapped[float] = mapped_column(Float, nullable=False)
    inventory_turnover: Mapped[float] = mapped_column(Float, nullable=False)
    order_consistency: Mapped[float] = mapped_column(Float, nullable=False)
    existing_debt_pkr: Mapped[float] = mapped_column(Float, nullable=False)
    cash_flow_proxy: Mapped[float] = mapped_column(Float, nullable=False)
    years_in_operation: Mapped[float] = mapped_column(Float, nullable=False)
    num_employees: Mapped[int] = mapped_column(Integer, nullable=False)

    risk_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    shap_explanation_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What produced ``risk_score``, fixed at scoring time. ``scoring_engine`` is
    # 'ml' (trained ensemble) or 'surrogate' (hand-weighted fallback formula).
    # NULL only where a row scored before migration 0006 did not record it.
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    scoring_engine: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    # --- model assessment, fixed at scoring time ---
    # The model's own probability of default (trained on balanced data, so it
    # ranks well but runs high) and the calibrated one shown to officers.
    # NULL for the surrogate engine and for rows scored before migration 0007.
    raw_pd: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_pd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 'High Risk' / 'Medium Risk' / 'Low Risk' under the policy below.
    risk_band: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- policy recommendation, fixed at scoring time ---
    # ``decision`` above holds the recommendation in its original vocabulary
    # ('Approved' = recommend approve). It is never a final decision.
    # NULL policy columns mean "scored before policies were recorded".
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_policies.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_evaluation: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    reason_codes: Mapped[list | None] = mapped_column(JsonColumn, nullable=True)

    # --- human decision ---
    # 'Pending' until an authorised officer decides; 'Escalated' once a
    # manager has passed it to an admin; 'Superseded' when it was re-scored
    # before any decision. ``review_*`` below hold the officer's decision.
    decision_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="Pending", index=True
    )
    # 'officer': a named officer decided. 'legacy_auto': decided by the score
    # band alone under the rule in force before 2.0, with no officer recorded.
    decision_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    escalated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The earlier assessment this one replaced. That row is kept, unchanged.
    supersedes_application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Set on the replaced row, so it can be followed forward as well as back.
    superseded_by_application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), nullable=True
    )

    # Line of business, for portfolio concentration. NULL before migration 0004.
    business_sector: Mapped[str | None] = mapped_column(
        String(40), nullable=True, index=True
    )

    # Where the turnover figures came from: a parsed statement summary, or NULL
    # when the officer typed them. Never the raw transactions.
    turnover_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Borrower's mobile number for payment reminders. Optional.
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Who ran the assessment. NULL only for rows scored before migration 0003.
    scored_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # The officer's final call on a Manual Review application. ``decision``
    # keeps the model's band unchanged, so the file shows both.
    review_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    # ``borrower`` here is the business; on Alert and EWSTracking the attribute
    # of the same name is the application (kept from before borrowers existed).
    # selectin, not joined: a JOIN would end up inside ``SELECT … FOR UPDATE``
    # when a review or an alert locks its row, which PostgreSQL refuses.
    borrower: Mapped["Borrower"] = relationship(
        back_populates="applications", lazy="selectin"
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="borrower", cascade="all, delete-orphan", foreign_keys="Alert.borrower_id"
    )
    ews_records: Mapped[list["EWSTracking"]] = relationship(
        back_populates="borrower",
        cascade="all, delete-orphan",
        foreign_keys="EWSTracking.borrower_id",
    )

    @property
    def authority_view(self) -> dict:
        """Who may approve this application now, and the limit that applies.

        Read from the policy snapshot stored at scoring time. An application
        scored before policies were recorded has none, so the active policy
        governs it; that is the policy an officer deciding it today works under.
        """
        from sqlalchemy import select
        from sqlalchemy.orm import object_session

        from schemas import Decision
        from services.policy_rules import (
            DEMO_MANAGER_APPROVAL_LIMIT_PKR,
            approval_authority,
        )

        snapshot = (self.policy_evaluation or {}).get("authority_rule")
        if snapshot is None:
            session = object_session(self)
            active = (
                session.scalar(select(CreditPolicy).where(CreditPolicy.status == "active"))
                if session is not None
                else None
            )
            snapshot = {
                "manager_approval_limit_pkr": (
                    active.manager_approval_limit_pkr
                    if active is not None
                    else DEMO_MANAGER_APPROVAL_LIMIT_PKR
                ),
                "decline_override_admin_only": (
                    active.decline_override_admin_only if active is not None else True
                ),
            }
        role, reason = approval_authority(
            loan_amount_pkr=self.loan_amount_pkr,
            recommendation=Decision(self.decision),
            manager_approval_limit_pkr=float(snapshot["manager_approval_limit_pkr"]),
            decline_override_admin_only=bool(snapshot["decline_override_admin_only"]),
            escalated=self.decision_status == "Escalated",
        )
        return {
            "approve_requires": role,
            "reason": reason,
            "manager_approval_limit_pkr": float(snapshot["manager_approval_limit_pkr"]),
            "decline_override_admin_only": bool(snapshot["decline_override_admin_only"]),
        }

    @property
    def borrower_public_id(self) -> str | None:
        """The owning borrower's reference, e.g. ``BRW-000012``."""
        return self.borrower.public_id if self.borrower is not None else None

    @property
    def turnover_evidence(self) -> dict | None:
        """The stored statement summary, or ``None`` if the turnover was typed."""
        if not self.turnover_evidence_json:
            return None
        try:
            return json.loads(self.turnover_evidence_json)
        except ValueError:
            return None

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Application id={self.id} business={self.business_name!r} "
            f"score={self.risk_score} decision={self.decision!r}>"
        )


# Alert lifecycle. Open, Acknowledged and Action Required are open; Resolved
# and Dismissed are closed. Alerts from before 2.1 were Active / In Review and
# were renamed by migration 0008 (Active -> Open, In Review -> Acknowledged).
ALERT_OPEN_STATUSES: tuple[str, ...] = ("Open", "Acknowledged", "Action Required")
ALERT_CLOSED_STATUSES: tuple[str, ...] = ("Resolved", "Dismissed")


class Alert(Base):
    """An EWS alert on one approved facility (``borrower_id`` is the application).

    One alert is open per facility at a time (a partial unique index); a later
    observation that still breaches updates it instead of opening another, and
    its severity only rises while it is open. Alerts are raised at the WARNING
    and CRITICAL states; a WATCH facility is listed on the dashboard, not alerted.
    ``severity``, ``reason_codes`` and ``evidence`` say why it fired and are set
    by the deterministic EWS engine (``services.ews_engine``). They are NULL on
    alerts raised before 2.1, which recorded only a score drop.

    ``estimated_days_to_default`` is a heuristic runway kept for compatibility;
    it plays no part in raising an alert.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_status IN ('Open', 'Acknowledged', 'Action Required', 'Resolved', 'Dismissed')",
            name="ck_alerts_status",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN ('WARNING', 'CRITICAL')",
            name="ck_alerts_severity",
        ),
        Index(
            "uq_alerts_one_open_per_facility",
            "borrower_id",
            unique=True,
            postgresql_where=text("alert_status IN ('Open', 'Acknowledged', 'Action Required')"),
            sqlite_where=text("alert_status IN ('Open', 'Acknowledged', 'Action Required')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )

    baseline_score: Mapped[float] = mapped_column(Float, nullable=False)
    current_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_drop: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_days_to_default: Mapped[int] = mapped_column(Integer, nullable=False)

    alert_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Open", index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Who owns the follow-up, and who closed it and why (Resolved or Dismissed).
    assigned_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- 2.1: why it fired (NULL on legacy alerts) ---
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    reason_codes: Mapped[list | None] = mapped_column(JsonColumn, nullable=True)
    evidence: Mapped[list | None] = mapped_column(JsonColumn, nullable=True)
    previous_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommended_actions: Mapped[list | None] = mapped_column(JsonColumn, nullable=True)
    # The observation that raised it, and the latest one that updated it.
    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ews_tracking.id", ondelete="SET NULL"), nullable=True
    )
    last_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ews_tracking.id", ondelete="SET NULL"), nullable=True
    )
    # --- 2.1: lifecycle ---
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    action_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    borrower: Mapped["Application"] = relationship(back_populates="alerts")

    @property
    def business_name(self) -> str:
        """The borrower's business, so an alert is readable without a lookup."""
        return self.borrower.business_name

    @property
    def is_open(self) -> bool:
        """Still needs attention: Open, Acknowledged or Action Required."""
        return self.alert_status in ALERT_OPEN_STATUSES

    @property
    def is_overdue(self) -> bool:
        """An open alert whose action due date has passed."""
        return (
            self.is_open
            and self.action_due_date is not None
            and self.action_due_date < utcnow().date()
        )

    @property
    def is_legacy(self) -> bool:
        """Raised before 2.1, so it carries no severity, reasons or evidence."""
        return self.severity is None

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Alert id={self.id} borrower_id={self.borrower_id} "
            f"drop={self.score_drop} status={self.alert_status!r}>"
        )


# Where an observation's score came from. Never a model score unless it is one.
SCORE_SOURCES: tuple[str, ...] = (
    "ews_rule_adjusted",  # origination score minus the EWS rule penalties
    "officer_override",  # typed by a manager or admin, with a reason
    "latest_foriflow_assessment",  # reserved: not produced by this release
    "origination_assessment",  # the baseline point only
    "legacy_unknown",  # recorded before 2.1; not stored then
)


class EWSTracking(Base):
    """One monthly monitoring observation of an approved facility.

    ``borrower_id`` is the application (facility), as it has been since 1.0.
    Observations are history: a recorded month is never edited. A correction
    adds a new row and marks the earlier one ``superseded``, linking the two;
    only one ``active`` row may exist per facility and month (a partial unique
    index). Superseded rows are kept and shown, never counted.

    ``monthly_score`` is the monitored score. ``score_source`` says where it
    came from: the EWS rules applied to the origination score, an officer's
    override (with ``override_reason``), or unknown for rows recorded before
    2.1. It is never a fresh model score.
    """

    __tablename__ = "ews_tracking"
    __table_args__ = (
        CheckConstraint(
            "record_status IN ('active', 'superseded')", name="ck_ews_tracking_record_status"
        ),
        CheckConstraint(
            "score_source IN ('ews_rule_adjusted', 'officer_override', "
            "'latest_foriflow_assessment', 'origination_assessment', 'legacy_unknown')",
            name="ck_ews_tracking_score_source",
        ),
        CheckConstraint(
            "score_source <> 'officer_override' OR override_reason IS NOT NULL",
            name="ck_ews_tracking_override_reason",
        ),
        Index(
            "uq_ews_tracking_active_month",
            "borrower_id",
            "month_number",
            unique=True,
            postgresql_where=text("record_status = 'active'"),
            sqlite_where=text("record_status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # The reporting period: months since disbursement.
    month_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    installment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    bureau_balance: Mapped[float] = mapped_column(Float, nullable=False)
    pos_cash_balance: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_score: Mapped[float] = mapped_column(Float, nullable=False)
    data_source_primary: Mapped[str] = mapped_column(String(32), nullable=False)
    # What the borrower paid this month. NULL when the officer did not record it.
    amount_paid_pkr: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- 2.1 (NULL on rows recorded before it, where noted) ---
    observation_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Days past due when known; must fit the installment status bucket.
    days_late: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ews_rule_adjusted"
    )
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The rule-derived score an override replaced, for the record.
    rule_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    record_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    supersedes_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ews_tracking.id", ondelete="RESTRICT"), nullable=True
    )
    superseded_by_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ews_tracking.id", ondelete="RESTRICT"), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the EWS concluded when this row was recorded: state, trend, signals.
    assessment: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    borrower: Mapped["Application"] = relationship(back_populates="ews_records")

    @property
    def is_legacy(self) -> bool:
        """Recorded before 2.1: no date, author or score provenance on file."""
        return self.score_source == "legacy_unknown"

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<EWSTracking id={self.id} borrower_id={self.borrower_id} "
            f"month={self.month_number} score={self.monthly_score}>"
        )


class User(Base):
    """An on-premise officer account: ``admin``, ``manager`` or ``analyst``."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'manager', 'analyst')", name="ck_users_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"


def _run_alembic_upgrade() -> None:
    """Apply Alembic migrations to the configured non-SQLite database."""
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    cfg = Config(str(ini_path))
    # ConfigParser interpolates `%`; URL-encoded passwords must be escaped.
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def init_db() -> None:
    """Create tables (SQLite) or run Alembic (PostgreSQL).

    ``create_all`` is limited to SQLite so tests and a laptop-only fallback
    keep working. Postgres schema is owned by Alembic and must not be
    created ad hoc, or the migration history would drift from the live DB.
    """
    if _IS_SQLITE:
        Base.metadata.create_all(bind=engine)
        return
    _run_alembic_upgrade()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
