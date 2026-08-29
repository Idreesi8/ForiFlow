"""SQLAlchemy engine, session management and ORM models for ForiFlow.

ForiFlow scores Pakistani SME loan applications and monitors disbursed
facilities through an Early Warning System (EWS). All monetary columns are
stored in PKR and all timestamps are timezone-aware UTC values.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
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


class Application(Base):
    """A scored SME credit application.

    Holds the raw applicant features, the model output (``risk_score`` and
    ``decision``) and the serialised SHAP explanation so that a credit officer
    can retrieve the stored rationale later for an SBP-oriented review.
    ForiFlow is not SBP-certified.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="borrower", cascade="all, delete-orphan"
    )
    ews_records: Mapped[list["EWSTracking"]] = relationship(
        back_populates="borrower", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Application id={self.id} business={self.business_name!r} "
            f"score={self.risk_score} decision={self.decision!r}>"
        )


class Alert(Base):
    """An EWS alert raised when a borrower's score deteriorates materially.

    ``score_drop`` is expressed in score points relative to the borrower's
    baseline (origination) score, and ``estimated_days_to_default`` is the
    model's runway estimate used to prioritise recovery outreach.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )

    baseline_score: Mapped[float] = mapped_column(Float, nullable=False)
    current_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_drop: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_days_to_default: Mapped[int] = mapped_column(Integer, nullable=False)

    alert_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="Active", index=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    borrower: Mapped["Application"] = relationship(back_populates="alerts")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<Alert id={self.id} borrower_id={self.borrower_id} "
            f"drop={self.score_drop} status={self.alert_status!r}>"
        )


class EWSTracking(Base):
    """One monthly post-disbursement observation for a borrower.

    Combines an officer-entered bureau balance (``bureau_balance``), point-of-sale
    settlement cash (``pos_cash_balance``) and repayment behaviour into the
    recomputed ``monthly_score``. ``data_source_primary`` is an officer-selected
    label (``ECIB`` means a typed extract, not a live pull).
    """

    __tablename__ = "ews_tracking"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    borrower_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )

    month_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    installment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    bureau_balance: Mapped[float] = mapped_column(Float, nullable=False)
    pos_cash_balance: Mapped[float] = mapped_column(Float, nullable=False)
    monthly_score: Mapped[float] = mapped_column(Float, nullable=False)
    data_source_primary: Mapped[str] = mapped_column(String(32), nullable=False)

    borrower: Mapped["Application"] = relationship(back_populates="ews_records")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<EWSTracking id={self.id} borrower_id={self.borrower_id} "
            f"month={self.month_number} score={self.monthly_score}>"
        )


class User(Base):
    """An on-premise officer account. Roles are ``admin`` or ``analyst``."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'analyst')", name="ck_users_role"),
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
