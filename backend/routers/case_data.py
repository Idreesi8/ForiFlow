"""Reference register only; not a consent signature or data access service."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from case_data_schemas import RecordCreate, WithdrawRecord
from models.database import User, get_db
from services import case_data
from services.audit_service import Audit
from services.auth_service import get_current_user, require_manager

router = APIRouter(prefix='/case-data', tags=['Source and permission evidence'], dependencies=[Depends(get_current_user)])
Db = Annotated[Session, Depends(get_db)]
Officer = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]


@router.get('/{application_id}')
def read(application_id: int, db: Db, offset: Annotated[int, Query(ge=0, le=500)] = 0):
    return case_data.report(db, application_id, offset=offset)


@router.get('/{application_id}/history/{stream_key}')
def history(application_id: int, stream_key: UUID, db: Db, offset: Annotated[int, Query(ge=0, le=500)] = 0):
    return case_data.history(db, application_id, stream_key, offset=offset)


@router.post('/{application_id}/records')
def record(application_id: int, body: RecordCreate, db: Db, actor: Officer, audit: Audit):
    return case_data.write(db, application_id, body, actor, audit)


@router.post('/{application_id}/records/{record_id}/replace')
def replace(application_id: int, record_id: int, body: RecordCreate, db: Db, actor: Manager, audit: Audit):
    return case_data.write(db, application_id, body, actor, audit, target_id=record_id)


@router.post('/{application_id}/records/{record_id}/withdraw')
def withdraw(application_id: int, record_id: int, body: WithdrawRecord, db: Db, actor: Manager, audit: Audit):
    return case_data.write(db, application_id, body, actor, audit, target_id=record_id, withdraw=True)
