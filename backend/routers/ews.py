"""Early Warning System endpoints for post-disbursement monitoring."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from models.database import Alert, Application, EWSTracking, User, get_db, utcnow
from schemas import (
    AlertResolveRequest,
    AlertResponse,
    AlertStatus,
    ApplicationSummary,
    Decision,
    EWSMonitorRequest,
    EWSMonitorResponse,
    EWSTrackingResponse,
)
from services.auth_service import get_current_user, require_admin
from services.ews_service import EWSService, get_ews_service

router = APIRouter(
    prefix="/ews",
    tags=["Early Warning System"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Monitor = Annotated[EWSService, Depends(get_ews_service)]
Officer = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(require_admin)]


def _require_approved_facility(borrower: Application) -> None:
    """Only an approved application became a facility, so only it is monitored.

    Approved means Approved by the model, or Manual Review and then approved
    by an officer. ForiFlow keeps no separate disbursement record.
    """
    final = ApplicationSummary.model_validate(borrower).final_decision
    if final is Decision.APPROVED:
        return
    if final is None:
        detail = (
            f"Application {borrower.id} is still awaiting an officer decision "
            "(Manual Review). Approve it first, then monitor it."
        )
    elif borrower.decision == Decision.MANUAL_REVIEW.value:
        detail = (
            f"Application {borrower.id} was rejected by {borrower.reviewed_by} after "
            "manual review, so there is no facility to monitor."
        )
    else:
        detail = (
            f"Application {borrower.id} was Rejected at origination, so there "
            "is no facility to monitor."
        )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _load_borrower(borrower_id: int, db: Session) -> Application:
    """Fetch the borrower's originating application or raise ``404``."""
    borrower = db.get(Application, borrower_id)
    if borrower is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrower {borrower_id} was not found.",
        )
    return borrower


@router.post(
    "/monitor",
    response_model=EWSMonitorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a monthly observation and trigger an alert if the score drops",
)
async def monitor_borrower(
    payload: EWSMonitorRequest,
    db: DbSession,
    monitor: Monitor,
    officer: Officer,
) -> EWSMonitorResponse:
    """Evaluate one borrower-month of surveillance data.

    The borrower's origination score is the baseline. An alert is raised when
    the recomputed score falls more than 15 points below that baseline. Any
    already-open alert is updated in place instead of being duplicated.

    Only the latest recorded month drives the alert, so back-filling an older
    month never rewrites it. If a correction of the latest month brings it
    back within the threshold, the open alert it raised is closed with a note.
    """
    borrower = _load_borrower(payload.borrower_id, db)
    _require_approved_facility(borrower)
    if payload.month_number > borrower.tenure_months:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Month {payload.month_number} is past the end of the facility: "
                f"application {borrower.id} has a {borrower.tenure_months}-month tenure."
            ),
        )

    outcome = monitor.evaluate(
        baseline_score=borrower.risk_score,
        payload=payload,
        original_loan_amount_pkr=borrower.loan_amount_pkr,
        expected_monthly_cash_flow=borrower.cash_flow_proxy,
    )

    # Re-submitting a month (e.g. after correcting a typed bureau balance) overwrites it.
    tracking = db.scalars(
        select(EWSTracking).where(
            EWSTracking.borrower_id == payload.borrower_id,
            EWSTracking.month_number == payload.month_number,
        )
    ).first()
    # A corrected month that breached before is the one the open alert follows.
    corrected_breach = (
        tracking is not None
        and borrower.risk_score - tracking.monthly_score > monitor.alert_threshold
    )
    if tracking is None:
        tracking = EWSTracking(
            borrower_id=payload.borrower_id, month_number=payload.month_number
        )
        db.add(tracking)

    tracking.installment_status = payload.installment_status.value
    tracking.bureau_balance = payload.bureau_balance
    tracking.pos_cash_balance = payload.pos_cash_balance
    tracking.monthly_score = outcome.current_score
    tracking.data_source_primary = payload.data_source_primary.value
    db.flush()

    latest_month = db.scalar(
        select(func.max(EWSTracking.month_number)).where(
            EWSTracking.borrower_id == payload.borrower_id
        )
    )
    is_latest = payload.month_number >= (latest_month or 0)

    alert: Alert | None = db.scalars(
        select(Alert)
        .where(
            Alert.borrower_id == payload.borrower_id,
            Alert.alert_status != AlertStatus.RESOLVED.value,
        )
        .order_by(Alert.triggered_at.desc())
    ).first()

    raised = is_latest and outcome.alert_triggered
    touched = False
    if raised:
        touched = True
        if alert is None:
            alert = Alert(
                borrower_id=payload.borrower_id,
                alert_status=AlertStatus.ACTIVE.value,
                triggered_at=utcnow(),
            )
            db.add(alert)
        alert.baseline_score = outcome.baseline_score
        alert.current_score = outcome.current_score
        alert.score_drop = outcome.score_drop
        alert.estimated_days_to_default = outcome.estimated_days_to_default
    elif is_latest and corrected_breach and alert is not None:
        # The month that raised the alert was corrected and no longer breaches.
        touched = True
        alert.current_score = outcome.current_score
        alert.score_drop = outcome.score_drop
        alert.alert_status = AlertStatus.RESOLVED.value
        alert.resolved_at = utcnow()
        alert.resolved_by = officer.username
        alert.resolution_note = (
            f"Closed automatically: month {payload.month_number} was corrected and is "
            f"now within the {monitor.alert_threshold:g}-point threshold."
        )

    db.commit()
    db.refresh(tracking)
    if touched:
        db.refresh(alert)
    else:
        alert = None

    recommended_action = outcome.recommended_action
    if not is_latest:
        recommended_action = (
            f"Earlier month recorded. Alerts follow the latest month on file "
            f"(month {latest_month}), so no alert was changed."
        )

    return EWSMonitorResponse(
        borrower_id=borrower.id,
        business_name=borrower.business_name,
        month_number=payload.month_number,
        baseline_score=outcome.baseline_score,
        current_score=outcome.current_score,
        score_drop=outcome.score_drop,
        alert_triggered=raised,
        alert_threshold=monitor.alert_threshold,
        estimated_days_to_default=outcome.estimated_days_to_default if raised else None,
        recommended_action=recommended_action,
        tracking=EWSTrackingResponse.model_validate(tracking),
        alert=AlertResponse.model_validate(alert) if alert is not None else None,
    )


