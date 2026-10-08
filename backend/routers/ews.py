"""Early Warning System endpoints: observations, trend, state, alerts, timeline.

The backend is authoritative. Observations are history: a recorded month is
never overwritten (a correction adds a row and supersedes the original), and
every change is written to the append-only audit trail. Trend, signals, state
and alerts come from :mod:`services.ews_engine`, a deterministic rule set; the
EWS recommends, it never changes a facility.

Who may do what:

* any signed-in officer (analyst, manager, admin): read everything and record
  a month with the rule-derived score;
* manager or admin: override a month's score (with a reason), correct a
  recorded month, and acknowledge, assign, set due dates on, mark Action
  Required, resolve or dismiss alerts.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from models.database import (
    ALERT_OPEN_STATUSES,
    Alert,
    Application,
    AuditLog,
    EWSTracking,
    User,
    get_db,
    utcnow,
)
from schemas import (
    AlertActionRequest,
    AlertAssignRequest,
    AlertDueDateRequest,
    AlertNoteRequest,
    AlertResolveRequest,
    AlertResponse,
    AlertSeverity,
    AlertStatus,
    AuditLogResponse,
    EWSCorrectionRequest,
    EWSFacilityState,
    EWSMethodology,
    EWSMonitorRequest,
    EWSMonitorResponse,
    EWSObservationFields,
    EWSOverview,
    EWSOverviewRow,
    EWSSignal,
    EWSState,
    EWSTrackingResponse,
    EWSTrend,
    FacilityTimeline,
    InstallmentStatus,
    TimelineEvent,
    TrendPoint,
    UserRole,
)
from services import audit_service, ews_engine
from services.audit_service import Action, Audit, AuditContext
from services.auth_service import get_current_user, require_manager
from services.ews_service import EWSService, MonitoringOutcome, get_ews_service

router = APIRouter(
    prefix="/ews",
    tags=["Early Warning System"],
    dependencies=[Depends(get_current_user)],
)

DbSession = Annotated[Session, Depends(get_db)]
Monitor = Annotated[EWSService, Depends(get_ews_service)]
Officer = Annotated[User, Depends(get_current_user)]
Manager = Annotated[User, Depends(require_manager)]

MANAGER_ROLES = frozenset({UserRole.MANAGER.value, UserRole.ADMIN.value})

_TRACKING_FIELDS = (
    "month_number",
    "observation_date",
    "installment_status",
    "days_late",
    "bureau_balance",
    "pos_cash_balance",
    "monthly_score",
    "score_source",
    "rule_score",
    "override_reason",
    "data_source_primary",
    "amount_paid_pkr",
    "record_status",
    "supersedes_observation_id",
    "superseded_by_observation_id",
    "correction_reason",
)
_ALERT_FIELDS = (
    "alert_status",
    "severity",
    "reason_codes",
    "baseline_score",
    "previous_score",
    "current_score",
    "score_drop",
    "estimated_days_to_default",
    "last_observation_id",
    "acknowledged_by",
    "acknowledged_at",
    "assigned_to",
    "assigned_by",
    "action_due_date",
    "action_note",
    "resolved_by",
    "resolved_at",
    "resolution_note",
)
_LIFECYCLE_FIELDS = (
    "alert_status",
    "acknowledged_by",
    "acknowledged_at",
    "assigned_to",
    "assigned_by",
    "assigned_at",
    "action_due_date",
    "action_note",
    "resolved_by",
    "resolved_at",
    "resolution_note",
)


def _state(row: object, fields: tuple[str, ...]) -> dict:
    """The audited fields of an observation or an alert."""
    return {name: getattr(row, name) for name in fields}


# --- loading -------------------------------------------------------------------------


def _require_approved_facility(borrower: Application) -> None:
    """Only an approved application became a facility, so only it is monitored.

    Approved means an officer approved it (or, for an application from before
    2.0, that the score band alone did under the rule then in force). A
    recommendation of Approve is not an approval. ForiFlow keeps no separate
    disbursement record.
    """
    state = borrower.decision_status
    if state == "Approved":
        return
    if state in ("Pending", "Escalated"):
        detail = (
            f"Application {borrower.id} is still awaiting an officer decision "
            f"(recommendation: {borrower.decision}). Approve it first, then monitor it."
        )
    elif state == "Superseded":
        detail = (
            f"Application {borrower.id} was re-scored as application "
            f"{borrower.superseded_by_application_id}, so there is no facility to monitor."
        )
    elif borrower.reviewed_by:
        detail = (
            f"Application {borrower.id} was Rejected by {borrower.reviewed_by}, "
            "so there is no facility to monitor."
        )
    else:
        detail = (
            f"Application {borrower.id} was Rejected at origination, so there "
            "is no facility to monitor."
        )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _load_facility(facility_id: int, db: Session) -> Application:
    """Fetch the facility's application or raise ``404``."""
    borrower = db.get(Application, facility_id)
    if borrower is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Borrower {facility_id} was not found.",
        )
    return borrower


def _active_observations(db: Session, facility_id: int) -> list[EWSTracking]:
    """The facility's current history: one active row per month, oldest first."""
    return list(
        db.scalars(
            select(EWSTracking)
            .where(EWSTracking.borrower_id == facility_id, EWSTracking.record_status == "active")
            .order_by(EWSTracking.month_number)
        ).all()
    )


