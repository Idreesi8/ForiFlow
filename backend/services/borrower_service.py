"""Borrowers: the businesses behind applications, and their history.

One borrower has many applications; each application has its own score, model
version, monthly monitoring and alerts. Two applications are filed under the
same borrower only when an officer names the borrower, or when both carry the
same CNIC or NTN. Names are never matched: two shops can share one.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from models.database import (
    Application,
    Borrower,
    User,
    borrower_public_id,
    mask_identifier,
    utcnow,
)
from schemas import (
    AlertResponse,
    AlertStatus,
    ApplicationSummary,
    BorrowerApplicationHistory,
    BorrowerHistory,
    BorrowerHistorySummary,
    BorrowerResponse,
    Decision,
    EWSTrackingResponse,
    SMEApplicant,
)
from services import audit_service
from services.audit_service import Action, AuditContext

# What an audit entry keeps of a borrower. The identifier is masked.
_STATE_FIELDS = (
    "public_id",
    "business_name",
    "owner_name",
    "identifier_type",
    "contact_phone",
    "business_sector",
    "years_in_operation",
    "status",
)


def borrower_state(borrower: Borrower) -> dict:
    """A borrower as it is written to the audit trail."""
    state = {name: getattr(borrower, name) for name in _STATE_FIELDS}
    state["identifier_masked"] = mask_identifier(borrower.identifier)
    return state


def get_by_ref(db: Session, ref: str, *, for_update: bool = False) -> Borrower:
    """Find a borrower by ``BRW-…`` reference or numeric id, or raise ``404``."""
    statement = select(Borrower)
    if ref.upper().startswith("BRW-"):
        statement = statement.where(Borrower.public_id == ref.upper())
    elif ref.isdigit():
        statement = statement.where(Borrower.id == int(ref))
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Borrower {ref!r} was not found."
        )
    if for_update:
        statement = statement.with_for_update()
    borrower = db.scalar(statement)
    if borrower is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Borrower {ref!r} was not found."
        )
    return borrower


def find_by_identifier(db: Session, identifier: str) -> Borrower | None:
    """The borrower holding this CNIC or NTN, if any."""
    return db.scalar(select(Borrower).where(Borrower.identifier == identifier))


def _identifier_taken(existing: Borrower) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"That identifier is already on file for borrower {existing.public_id} "
            f"({existing.business_name}). File the application under it instead."
        ),
    )


def create(
    db: Session,
    *,
    business_name: str,
    owner_name: str,
    identifier_type: str | None = None,
    identifier: str | None = None,
    contact_phone: str | None = None,
    business_sector: str | None = None,
    years_in_operation: float | None = None,
    actor: User | None,
    context: AuditContext | None,
    source: str,
) -> Borrower:
    """Insert a borrower, give it its reference and audit it. Does not commit."""
    if identifier is not None:
        existing = find_by_identifier(db, identifier)
        if existing is not None:
            raise _identifier_taken(existing)
    borrower = Borrower(
        business_name=business_name,
        owner_name=owner_name,
        identifier_type=identifier_type,
        identifier=identifier,
        contact_phone=contact_phone,
        business_sector=business_sector,
        years_in_operation=years_in_operation,
        status="active",
    )
    try:
        with db.begin_nested():
            db.add(borrower)
            db.flush()
            borrower.public_id = borrower_public_id(borrower.id)
            db.flush()
    except IntegrityError:
        # Another officer registered the same identifier a moment earlier.
        existing = find_by_identifier(db, identifier) if identifier else None
        if existing is None:
            raise
        raise _identifier_taken(existing) from None
    audit_service.record(
        db,
        action=Action.BORROWER_CREATED,
        entity_type="borrower",
        entity_id=borrower.id,
        actor=actor,
        new=borrower_state(borrower),
        details={"source": source},
        context=context,
    )
    return borrower


def apply_changes(
    db: Session,
    borrower: Borrower,
    changes: dict,
    *,
    actor: User | None,
    context: AuditContext | None,
    source: str,
) -> bool:
    """Set the given fields, auditing the before and after. Does not commit.

    Returns ``False`` (and writes nothing) when no value actually changes.
    """
    changed = {
        name: value for name, value in changes.items() if getattr(borrower, name) != value
    }
    if not changed:
        return False
    new_identifier = changed.get("identifier")
    if new_identifier is not None:
        existing = find_by_identifier(db, new_identifier)
        if existing is not None and existing.id != borrower.id:
            raise _identifier_taken(existing)
    previous = borrower_state(borrower)
    for name, value in changed.items():
        setattr(borrower, name, value)
    borrower.updated_at = utcnow()
    db.flush()
    after = borrower_state(borrower)
    audit_service.record(
        db,
        action=Action.BORROWER_UPDATED,
        entity_type="borrower",
        entity_id=borrower.id,
        actor=actor,
        previous={key: previous[key] for key in after if previous[key] != after[key]},
        new={key: after[key] for key in after if previous[key] != after[key]},
        details={"source": source},
        context=context,
    )
    return True


def resolve_for_application(
    db: Session, applicant: SMEApplicant, *, actor: User, context: AuditContext | None
) -> tuple[Borrower, bool]:
    """The borrower a new application is filed under, and whether it is new.

    1. A ``borrower_public_id`` names the borrower outright.
    2. Otherwise a CNIC or NTN finds the borrower that already holds it.
    3. Otherwise a new borrower is opened from the application's own details.

    An existing borrower takes the application's newer contact number, sector
    and years in operation; its names are left alone.
    """
    identifier = applicant.borrower_identifier
    identifier_type = (
        applicant.borrower_identifier_type.value if applicant.borrower_identifier_type else None
    )
    sector = applicant.business_sector.value if applicant.business_sector else None

    borrower: Borrower | None = None
    if applicant.borrower_public_id is not None:
        borrower = get_by_ref(db, applicant.borrower_public_id, for_update=True)
        if identifier and borrower.identifier and borrower.identifier != identifier:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Borrower {borrower.public_id} is on file with a different "
                    f"{borrower.identifier_type}. Check which business this is."
                ),
            )
    elif identifier is not None:
        borrower = find_by_identifier(db, identifier)

    if borrower is None:
        created = create(
            db,
            business_name=applicant.business_name,
            owner_name=applicant.applicant_name,
            identifier_type=identifier_type,
            identifier=identifier,
            contact_phone=applicant.contact_phone,
            business_sector=sector,
            years_in_operation=applicant.years_in_operation,
            actor=actor,
            context=context,
            source="application",
        )
        return created, True

    if borrower.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Borrower {borrower.public_id} is marked inactive. A manager must "
                "reactivate it before a new application is opened."
            ),
        )
    changes: dict = {"years_in_operation": float(applicant.years_in_operation)}
    if applicant.contact_phone:
        changes["contact_phone"] = applicant.contact_phone
    if sector:
        changes["business_sector"] = sector
    if identifier and not borrower.identifier:
        changes["identifier"] = identifier
        changes["identifier_type"] = identifier_type
    apply_changes(db, borrower, changes, actor=actor, context=context, source="application")
    return borrower, False


def history(db: Session, borrower: Borrower) -> BorrowerHistory:
    """Every application of a borrower with its score, model, months and alerts."""
    applications = db.scalars(
        select(Application)
        .where(Application.borrower_id == borrower.id)
        .options(selectinload(Application.ews_records), selectinload(Application.alerts))
        .order_by(Application.created_at, Application.id)
    ).all()

    rows: list[BorrowerApplicationHistory] = []
    for application in applications:
        summary = ApplicationSummary.model_validate(application)
        rows.append(
            BorrowerApplicationHistory(
                application_id=application.id,
                created_at=application.created_at,
                loan_amount_pkr=application.loan_amount_pkr,
                tenure_months=application.tenure_months,
                risk_score=application.risk_score,
                decision=summary.decision,
                recommendation=summary.recommendation,
                policy_version=application.policy_version,
                decision_status=summary.decision_status,
                final_decision=summary.final_decision,
                review_decision=summary.review_decision,
                reviewed_by=application.reviewed_by,
                reviewed_at=application.reviewed_at,
                scored_by=application.scored_by,
                model_version=application.model_version,
                scoring_engine=application.scoring_engine,
                monitoring=[
                    EWSTrackingResponse.model_validate(record)
                    for record in sorted(application.ews_records, key=lambda r: r.month_number)
                ],
                alerts=[
                    AlertResponse.model_validate(alert)
                    for alert in sorted(application.alerts, key=lambda a: a.triggered_at)
                ],
            )
        )

    scores = [row.risk_score for row in rows]
    alerts = [alert for row in rows for alert in row.alerts]
    return BorrowerHistory(
        borrower=BorrowerResponse.model_validate(borrower),
        summary=BorrowerHistorySummary(
            applications=len(rows),
            first_application_at=rows[0].created_at if rows else None,
            latest_application_at=rows[-1].created_at if rows else None,
            latest_score=scores[-1] if scores else None,
            lowest_score=min(scores) if scores else None,
            highest_score=max(scores) if scores else None,
            approved_facilities=sum(
                1 for row in rows if row.final_decision is Decision.APPROVED
            ),
            monitored_months=sum(len(row.monitoring) for row in rows),
            open_alerts=sum(
                1 for alert in alerts if alert.alert_status is not AlertStatus.RESOLVED
            ),
            total_alerts=len(alerts),
            # In order of first use; "unrecorded" marks rows scored before 1.10.
            model_versions_used=list(
                dict.fromkeys(row.model_version or "unrecorded" for row in rows)
            ),
            scoring_engines_used=list(
                dict.fromkeys(row.scoring_engine or "unrecorded" for row in rows)
            ),
            policy_versions_used=list(
                dict.fromkeys(row.policy_version or "unrecorded" for row in rows)
            ),
        ),
        applications=rows,
    )
