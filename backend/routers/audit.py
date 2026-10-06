"""Read-only access to the audit trail. There is no route that changes it."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.database import AuditLog, get_db
from schemas import AuditLogResponse
from services.auth_service import require_admin

router = APIRouter(prefix="/audit", tags=["Audit"], dependencies=[Depends(require_admin)])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/logs", response_model=list[AuditLogResponse], summary="Read the audit trail (admin)")
async def list_audit_logs(
    db: DbSession,
    action: Annotated[str | None, Query(max_length=64, description="e.g. application.scored")] = None,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    username: Annotated[str | None, Query(max_length=64)] = None,
    request_id: Annotated[str | None, Query(max_length=64)] = None,
    since: Annotated[datetime | None, Query(description="Entries at or after this time.")] = None,
    until: Annotated[datetime | None, Query(description="Entries before this time.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditLogResponse]:
    """Audit entries, newest first, filtered by any of the query parameters.

    The trail is append-only: entries are written by the actions they describe
    and nothing in the API updates or deletes one.
    """
    statement = select(AuditLog).order_by(AuditLog.id.desc())
    for column, value in (
        (AuditLog.action, action),
        (AuditLog.entity_type, entity_type),
        (AuditLog.entity_id, entity_id),
        (AuditLog.username, username),
        (AuditLog.request_id, request_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if since is not None:
        statement = statement.where(AuditLog.occurred_at >= since)
    if until is not None:
        statement = statement.where(AuditLog.occurred_at < until)
    entries = db.scalars(statement.offset(offset).limit(limit)).all()
    return [AuditLogResponse.model_validate(entry) for entry in entries]