def _open_alert(db: Session, facility_id: int, *, lock: bool = False) -> Alert | None:
    statement = select(Alert).where(
        Alert.borrower_id == facility_id, Alert.alert_status.in_(ALERT_OPEN_STATUSES)
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalars(statement.order_by(Alert.triggered_at.desc())).first()


# --- recording a month -------------------------------------------------------------


def _check_override_allowed(
    payload: EWSObservationFields,
    officer: User,
    facility_id: int,
    db: Session,
    audit: AuditContext,
) -> None:
    """A score override needs a manager or admin. A refusal is audited."""
    if payload.current_score is None or officer.role in MANAGER_ROLES:
        return
    audit_service.record(
        db,
        action=Action.EWS_SCORE_OVERRIDE_DENIED,
        entity_type="application",
        entity_id=facility_id,
        actor=officer,
        details={"attempted_score": payload.current_score, "role": officer.role},
        context=audit,
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Overriding the monitored score needs a manager or admin.",
    )


def _observation_date(
    payload: EWSObservationFields, borrower: Application, fallback: date | None
) -> date:
    """The date the figures were observed: given, else the fallback, else today."""
    observed = payload.observation_date or fallback or utcnow().date()
    created = borrower.created_at.date() if borrower.created_at is not None else None
    if created is not None and observed < created:
        raise HTTPException(
            status_code=422,
            detail=(
                f"observation_date {observed.isoformat()} is before application "
                f"{borrower.id} was scored ({created.isoformat()})."
            ),
        )
    return observed


def _new_observation(
    *,
    borrower: Application,
    month_number: int,
    payload: EWSObservationFields,
    monitor: EWSService,
    officer: User,
    audit: AuditContext,
    observed: date,
) -> tuple[EWSTracking, MonitoringOutcome]:
    """A new, unsaved observation row and the month's scoring outcome."""
    outcome = monitor.evaluate(
        baseline_score=borrower.risk_score,
        payload=payload,
        original_loan_amount_pkr=borrower.loan_amount_pkr,
        expected_monthly_cash_flow=borrower.cash_flow_proxy,
    )
    row = EWSTracking(
        borrower_id=borrower.id,
        month_number=month_number,
        observation_date=observed,
        installment_status=payload.installment_status.value,
        days_late=payload.days_late,
        bureau_balance=payload.bureau_balance,
        pos_cash_balance=payload.pos_cash_balance,
        monthly_score=outcome.current_score,
        rule_score=outcome.rule_score,
        score_source="officer_override" if outcome.score_overridden else "ews_rule_adjusted",
        override_reason=payload.override_reason if outcome.score_overridden else None,
        data_source_primary=payload.data_source_primary.value,
        amount_paid_pkr=payload.amount_paid_pkr,
        record_status="active",
        created_by=officer.username,
        created_at=utcnow(),
        request_id=audit.request_id,
    )
    return row, outcome


def _store_assessment(
    db: Session, borrower: Application, row: EWSTracking
) -> ews_engine.Assessment:
    """Assess the facility now; keep on the row what the EWS concluded as of its month."""
    facility = ews_engine.facility_of(borrower)
    active = _active_observations(db, borrower.id)
    as_of = ews_engine.assess(facility, [r for r in active if r.month_number <= row.month_number])
    row.assessment = as_of.as_dict()
    return ews_engine.assess(facility, active)


def _audit_override(
    db: Session, row: EWSTracking, borrower: Application, officer: User, audit: AuditContext
) -> None:
    """An override is audited on its own, with the rule score it replaced."""
    if row.score_source != "officer_override":
        return
    audit_service.record(
        db,
        action=Action.EWS_SCORE_OVERRIDDEN,
        entity_type="ews_observation",
        entity_id=row.id,
        actor=officer,
        previous={"monthly_score": row.rule_score, "score_source": "ews_rule_adjusted"},
        new={
            "monthly_score": row.monthly_score,
            "score_source": "officer_override",
            "override_reason": row.override_reason,
        },
        details={"application_id": borrower.id, "month_number": row.month_number},
        context=audit,
    )


# --- alerts from an assessment -----------------------------------------------------


def _evidence(assessment: ews_engine.Assessment) -> list[dict[str, Any]]:
    """The signals and the state rules that fired, each with its figures."""
    items: list[dict[str, Any]] = [
        {"kind": "signal", **signal.as_dict()} for signal in assessment.signals
    ]
    items.extend(
        {
            "kind": "state_rule",
            "code": None,
            "label": f"{assessment.state.value} rule",
            "evidence": reason,
            "values": {},
        }
        for reason in assessment.state_reasons
    )
    return items


def _severity_rank(value: str | None) -> int:
    """Rank of an alert's severity. A legacy alert (no severity) counts as WARNING:
    it was raised by a drop above the warning line."""
    return ews_engine.STATE_RANK[EWSState(value) if value else EWSState.WARNING]


def _apply_alert(
    db: Session,
    *,
    borrower: Application,
    assessment: ews_engine.Assessment,
    observation: EWSTracking,
    monitor: EWSService,
    officer: User,
    audit: AuditContext,
    corrected: EWSTracking | None = None,
) -> tuple[Alert | None, bool]:
    """Open, update, escalate or auto-resolve the facility's one open alert.

    Returns the alert touched (or None) and whether the facility is alerting.
    The alert always describes the facility's latest active month. Its severity
    only rises while it is open; an improving month leaves it open for an
    officer to resolve. Only a correction of the month the alert rests on can
    close it automatically.
    """
    alert = _open_alert(db, borrower.id, lock=True)
    trend = assessment.trend
    latest = db.get(EWSTracking, assessment.latest_observation_id) or observation

    if assessment.raises_alert:
        before = _state(alert, _ALERT_FIELDS) if alert is not None else None
        if alert is None:
            alert = Alert(
                borrower_id=borrower.id,
                alert_status=AlertStatus.OPEN.value,
                triggered_at=utcnow(),
                observation_id=latest.id,
            )
            db.add(alert)
            action = Action.EWS_ALERT_CREATED
            severity = assessment.state
        else:
            rises = ews_engine.STATE_RANK[assessment.state] > _severity_rank(alert.severity)
            action = Action.EWS_ALERT_ESCALATED if rises else Action.EWS_ALERT_UPDATED
            severity = (
                assessment.state if rises or alert.severity is None else EWSState(alert.severity)
            )
        days, _basis = monitor.runway(
            InstallmentStatus(latest.installment_status), trend.total_deterioration or 0.0
        )
        alert.severity = severity.value
        alert.reason_codes = assessment.reason_codes
        alert.evidence = _evidence(assessment)
        alert.recommended_actions = list(ews_engine.RECOMMENDED_ACTIONS[severity])
        alert.baseline_score = trend.baseline_score
        alert.previous_score = trend.previous_score
        alert.current_score = trend.latest_score
        alert.score_drop = trend.total_deterioration
        alert.last_observation_id = latest.id
        alert.estimated_days_to_default = days
        db.flush()
        after = _state(alert, _ALERT_FIELDS)
        if before is None or after != before:
            audit_service.record(
                db,
                action=action,
                entity_type="ews_alert",
                entity_id=alert.id,
                actor=officer,
                previous=before,
                new=after,
                details={
                    "application_id": borrower.id,
                    "borrower_id": borrower.borrower_id,
                    "month_number": latest.month_number,
                    "observation_id": latest.id,
                    "ews_state": assessment.state.value,
                    "reason_codes": assessment.reason_codes,
                },
                context=audit,
            )
        return alert, True

    if alert is not None and corrected is not None:
        rests_on = alert.last_observation_id or alert.observation_id
        corrected_latest = corrected.month_number >= (assessment.latest_month or 0)
        if rests_on == corrected.id or (rests_on is None and corrected_latest):
            before = _state(alert, _ALERT_FIELDS)
            alert.current_score = trend.latest_score
            alert.previous_score = trend.previous_score
            alert.score_drop = trend.total_deterioration
            alert.last_observation_id = latest.id
            alert.alert_status = AlertStatus.RESOLVED.value
            alert.resolved_at = utcnow()
            alert.resolved_by = officer.username
            alert.resolution_note = (
                f"Closed automatically: month {corrected.month_number} was corrected "
                f"(observation {corrected.id} -> {observation.id}) and the facility is now "
                f"{assessment.state.value}."
            )
            db.flush()
            audit_service.record(
                db,
                action=Action.EWS_ALERT_AUTO_RESOLVED,
                entity_type="ews_alert",
                entity_id=alert.id,
                actor=officer,
                previous=before,
                new=_state(alert, _ALERT_FIELDS),
                details={
                    "application_id": borrower.id,
                    "corrected_observation_id": corrected.id,
                    "observation_id": observation.id,
                    "ews_state": assessment.state.value,
                },
                context=audit,
            )
            return alert, False
    return None, False


# --- response builders -------------------------------------------------------------


def _trend_response(
    borrower: Application, trend: ews_engine.Trend, rows: list[EWSTracking]
) -> EWSTrend:
    """The trend with its points: the baseline first, then each active month."""
    points = [
        TrendPoint(
            label="Baseline",
            month_number=0,
            score=round(float(borrower.risk_score), 2),
            score_source="origination_assessment",
        )
    ]
    points.extend(
        TrendPoint(
            label=f"Month {row.month_number}",
            month_number=row.month_number,
            score=round(float(row.monthly_score), 2),
            score_source=row.score_source,
            observation_id=row.id,
            observation_date=row.observation_date,
            installment_status=row.installment_status,
        )
        for row in rows
    )
    return EWSTrend(facility_id=borrower.id, points=points, **trend.as_dict())


def _signals(assessment: ews_engine.Assessment) -> list[EWSSignal]:
    return [EWSSignal(**signal.as_dict()) for signal in assessment.signals]


def _monitor_response(
    db: Session,
    borrower: Application,
    row: EWSTracking,
    outcome: MonitoringOutcome,
    assessment: ews_engine.Assessment,
    alert: Alert | None,
    alerting: bool,
    monitor: EWSService,
) -> EWSMonitorResponse:
    rows = _active_observations(db, borrower.id)
    actions = assessment.recommended_actions
    return EWSMonitorResponse(
        borrower_id=borrower.id,
        business_name=borrower.business_name,
        month_number=row.month_number,
        baseline_score=round(float(borrower.risk_score), 2),
        current_score=row.monthly_score,
        score_source=row.score_source,
        score_drop=round(float(borrower.risk_score) - row.monthly_score, 2),
        alert_triggered=alerting,
        alert_threshold=monitor.alert_threshold,
        ews_state=assessment.state,
        state_reasons=list(assessment.state_reasons),
        signals=_signals(assessment),
        trend=_trend_response(borrower, assessment.trend, rows),
        recommended_actions=actions,
        recommended_action=actions[0],
        estimated_days_to_default=(
            alert.estimated_days_to_default if alerting and alert is not None else None
        ),
        default_probability_3m=outcome.default_probability_3m,
        runway_basis=outcome.runway_basis,
        tracking=EWSTrackingResponse.model_validate(row),
        alert=AlertResponse.model_validate(alert) if alert is not None else None,
    )


# --- observations --------------------------------------------------------------------


@router.post(
    "/observations",
    response_model=EWSMonitorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a monthly observation for an approved facility (same as /ews/monitor)",
)
@router.post(
    "/monitor",
    response_model=EWSMonitorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a monthly observation for an approved facility",
)
async def record_observation(
    payload: EWSMonitorRequest,
    db: DbSession,
    monitor: Monitor,
    officer: Officer,
    audit: Audit,
) -> EWSMonitorResponse:
    """Record one month, then re-assess the facility and its alert.

    A month already on file returns ``409``: observations are not overwritten.
    A wrong month is corrected with ``POST /ews/observations/{id}/correct``.
    A score override (``current_score``) needs a manager or admin and a reason.
    """
    borrower = _load_facility(payload.borrower_id, db)
    _require_approved_facility(borrower)
    if payload.month_number > borrower.tenure_months:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Month {payload.month_number} is past the end of the facility: "
                f"application {borrower.id} has a {borrower.tenure_months}-month tenure."
            ),
        )
    existing = db.scalars(
        select(EWSTracking).where(
            EWSTracking.borrower_id == borrower.id,
            EWSTracking.month_number == payload.month_number,
            EWSTracking.record_status == "active",
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Month {payload.month_number} is already recorded for application "
                f"{borrower.id} (observation {existing.id}). Recorded months are not "
                f"overwritten; a manager can correct it with POST "
                f"/ews/observations/{existing.id}/correct."
            ),
        )
    _check_override_allowed(payload, officer, borrower.id, db, audit)
    observed = _observation_date(payload, borrower, None)

    row, outcome = _new_observation(
        borrower=borrower,
        month_number=payload.month_number,
        payload=payload,
        monitor=monitor,
        officer=officer,
        audit=audit,
        observed=observed,
    )
    db.add(row)
    db.flush()
    assessment = _store_assessment(db, borrower, row)
    db.flush()
    audit_service.record(
        db,
        action=Action.EWS_OBSERVATION_CREATED,
        entity_type="ews_observation",
        entity_id=row.id,
        actor=officer,
        previous=None,
        new=_state(row, _TRACKING_FIELDS),
        details={
            "application_id": borrower.id,
            "borrower_id": borrower.borrower_id,
            "baseline_score": round(float(borrower.risk_score), 2),
            "ews_state": assessment.state.value,
            "reason_codes": assessment.reason_codes,
            "default_probability_3m_reference": outcome.default_probability_3m,
        },
        context=audit,
    )
    _audit_override(db, row, borrower, officer, audit)
    alert, alerting = _apply_alert(
        db,
        borrower=borrower,
        assessment=assessment,
        observation=row,
        monitor=monitor,
        officer=officer,
        audit=audit,
    )
    db.commit()
    db.refresh(row)
    if alert is not None:
        db.refresh(alert)
    return _monitor_response(db, borrower, row, outcome, assessment, alert, alerting, monitor)


