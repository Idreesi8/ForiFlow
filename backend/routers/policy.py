"""The credit policy: read by every officer, changed only by an admin."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.database import CreditPolicy, User, get_db
from schemas import PolicyCreate, PolicyResponse
from services import policy_service
from services.audit_service import Audit
from services.auth_service import get_current_user, require_admin

router = APIRouter(
    prefix="/policy",
    tags=["Credit policy"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Admin = Annotated[User, Depends(require_admin)]


def _response(policy: CreditPolicy, counts: dict[int, int]) -> PolicyResponse:
    return PolicyResponse.model_validate(policy).model_copy(
        update={"applications_assessed": int(counts.get(policy.id, 0))}
    )


@router.get("/active", response_model=PolicyResponse, summary="The policy in force now")
async def get_active_policy(db: DbSession) -> PolicyResponse:
    """The version new assessments are made under.

    The policy turns a model score into a recommendation and sets who may
    approve. It is configurable; the shipped figures are demo values, not
    thresholds validated for Pakistani SME lending.
    """
    policy = policy_service.active_policy(db)
    db.commit()  # keeps the demo policy if this call was the first to need it
    return _response(policy, policy_service.applications_assessed(db))


@router.get(
    "/versions", response_model=list[PolicyResponse], summary="Every policy version, newest first"
)
async def list_policy_versions(db: DbSession) -> list[PolicyResponse]:
    """Drafts, the active version and retired ones. None is ever deleted."""
    policy_service.active_policy(db)
    db.commit()
    counts = policy_service.applications_assessed(db)
    policies = db.scalars(select(CreditPolicy).order_by(CreditPolicy.id.desc())).all()
    return [_response(policy, counts) for policy in policies]


@router.post(
    "/versions",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a policy version as a draft (admin)",
)
async def create_policy_version(
    body: PolicyCreate, db: DbSession, admin: Admin, audit: Audit
) -> PolicyResponse:
    """Add a version. It changes nothing until an admin activates it.

    A version's figures cannot be edited afterwards, and a version number
    cannot be reused (``409``): a change is always a new version.
    """
    policy = policy_service.create_version(db, body, actor=admin, context=audit)
    db.commit()
    db.refresh(policy)
    return _response(policy, {})


@router.post(
    "/versions/{policy_id}/activate",
    response_model=PolicyResponse,
    summary="Make a policy version the active one (admin)",
)
async def activate_policy_version(
    policy_id: int, db: DbSession, admin: Admin, audit: Audit
) -> PolicyResponse:
    """Activate a version and retire the one it replaces.

    Only assessments made from now on use it. Applications already assessed
    keep the version, recommendation and authority rule they were given.
    """
    policy = policy_service.get(db, policy_id, for_update=True)
    policy_service.activate(db, policy, actor=admin, context=audit)
    db.commit()
    db.refresh(policy)
    return _response(policy, policy_service.applications_assessed(db))
