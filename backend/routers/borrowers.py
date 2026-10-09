"""Borrowers: the business behind one or more applications, and its history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models.database import Borrower, User, get_db, mask_phone
from schemas import (
    BorrowerCreate,
    BorrowerHistory,
    BorrowerResponse,
    BorrowerUpdate,
)
from services import borrower_service
from services.audit_service import Audit
from services.auth_service import get_current_user, require_manager

router = APIRouter(
    prefix="/borrowers",
    tags=["Borrowers"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Officer = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]


@router.get("", response_model=list[BorrowerResponse], summary="List or search borrowers")
async def list_borrowers(
    db: DbSession,
    q: Annotated[
        str | None,
        Query(
            max_length=160,
            description="Part of the business or owner name, or a BRW- reference.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BorrowerResponse]:
    """Borrowers, newest first.

    Searching is by name or reference only. A CNIC or NTN is never accepted in
    the URL, where it would end up in access logs; an identifier finds its
    borrower when it is submitted with an application or a new borrower.
    """
    statement = select(Borrower).order_by(Borrower.id.desc())
    if q:
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(
                Borrower.business_name.ilike(needle),
                Borrower.owner_name.ilike(needle),
                Borrower.public_id.ilike(needle),
            )
        )
    borrowers = db.scalars(statement.offset(offset).limit(limit)).all()
    # 2.3: phone numbers are masked in the list; GET /borrowers/{ref} has them.
    return [
        BorrowerResponse.model_validate(borrower).model_copy(
            update={"contact_phone": mask_phone(borrower.contact_phone)}
        )
        for borrower in borrowers
    ]


@router.post(
    "",
    response_model=BorrowerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a borrower record",
)
async def create_borrower(
    body: BorrowerCreate, db: DbSession, officer: Officer, audit: Audit
) -> BorrowerResponse:
    """Register a business before its first application.

    Scoring an application without naming a borrower opens one automatically,
    so this is only needed to put a borrower on file ahead of time. An
    identifier already on file returns ``409`` naming the existing borrower.
    """
    borrower = borrower_service.create(
        db,
        business_name=body.business_name,
        owner_name=body.owner_name,
        identifier_type=(
            body.borrower_identifier_type.value if body.borrower_identifier_type else None
        ),
        identifier=body.borrower_identifier,
        contact_phone=body.contact_phone,
        business_sector=body.business_sector.value if body.business_sector else None,
        years_in_operation=body.years_in_operation,
        actor=officer,
        context=audit,
        source="borrowers_api",
    )
    db.commit()
    db.refresh(borrower)
    return BorrowerResponse.model_validate(borrower)


@router.get("/{borrower_ref}", response_model=BorrowerResponse, summary="Fetch one borrower")
async def get_borrower(borrower_ref: str, db: DbSession) -> BorrowerResponse:
    """A borrower by ``BRW-…`` reference or numeric id."""
    return BorrowerResponse.model_validate(borrower_service.get_by_ref(db, borrower_ref))


@router.patch(
    "/{borrower_ref}",
    response_model=BorrowerResponse,
    summary="Correct a borrower's details (manager or admin)",
)
async def update_borrower(
    borrower_ref: str, body: BorrowerUpdate, db: DbSession, officer: Manager, audit: Audit
) -> BorrowerResponse:
    """Change only the fields sent. The audit entry keeps the old and new values.

    Applications keep the names and figures they were scored with; this edits
    the borrower record, not its history.
    """
    borrower = borrower_service.get_by_ref(db, borrower_ref, for_update=True)
    sent = body.model_dump(exclude_unset=True)
    changes: dict = {}
    for name in ("business_name", "owner_name", "contact_phone", "years_in_operation"):
        if sent.get(name) is not None:
            changes[name] = sent[name]
    if body.business_sector is not None:
        changes["business_sector"] = body.business_sector.value
    if body.status is not None:
        changes["status"] = body.status.value
    if body.borrower_identifier is not None and body.borrower_identifier_type is not None:
        changes["identifier"] = body.borrower_identifier
        changes["identifier_type"] = body.borrower_identifier_type.value
    borrower_service.apply_changes(
        db, borrower, changes, actor=officer, context=audit, source="borrowers_api"
    )
    db.commit()
    db.refresh(borrower)
    return BorrowerResponse.model_validate(borrower)


@router.get(
    "/{borrower_ref}/history",
    response_model=BorrowerHistory,
    summary="Every application, score, model version, monitored month and alert",
)
async def borrower_history(borrower_ref: str, db: DbSession) -> BorrowerHistory:
    """The borrower's full record, oldest application first.

    Each application carries the score and band it was given, the officer's
    decision, the model version and engine that scored it, its monthly
    monitoring and its alerts. ``GET /ews/borrowers/{id}/history`` is a
    different, older route: its id is an application id and it returns that one
    facility's months.
    """
    return borrower_service.history(db, borrower_service.get_by_ref(db, borrower_ref))