@router.post(
    "/observations/{observation_id}/correct",
    response_model=EWSMonitorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Correct a recorded month (manager or admin); the original is kept",
)
async def correct_observation(
    observation_id: int,
    payload: EWSCorrectionRequest,
    db: DbSession,
    monitor: Monitor,
    officer: Manager,
    audit: Audit,
) -> EWSMonitorResponse:
    """Add a corrected row for the same month and mark the original superseded.

    The original keeps every figure it was recorded with; the two rows point to
    each other. If the alert rested on the corrected month and the facility is
    no longer at WARNING or worse, the alert is closed with a note.
    """
    original = db.get(EWSTracking, observation_id, with_for_update=True)
    if original is None:
        raise HTTPException(
            status_code=404, detail=f"Observation {observation_id} was not found."
        )
    if original.record_status != "active":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Observation {observation_id} was already corrected by observation "
                f"{original.superseded_by_observation_id}; correct that one instead."
            ),
        )
    borrower = _load_facility(original.borrower_id, db)
    _require_approved_facility(borrower)
    observed = _observation_date(payload, borrower, original.observation_date)

    before = _state(original, _TRACKING_FIELDS)
    original.record_status = "superseded"
    db.flush()  # frees the month in the one-active-row-per-month index
    row, outcome = _new_observation(
        borrower=borrower,
        month_number=original.month_number,
        payload=payload,
        monitor=monitor,
        officer=officer,
        audit=audit,
        observed=observed,
    )
    row.supersedes_observation_id = original.id
    row.correction_reason = payload.correction_reason
    db.add(row)
    db.flush()
    original.superseded_by_observation_id = row.id
    assessment = _store_assessment(db, borrower, row)
    db.flush()
    audit_service.record(
        db,
        action=Action.EWS_OBSERVATION_CORRECTED,
        entity_type="ews_observation",
        entity_id=row.id,
        actor=officer,
        previous=before,
        new=_state(row, _TRACKING_FIELDS),
        details={
            "application_id": borrower.id,
            "supersedes_observation_id": original.id,
            "correction_reason": payload.correction_reason,
            "ews_state": assessment.state.value,
            "reason_codes": assessment.reason_codes,
        },
        context=audit,
    )
    audit_service.record(
        db,
        action=Action.EWS_OBSERVATION_SUPERSEDED,
        entity_type="ews_observation",
        entity_id=original.id,
        actor=officer,
        previous={"record_status": "active", "superseded_by_observation_id": None},
        new={"record_status": "superseded", "superseded_by_observation_id": row.id},
        details={"application_id": borrower.id, "correction_reason": payload.correction_reason},
        context=audit,
    )
    _audit_override(db, row, borrower, officer, audit)
    alert, alerting = _apply_alert(
        db,
        borrower=borrower,
        assessment=assessment,
        observation=row,
        monitor=monitor,
        officer=officer,
        audit=audit,
        corrected=original,
    )
    db.commit()
    db.refresh(row)
    if alert is not None:
        db.refresh(alert)
    return _monitor_response(db, borrower, row, outcome, assessment, alert, alerting, monitor)


