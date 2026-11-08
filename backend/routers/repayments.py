"""Officer-recorded repayment calendars. No live payments or credit decisions."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from models.database import User, get_db
from repayment_schemas import ReceiptCreate, ReceiptVoid, ScheduleCreate
from services import repayments
from services.audit_service import Audit
from services.auth_service import get_current_user, require_manager

router = APIRouter(prefix='/repayments', tags=['Repayment calendar'], dependencies=[Depends(get_current_user)])
Db = Annotated[Session, Depends(get_db)]
Officer = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]


@router.get('/{application_id}')
def read_calendar(application_id: int, db: Db,
                  schedule_id: Annotated[int | None, Query(ge=1)] = None,
                  receipt_offset: Annotated[int, Query(ge=0, le=1000)] = 0):
    return repayments.report(db, application_id, schedule_id=schedule_id, receipt_offset=receipt_offset)


@router.post('/{application_id}/schedule')
def record_schedule(application_id: int, body: ScheduleCreate, db: Db, actor: Manager, audit: Audit):
    return repayments.save_schedule(db, application_id, body, actor, audit)


@router.post('/{application_id}/receipts')
def record_receipt(application_id: int, body: ReceiptCreate, db: Db, actor: Officer, audit: Audit):
    return repayments.save_receipt(db, application_id, body, actor, audit)


@router.post('/{application_id}/receipts/{receipt_id}/void')
def void_receipt(application_id: int, receipt_id: int, body: ReceiptVoid, db: Db, actor: Manager, audit: Audit):
    return repayments.void_receipt(db, application_id, receipt_id, body, actor, audit)
