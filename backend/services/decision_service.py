"""The human decision: who may decide an application, and the record of it.

A recommendation never becomes a decision by itself. An application stays
``Pending`` until an authorised officer approves or rejects it, and every
action here, including a refused one, is written to the audit trail.

Authority (enforced here, on the server; the dashboard only mirrors it):

* An analyst decides nothing.
* A manager may reject any application, approve one within the policy's manager
  limit, and escalate one to an admin.
* Approving above the manager limit, approving against a Decline
  recommendation (when the policy says so) and anything on an escalated
  application need an admin.
* A decision is recorded once and is not changed afterwards.

The limits come from the policy version the application was assessed under.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.database import Application, AuditLog, User, utcnow
from schemas import (
    RECOMMENDATION_OF,
    AssessmentRecord,
    Decision,
    DecisionEvent,
    DecisionHistory,
    DecisionStatus,
    OfficerAction,
    UserRole,
)
from services import audit_service
from services.audit_service import Action, AuditContext

OPEN_STATUSES = (DecisionStatus.PENDING.value, DecisionStatus.ESCALATED.value)

# The inputs an officer can change between a score and a re-score.
RESCORE_INPUTS = (
    "loan_amount_pkr",
    "tenure_months",
    "monthly_digital_payments",
    "payment_history_score",
    "inventory_turnover",
    "order_consistency",
    "existing_debt_pkr",
    "cash_flow_proxy",
    "years_in_operation",
    "num_employees",
)

_DENIAL_TEXT = {
    "above_manager_limit": (
        "A facility of PKR {loan:,.0f} is above the manager approval limit of "
        "PKR {limit:,.0f}. An admin must approve it. A manager can still reject "
        "or escalate it."
    ),
    "approval_against_decline_recommendation": (
        "The policy recommends Decline. Approving against that recommendation needs "
        "an admin. A manager can still reject or escalate it."
    ),
    "escalated": (
        "Application {id} was escalated by {escalated_by} and is now with an admin."
    ),
}


def assessment_state(application: Application) -> dict:
    """The assessment facts an audit entry keeps about an application."""
    return {
        "risk_score": application.risk_score,
        "risk_band": application.risk_band,
        "recommendation": RECOMMENDATION_OF[Decision(application.decision)].value,
        "model_version": application.model_version,
        "scoring_engine": application.scoring_engine,
        "policy_version": application.policy_version,
        "decision_status": application.decision_status,
    }


def _refuse(
    db: Session,
    application: Application,
    officer: User,
    context: AuditContext | None,
    *,
    attempted: str,
    reason: str,
) -> HTTPException:
    """Record a refused action, commit it, and build the ``403`` to raise."""
    view = application.authority_view
    audit_service.record(
        db,
        action=Action.APPROVAL_DENIED,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        details={
            "attempted": attempted,
            "reason": reason,
            "loan_amount_pkr": application.loan_amount_pkr,
            "manager_approval_limit_pkr": view["manager_approval_limit_pkr"],
            "policy_version": application.policy_version,
            "decision_status": application.decision_status,
        },
        context=context,
    )
    db.commit()
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_DENIAL_TEXT[reason].format(
            loan=application.loan_amount_pkr,
            limit=view["manager_approval_limit_pkr"],
            id=application.id,
            escalated_by=application.escalated_by or "a manager",
        ),
    )


def record_action(
    db: Session,
    application: Application,
    action: OfficerAction,
    note: str,
    *,
    officer: User,
    context: AuditContext | None,
) -> Application:
    """Approve, reject or escalate. The caller holds the row lock and commits."""
    if application.decision_status == DecisionStatus.SUPERSEDED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Application {application.id} was re-scored as application "
                f"{application.superseded_by_application_id}. Decide that one."
            ),
        )
    if application.decision_status not in OPEN_STATUSES:
        by = (
            f"by {application.reviewed_by}"
            if application.reviewed_by
            else "under the rule in force before release 2.0"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Application {application.id} was already {application.decision_status} "
                f"{by}. A recorded decision is not changed."
            ),
        )

    is_admin = officer.role == UserRole.ADMIN.value
    escalated = application.decision_status == DecisionStatus.ESCALATED.value
    before = assessment_state(application)

    if action is OfficerAction.ESCALATED:
        if is_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An admin is the final authority and decides the application.",
            )
        if escalated:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Application {application.id} was already escalated by "
                    f"{application.escalated_by}."
                ),
            )
        application.decision_status = DecisionStatus.ESCALATED.value
        application.escalated_by = officer.username
        application.escalated_at = utcnow()
        application.escalation_note = note
        audit_service.record(
            db,
            action=Action.APPLICATION_ESCALATED,
            entity_type="application",
            entity_id=application.id,
            actor=officer,
            previous={"decision_status": before["decision_status"]},
            new={
                "decision_status": application.decision_status,
                "escalated_by": application.escalated_by,
                "escalated_at": application.escalated_at,
                "escalation_note": note,
            },
            details={**before, "loan_amount_pkr": application.loan_amount_pkr},
            context=context,
        )
        return application

    if escalated and not is_admin:
        raise _refuse(
            db, application, officer, context, attempted=action.value, reason="escalated"
        )
    if action is OfficerAction.APPROVED and not is_admin:
        view = application.authority_view
        if view["approve_requires"] == UserRole.ADMIN.value:
            raise _refuse(
                db, application, officer, context, attempted=action.value, reason=view["reason"]
            )

    recommendation = Decision(application.decision)
    overrides = recommendation is not Decision.MANUAL_REVIEW and (
        action.value != recommendation.value
    )
    application.review_decision = action.value
    application.review_note = note
    application.reviewed_by = officer.username
    application.reviewed_at = utcnow()
    application.decision_status = action.value
    application.decision_source = "officer"
    audit_service.record(
        db,
        action=Action.OFFICER_DECISION,
        entity_type="application",
        entity_id=application.id,
        actor=officer,
        previous={
            "decision": application.decision,
            "review_decision": None,
            "decision_status": before["decision_status"],
        },
        new={
            "review_decision": application.review_decision,
            "decision_status": application.decision_status,
            "review_note": application.review_note,
            "reviewed_by": application.reviewed_by,
            "reviewed_at": application.reviewed_at,
        },
        details={
            # The assessment and recommendation the officer decided on.
            **before,
            "loan_amount_pkr": application.loan_amount_pkr,
            "overrides_recommendation": overrides,
            "was_escalated": escalated,
            "escalated_by": application.escalated_by,
        },
        context=context,
    )
    return application


def supersede(
    db: Session,
    previous: Application,
    replacement: Application,
    *,
    officer: User,
    context: AuditContext | None,
) -> dict:
    """Mark ``previous`` as replaced by ``replacement`` and audit the re-score.

    Nothing about the earlier assessment is altered: its score, explanation,
    model version and policy version stay as they were. Returns the inputs that
    differ between the two, which is what a reviewer looks at first.
    """
    changed = {
        name: [getattr(previous, name), getattr(replacement, name)]
        for name in RESCORE_INPUTS
        if getattr(previous, name) != getattr(replacement, name)
    }
    before = assessment_state(previous)
    previous.decision_status = DecisionStatus.SUPERSEDED.value
    previous.superseded_by_application_id = replacement.id
    replacement.supersedes_application_id = previous.id
    audit_service.record(
        db,
        action=Action.APPLICATION_SUPERSEDED,
        entity_type="application",
        entity_id=previous.id,
        actor=officer,
        previous={"decision_status": before["decision_status"]},
        new={
            "decision_status": previous.decision_status,
            "superseded_by_application_id": replacement.id,
        },
        details=before,
        context=context,
    )
    audit_service.record(
        db,
        action=Action.APPLICATION_RESCORED,
        entity_type="application",
        entity_id=replacement.id,
        actor=officer,
        previous={**before, "application_id": previous.id, "scored_by": previous.scored_by},
        new={**assessment_state(replacement), "application_id": replacement.id},
        details={
            "inputs_changed": changed,
            "inputs_unchanged": not changed,
            "score_change": round(replacement.risk_score - previous.risk_score, 2),
            "rescore_number": _chain_length(db, replacement) - 1,
        },
        context=context,
    )
    return changed


def _chain(db: Session, application: Application) -> list[Application]:
    """The application and every assessment it replaced, oldest first."""
    chain = [application]
    seen = {application.id}
    current = application
    while current.supersedes_application_id is not None:
        earlier = db.get(Application, current.supersedes_application_id)
        if earlier is None or earlier.id in seen:
            break
        chain.append(earlier)
        seen.add(earlier.id)
        current = earlier
    current = application
    later: list[Application] = []
    while current.superseded_by_application_id is not None:
        newer = db.get(Application, current.superseded_by_application_id)
        if newer is None or newer.id in seen:
            break
        later.append(newer)
        seen.add(newer.id)
        current = newer
    return list(reversed(chain)) + later


def _chain_length(db: Session, application: Application) -> int:
    return len(_chain(db, application))


def history(db: Session, application: Application) -> DecisionHistory:
    """Every assessment in the re-score chain and every audited event on them."""
    chain = _chain(db, application)
    ids = [str(item.id) for item in chain]
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "application", AuditLog.entity_id.in_(ids))
        .order_by(AuditLog.id)
    ).all()
    audited = {entry.entity_id for entry in entries}
    unaudited = [item.id for item in chain if str(item.id) not in audited]
    return DecisionHistory(
        application_id=application.id,
        assessments=[
            AssessmentRecord(
                application_id=item.id,
                created_at=item.created_at,
                scored_by=item.scored_by,
                loan_amount_pkr=item.loan_amount_pkr,
                risk_score=item.risk_score,
                risk_band=item.risk_band,
                recommendation=RECOMMENDATION_OF[Decision(item.decision)],
                model_version=item.model_version,
                scoring_engine=item.scoring_engine,
                policy_version=item.policy_version,
                decision_status=item.decision_status,
                decided_by=item.reviewed_by,
                decided_at=item.reviewed_at,
                supersedes_application_id=item.supersedes_application_id,
                superseded_by_application_id=item.superseded_by_application_id,
            )
            for item in chain
        ],
        events=[
            DecisionEvent(
                occurred_at=entry.occurred_at,
                application_id=int(entry.entity_id),
                action=entry.action,
                actor=entry.username,
                role=entry.role,
                previous_state=entry.previous_state,
                new_state=entry.new_state,
                details=entry.details,
                request_id=entry.request_id,
            )
            for entry in entries
        ],
        note=(
            f"Application(s) {', '.join(str(i) for i in unaudited)} were recorded before "
            "the audit trail existed (release 1.10), so they have no events; the "
            "assessment record above is what is on file."
            if unaudited
            else None
        ),
    )