@router.get(
    "/facilities/{facility_id}/observations",
    response_model=list[EWSTrackingResponse],
    summary="Every recorded month of a facility, corrections included",
)
async def list_observations(
    facility_id: int,
    db: DbSession,
    include_superseded: Annotated[bool, Query()] = True,
) -> list[EWSTrackingResponse]:
    """Oldest month first; within a month the original comes before its correction."""
    _load_facility(facility_id, db)
    statement = select(EWSTracking).where(EWSTracking.borrower_id == facility_id)
    if not include_superseded:
        statement = statement.where(EWSTracking.record_status == "active")
    rows = db.scalars(statement.order_by(EWSTracking.month_number, EWSTracking.id)).all()
    return [EWSTrackingResponse.model_validate(row) for row in rows]


@router.get(
    "/borrowers/{borrower_id}/history",
    response_model=list[EWSTrackingResponse],
    summary="Active monthly observations of a facility (pre-2.1 route)",
)
async def borrower_history(borrower_id: int, db: DbSession) -> list[EWSTrackingResponse]:
    """The current history, one row per month, oldest first. Superseded rows excluded."""
    _load_facility(borrower_id, db)
    return [
        EWSTrackingResponse.model_validate(row) for row in _active_observations(db, borrower_id)
    ]


@router.get(
    "/facilities/{facility_id}/trend",
    response_model=EWSTrend,
    summary="Baseline, latest, deterioration and trend direction",
)
async def facility_trend(facility_id: int, db: DbSession) -> EWSTrend:
    borrower = _load_facility(facility_id, db)
    rows = _active_observations(db, facility_id)
    trend = ews_engine.compute_trend(borrower.risk_score, rows)
    return _trend_response(borrower, trend, rows)