@router.get("/alerts", response_model=list[AlertResponse], summary="List EWS alerts")
async def list_alerts(
    db: DbSession,
    alert_status: Annotated[
        AlertStatus | None, Query(description="Filter by alert lifecycle status.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlertResponse]:
    """Return alerts ordered by severity so the worst cases surface first."""
    statement = (
        select(Alert)
        .options(selectinload(Alert.borrower))
        .order_by(Alert.score_drop.desc(), Alert.triggered_at.desc())
    )
    if alert_status is not None:
        statement = statement.where(Alert.alert_status == alert_status.value)

    alerts = db.scalars(statement.offset(offset).limit(limit)).all()
    return [AlertResponse.model_validate(alert) for alert in alerts]


@router.get(
    "/borrowers/{borrower_id}/history",
    response_model=list[EWSTrackingResponse],
    summary="Monthly monitoring history for one borrower",
)
async def borrower_history(borrower_id: int, db: DbSession) -> list[EWSTrackingResponse]:
    """Return the borrower's monthly score trend for the dashboard chart."""
    _load_borrower(borrower_id, db)

    records = db.scalars(
        select(EWSTracking)
        .where(EWSTracking.borrower_id == borrower_id)
        .order_by(EWSTracking.month_number)
    ).all()
    return [EWSTrackingResponse.model_validate(record) for record in records]


def _load_open_alert(alert_id: int, db: Session) -> Alert:
    """Fetch an alert that is not yet resolved, or raise ``404`` / ``409``."""
    alert = db.get(Alert, alert_id, with_for_update=True)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} was not found.",
        )
    if alert.alert_status == AlertStatus.RESOLVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} was already resolved by {alert.resolved_by or 'an officer'}.",
        )
    return alert


@router.patch(
    "/alerts/{alert_id}/review",
    response_model=AlertResponse,
    summary="Take an EWS alert for review",
)
async def review_alert(alert_id: int, db: DbSession, officer: Officer) -> AlertResponse:
    """Mark an open alert In Review and record which officer is handling it.

    Taking an alert someone else is already reviewing returns ``409``, so a
    case never changes hands silently.
    """
    alert = _load_open_alert(alert_id, db)
    if (
        alert.alert_status == AlertStatus.IN_REVIEW.value
        and alert.assigned_to not in (None, officer.username)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} is already being reviewed by {alert.assigned_to}.",
        )
    alert.alert_status = AlertStatus.IN_REVIEW.value
    alert.assigned_to = officer.username
    db.commit()
    db.refresh(alert)
    return AlertResponse.model_validate(alert)


@router.patch(
    "/alerts/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Resolve an EWS alert with a note (admin only)",
)
async def resolve_alert(
    alert_id: int, body: AlertResolveRequest, db: DbSession, officer: Admin
) -> AlertResponse:
    """Close an alert, recording who closed it, when, and what was done."""
    alert = _load_open_alert(alert_id, db)
    alert.alert_status = AlertStatus.RESOLVED.value
    alert.resolved_at = utcnow()
    alert.resolved_by = officer.username
    alert.resolution_note = body.note
    db.commit()
    db.refresh(alert)
    return AlertResponse.model_validate(alert)