@router.get(
    "/facilities/{facility_id}/state",
    response_model=EWSFacilityState,
    summary="Current EWS state, signals and recommended actions",
)
async def facility_state(facility_id: int, db: DbSession) -> EWSFacilityState:
    borrower = _load_facility(facility_id, db)
    rows = _active_observations(db, facility_id)
    assessment = ews_engine.assess(ews_engine.facility_of(borrower), rows)
    alert = _open_alert(db, facility_id)
    return EWSFacilityState(
        facility_id=borrower.id,
        business_name=borrower.business_name,
        borrower_id=borrower.borrower_id,
        monitored=bool(rows),
        state=assessment.state,
        state_reasons=list(assessment.state_reasons),
        signals=_signals(assessment),
        recommended_actions=assessment.recommended_actions,
        trend=_trend_response(borrower, assessment.trend, rows),
        latest_observation=EWSTrackingResponse.model_validate(rows[-1]) if rows else None,
        open_alert=AlertResponse.model_validate(alert) if alert is not None else None,
    )


@router.get("/methodology", response_model=EWSMethodology, summary="EWS thresholds and caveats")
async def methodology() -> EWSMethodology:
    return EWSMethodology(**ews_engine.methodology())


@router.get("/overview", response_model=EWSOverview, summary="Portfolio EWS position")
async def overview(db: DbSession) -> EWSOverview:
    """Every approved facility with at least one recorded month, worst first."""
    rows_by_facility: dict[int, list[EWSTracking]] = {}
    for row in db.scalars(
        select(EWSTracking)
        .where(EWSTracking.record_status == "active")
        .order_by(EWSTracking.borrower_id, EWSTracking.month_number)
    ).all():
        rows_by_facility.setdefault(row.borrower_id, []).append(row)

    open_alerts = db.scalars(
        select(Alert).where(Alert.alert_status.in_(ALERT_OPEN_STATUSES))
    ).all()
    alerts_by_facility: dict[int, list[Alert]] = {}
    for alert in open_alerts:
        alerts_by_facility.setdefault(alert.borrower_id, []).append(alert)

    applications = (
        db.scalars(select(Application).where(Application.id.in_(list(rows_by_facility)))).all()
        if rows_by_facility
        else []
    )
    counts = {state.value: 0 for state in EWSState}
    out: list[EWSOverviewRow] = []
    for application in applications:
        if application.decision_status != "Approved":
            continue
        rows = rows_by_facility[application.id]
        assessment = ews_engine.assess(ews_engine.facility_of(application), rows)
        counts[assessment.state.value] += 1
        facility_alerts = alerts_by_facility.get(application.id, [])
        first = facility_alerts[0] if facility_alerts else None
        latest = rows[-1]
        trend = assessment.trend
        out.append(
            EWSOverviewRow(
                facility_id=application.id,
                business_name=application.business_name,
                borrower_id=application.borrower_id,
                baseline_score=trend.baseline_score,
                current_score=trend.latest_score,
                total_deterioration=trend.total_deterioration,
                recent_deterioration=trend.recent_deterioration,
                trend_direction=trend.direction,
                state=assessment.state,
                active_alerts=len(facility_alerts),
                open_alert_id=first.id if first else None,
                open_alert_status=first.alert_status if first else None,
                overdue=any(alert.is_overdue for alert in facility_alerts),
                observations=trend.observations,
                last_month_number=latest.month_number,
                last_observation_date=latest.observation_date,
                score_source=latest.score_source,
            )
        )
    out.sort(
        key=lambda r: (
            -ews_engine.STATE_RANK[r.state],
            -(r.total_deterioration or 0.0),
            r.facility_id,
        )
    )
    return EWSOverview(
        monitored_facilities=len(out),
        state_counts=counts,
        open_alerts=len(open_alerts),
        overdue_actions=sum(1 for alert in open_alerts if alert.is_overdue),
        rows=out,
        methodology=EWSMethodology(**ews_engine.methodology()),
    )


# --- timeline -------------------------------------------------------------------------

_EVENT_TITLES = {
    Action.APPLICATION_CREATED: "Application created",
    Action.APPLICATION_SCORED: "Application scored",
    Action.RECOMMENDATION_GENERATED: "Recommendation generated",
    Action.OFFICER_DECISION: "Officer decision recorded",
    Action.APPROVAL_DENIED: "Decision refused (authority)",
    Action.APPLICATION_ESCALATED: "Escalated to an admin",
    Action.APPLICATION_RESCORED: "Re-scored",
    Action.APPLICATION_SUPERSEDED: "Superseded by a re-score",
    Action.EXPLANATION_GENERATED: "Explanation generated",
    Action.EXPLANATION_RECOMPUTED: "Explanation recomputed",
    Action.EWS_OBSERVATION_CREATED: "Monthly observation recorded",
    Action.EWS_OBSERVATION_UPDATED: "Monthly observation overwritten (before 2.1)",
    Action.EWS_OBSERVATION_CORRECTED: "Monthly observation corrected",
    Action.EWS_OBSERVATION_SUPERSEDED: "Observation superseded by a correction",
    Action.EWS_SCORE_OVERRIDDEN: "Monitored score overridden by an officer",
    Action.EWS_SCORE_OVERRIDE_DENIED: "Score override refused (role)",
    Action.EWS_ALERT_CREATED: "Alert raised",
    Action.EWS_ALERT_UPDATED: "Alert updated by a later observation",
    Action.EWS_ALERT_ESCALATED: "Alert escalated",
    Action.EWS_ALERT_AUTO_RESOLVED: "Alert closed by a correction",
    Action.EWS_ALERT_TAKEN: "Alert taken for review (before 2.1)",
    Action.EWS_ALERT_ACKNOWLEDGED: "Alert acknowledged",
    Action.EWS_ALERT_ASSIGNED: "Alert assigned",
    Action.EWS_ALERT_DUE_DATE_SET: "Action due date set",
    Action.EWS_ALERT_ACTION_REQUIRED: "Action required",
    Action.EWS_ALERT_RESOLVED: "Alert resolved",
    Action.EWS_ALERT_DISMISSED: "Alert dismissed",
}


def _event_detail(entry: AuditLog) -> str | None:
    """A one-line summary of an audit entry, from its own stored fields."""
    new = entry.new_state or {}
    details = entry.details or {}
    if entry.entity_type == "ews_observation" and "month_number" in new:
        text = (
            f"Month {new['month_number']}: {new.get('installment_status')}, "
            f"score {new.get('monthly_score')}"
        )
        if new.get("score_source"):
            text += f" ({new['score_source']})"
        if details.get("ews_state"):
            text += f"; state {details['ews_state']}"
        return text
    if entry.entity_type == "ews_observation" and "score_source" in new:
        return (
            f"Score {new.get('monthly_score')} replaces rule score "
            f"{(entry.previous_state or {}).get('monthly_score')}: {new.get('override_reason')}"
        )
    if entry.entity_type == "ews_alert":
        bits = []
        if new.get("alert_status"):
            bits.append(f"status {new['alert_status']}")
        if new.get("severity"):
            bits.append(f"severity {new['severity']}")
        if details.get("reason_codes"):
            bits.append(", ".join(details["reason_codes"]))
        if details.get("note"):
            bits.append(f"note: {details['note']}")
        elif new.get("resolution_note") and new.get("alert_status") in ("Resolved", "Dismissed"):
            bits.append(f"note: {new['resolution_note']}")
        return "; ".join(bits) or None
    if new.get("decision_status"):
        return f"decision status {new['decision_status']}"
    return None


@router.get(
    "/facilities/{facility_id}/timeline",
    response_model=FacilityTimeline,
    summary="Stored events of a facility, oldest first",
)
async def facility_timeline(facility_id: int, db: DbSession) -> FacilityTimeline:
    """Built only from the audit trail and stored rows; nothing is inferred."""
    borrower = _load_facility(facility_id, db)
    observations = db.scalars(
        select(EWSTracking).where(EWSTracking.borrower_id == facility_id)
    ).all()
    alerts = db.scalars(select(Alert).where(Alert.borrower_id == facility_id)).all()
    obs_ids = [str(row.id) for row in observations]
    alert_ids = [str(alert.id) for alert in alerts]

    clauses = [
        (AuditLog.entity_type == "application") & (AuditLog.entity_id == str(facility_id))
    ]
    if obs_ids:
        clauses.append(
            (AuditLog.entity_type == "ews_observation") & AuditLog.entity_id.in_(obs_ids)
        )
    if alert_ids:
        clauses.append((AuditLog.entity_type == "ews_alert") & AuditLog.entity_id.in_(alert_ids))
    entries = db.scalars(
        select(AuditLog).where(or_(*clauses)).order_by(AuditLog.occurred_at, AuditLog.id)
    ).all()

    events: list[TimelineEvent] = [
        TimelineEvent(
            occurred_at=entry.occurred_at,
            kind=entry.action,
            title=_EVENT_TITLES.get(entry.action, entry.action),
            detail=_event_detail(entry),
            actor=entry.username,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            source="audit_log",
        )
        for entry in entries
    ]
    audited = {(entry.entity_type, entry.entity_id, entry.action) for entry in entries}
    audited_entities = {(entry.entity_type, entry.entity_id) for entry in entries}

    # Rows from before the audit trail: their own stored times, nothing invented.
    record_events: list[TimelineEvent] = []
    if ("application", str(facility_id), Action.APPLICATION_CREATED) not in audited:
        record_events.append(
            TimelineEvent(
                occurred_at=borrower.created_at,
                kind="record.application_scored",
                title="Application scored (stored record)",
                detail=f"Score {borrower.risk_score:g}; recommendation {borrower.decision}",
                actor=borrower.scored_by,
                entity_type="application",
                entity_id=str(facility_id),
                source="record",
            )
        )
    if (
        borrower.reviewed_at is not None
        and ("application", str(facility_id), Action.OFFICER_DECISION) not in audited
    ):
        record_events.append(
            TimelineEvent(
                occurred_at=borrower.reviewed_at,
                kind="record.officer_decision",
                title="Officer decision (stored record)",
                detail=str(borrower.review_decision),
                actor=borrower.reviewed_by,
                entity_type="application",
                entity_id=str(facility_id),
                source="record",
            )
        )
    for row in sorted(observations, key=lambda r: (r.month_number, r.id)):
        if ("ews_observation", str(row.id)) not in audited_entities:
            record_events.append(
                TimelineEvent(
                    occurred_at=row.created_at,
                    kind="record.observation",
                    title=f"Month {row.month_number} observation (stored record)",
                    detail=(
                        f"{row.installment_status}, score {row.monthly_score:g}; "
                        "recorded before the audit trail"
                    ),
                    actor=row.created_by,
                    entity_type="ews_observation",
                    entity_id=str(row.id),
                    source="record",
                )
            )
    for alert in alerts:
        if ("ews_alert", str(alert.id)) not in audited_entities:
            record_events.append(
                TimelineEvent(
                    occurred_at=alert.triggered_at,
                    kind="record.alert_raised",
                    title="Alert raised (stored record)",
                    detail=f"Score drop {alert.score_drop:g}",
                    entity_type="ews_alert",
                    entity_id=str(alert.id),
                    source="record",
                )
            )
            if alert.resolved_at is not None:
                record_events.append(
                    TimelineEvent(
                        occurred_at=alert.resolved_at,
                        kind="record.alert_closed",
                        title=f"Alert {alert.alert_status.lower()} (stored record)",
                        detail=alert.resolution_note,
                        actor=alert.resolved_by,
                        entity_type="ews_alert",
                        entity_id=str(alert.id),
                        source="record",
                    )
                )

    def _key(event: TimelineEvent) -> datetime:
        moment = event.occurred_at or borrower.created_at
        return moment.replace(tzinfo=None) if moment.tzinfo else moment

    merged = sorted(events + record_events, key=_key)
    note = None
    if record_events:
        note = (
            "Some events predate the audit trail (added in 1.10). They are read "
            "from the stored rows; a blank time means the row kept none."
        )
    return FacilityTimeline(
        facility_id=borrower.id, business_name=borrower.business_name, events=merged, note=note
    )


# --- alerts -------------------------------------------------------------------------


@router.get("/alerts", response_model=list[AlertResponse], summary="List EWS alerts")
async def list_alerts(
    db: DbSession,
    alert_status: Annotated[
        AlertStatus | None, Query(description="Filter by alert lifecycle status.")
    ] = None,
    severity: Annotated[AlertSeverity | None, Query()] = None,
    facility_id: Annotated[int | None, Query(gt=0)] = None,
    open_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AlertResponse]:
    """Open alerts first, then worst severity and largest drop. Closed alerts stay listed."""
    statement = select(Alert).options(selectinload(Alert.borrower))
    if alert_status is not None:
        statement = statement.where(Alert.alert_status == alert_status.value)
    if severity is not None:
        statement = statement.where(Alert.severity == severity.value)
    if facility_id is not None:
        statement = statement.where(Alert.borrower_id == facility_id)
    if open_only:
        statement = statement.where(Alert.alert_status.in_(ALERT_OPEN_STATUSES))
    alerts = list(db.scalars(statement).all())
    alerts.sort(
        key=lambda a: (
            0 if a.is_open else 1,
            -_severity_rank(a.severity),
            -(a.score_drop or 0.0),
            -a.triggered_at.timestamp(),
            -a.id,
        )
    )
    return [AlertResponse.model_validate(alert) for alert in alerts[offset : offset + limit]]


@router.get("/alerts/{alert_id}", response_model=AlertResponse, summary="One alert")
async def get_alert(alert_id: int, db: DbSession) -> AlertResponse:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} was not found.")
    return AlertResponse.model_validate(alert)


@router.get(
    "/alerts/{alert_id}/history",
    response_model=list[AuditLogResponse],
    summary="Every recorded change of an alert, oldest first",
)
async def alert_history(alert_id: int, db: DbSession) -> list[AuditLogResponse]:
    if db.get(Alert, alert_id) is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} was not found.")
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "ews_alert", AuditLog.entity_id == str(alert_id))
        .order_by(AuditLog.occurred_at, AuditLog.id)
    ).all()
    return [AuditLogResponse.model_validate(entry) for entry in entries]


def _load_open_alert(alert_id: int, db: Session) -> Alert:
    """Fetch an alert that is still open, or raise ``404`` / ``409``."""
    alert = db.get(Alert, alert_id, with_for_update=True)
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} was not found.",
        )
    if not alert.is_open:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Alert {alert_id} is already {alert.alert_status} by "
                f"{alert.resolved_by or 'an officer'}; a closed alert does not reopen."
            ),
        )
    return alert


def _transition(
    db: Session,
    alert: Alert,
    before: dict,
    *,
    action: str,
    officer: User,
    audit: AuditContext,
    note: str | None,
) -> AlertResponse:
    """Audit a lifecycle change already made to ``alert`` and commit both."""
    db.flush()
    audit_service.record(
        db,
        action=action,
        entity_type="ews_alert",
        entity_id=alert.id,
        actor=officer,
        previous=before,
        new=_state(alert, _LIFECYCLE_FIELDS),
        details={"application_id": alert.borrower_id, "note": note},
        context=audit,
    )
    db.commit()
    db.refresh(alert)
    return AlertResponse.model_validate(alert)


def _check_due_date(due: date | None) -> None:
    if due is not None and due < utcnow().date():
        raise HTTPException(status_code=422, detail="The due date cannot be in the past.")


def _resolve_assignee(db: Session, username: str) -> str:
    """An alert is assigned to an existing officer account only."""
    user = db.scalars(select(User).where(User.username == username)).first()
    if user is None:
        raise HTTPException(status_code=422, detail=f"No officer named {username!r}.")
    return user.username


@router.post(
    "/alerts/{alert_id}/acknowledge",
    response_model=AlertResponse,
    summary="Acknowledge an Open alert (manager or admin)",
)
async def acknowledge_alert(
    alert_id: int,
    db: DbSession,
    officer: Manager,
    audit: Audit,
    body: AlertNoteRequest | None = None,
) -> AlertResponse:
    alert = _load_open_alert(alert_id, db)
    if alert.alert_status != AlertStatus.OPEN.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Alert {alert_id} was already acknowledged by "
                f"{alert.acknowledged_by or 'an officer'}."
            ),
        )
    before = _state(alert, _LIFECYCLE_FIELDS)
    alert.alert_status = AlertStatus.ACKNOWLEDGED.value
    alert.acknowledged_at = utcnow()
    alert.acknowledged_by = officer.username
    return _transition(
        db, alert, before, action=Action.EWS_ALERT_ACKNOWLEDGED, officer=officer, audit=audit,
        note=body.note if body else None,
    )


@router.patch(
    "/alerts/{alert_id}/review",
    response_model=AlertResponse,
    summary="Take an alert: acknowledge it and assign it to yourself (pre-2.1 route)",
)
async def review_alert(
    alert_id: int, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    """Acknowledge if Open and take it, unless someone else holds it (``409``)."""
    alert = _load_open_alert(alert_id, db)
    if alert.assigned_to not in (None, officer.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Alert {alert_id} is already assigned to {alert.assigned_to}.",
        )
    if alert.alert_status != AlertStatus.OPEN.value and alert.assigned_to == officer.username:
        return AlertResponse.model_validate(alert)  # already yours: nothing changes
    before = _state(alert, _LIFECYCLE_FIELDS)
    now = utcnow()
    if alert.alert_status == AlertStatus.OPEN.value:
        alert.alert_status = AlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = now
        alert.acknowledged_by = officer.username
    alert.assigned_to = officer.username
    alert.assigned_by = officer.username
    alert.assigned_at = now
    return _transition(
        db, alert, before, action=Action.EWS_ALERT_ACKNOWLEDGED, officer=officer, audit=audit,
        note="Taken for review",
    )


@router.post(
    "/alerts/{alert_id}/assign",
    response_model=AlertResponse,
    summary="Assign the follow-up to an officer (manager or admin)",
)
async def assign_alert(
    alert_id: int, body: AlertAssignRequest, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    alert = _load_open_alert(alert_id, db)
    assignee = _resolve_assignee(db, body.assigned_to)
    _check_due_date(body.due_date)
    before = _state(alert, _LIFECYCLE_FIELDS)
    alert.assigned_to = assignee
    alert.assigned_by = officer.username
    alert.assigned_at = utcnow()
    if body.due_date is not None:
        alert.action_due_date = body.due_date
    return _transition(
        db, alert, before, action=Action.EWS_ALERT_ASSIGNED, officer=officer, audit=audit,
        note=body.note,
    )


@router.post(
    "/alerts/{alert_id}/due-date",
    response_model=AlertResponse,
    summary="Set when the follow-up is due (manager or admin)",
)
async def set_due_date(
    alert_id: int, body: AlertDueDateRequest, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    alert = _load_open_alert(alert_id, db)
    _check_due_date(body.due_date)
    before = _state(alert, _LIFECYCLE_FIELDS)
    alert.action_due_date = body.due_date
    return _transition(
        db, alert, before, action=Action.EWS_ALERT_DUE_DATE_SET, officer=officer, audit=audit,
        note=body.note,
    )


@router.post(
    "/alerts/{alert_id}/action-required",
    response_model=AlertResponse,
    summary="Mark an acknowledged alert Action Required (manager or admin)",
)
async def require_action(
    alert_id: int, body: AlertActionRequest, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    alert = _load_open_alert(alert_id, db)
    if alert.alert_status == AlertStatus.OPEN.value:
        raise HTTPException(status_code=409, detail=f"Acknowledge alert {alert_id} first.")
    if alert.alert_status == AlertStatus.ACTION_REQUIRED.value:
        raise HTTPException(
            status_code=409, detail=f"Alert {alert_id} is already Action Required."
        )
    assignee = _resolve_assignee(db, body.assigned_to) if body.assigned_to else None
    _check_due_date(body.due_date)
    before = _state(alert, _LIFECYCLE_FIELDS)
    alert.alert_status = AlertStatus.ACTION_REQUIRED.value
    alert.action_note = body.action_note
    if assignee is not None:
        alert.assigned_to = assignee
        alert.assigned_by = officer.username
        alert.assigned_at = utcnow()
    if body.due_date is not None:
        alert.action_due_date = body.due_date
    return _transition(
        db, alert, before, action=Action.EWS_ALERT_ACTION_REQUIRED, officer=officer, audit=audit,
        note=body.action_note,
    )


def _close(
    alert_id: int,
    note: str,
    new_status: AlertStatus,
    action: str,
    db: Session,
    officer: User,
    audit: AuditContext,
) -> AlertResponse:
    alert = _load_open_alert(alert_id, db)
    before = _state(alert, _LIFECYCLE_FIELDS)
    alert.alert_status = new_status.value
    alert.resolved_at = utcnow()
    alert.resolved_by = officer.username
    alert.resolution_note = note
    return _transition(db, alert, before, action=action, officer=officer, audit=audit, note=note)


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Resolve an alert with a note (manager or admin)",
)
@router.patch(
    "/alerts/{alert_id}/resolve",
    response_model=AlertResponse,
    summary="Resolve an alert with a note (pre-2.1 route)",
)
async def resolve_alert(
    alert_id: int, body: AlertResolveRequest, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    """Close an alert, recording who closed it, when and what was done. It stays listed."""
    return _close(
        alert_id, body.note, AlertStatus.RESOLVED, Action.EWS_ALERT_RESOLVED, db, officer, audit
    )


@router.post(
    "/alerts/{alert_id}/dismiss",
    response_model=AlertResponse,
    summary="Dismiss an alert, e.g. one raised on a data-entry error (manager or admin)",
)
async def dismiss_alert(
    alert_id: int, body: AlertResolveRequest, db: DbSession, officer: Manager, audit: Audit
) -> AlertResponse:
    return _close(
        alert_id, body.note, AlertStatus.DISMISSED, Action.EWS_ALERT_DISMISSED, db, officer, audit
    )
