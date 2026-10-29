"""A read-only officer work list derived from recorded workflow evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from business_time import as_utc, business_date, utc_now

from models.database import ALERT_OPEN_STATUSES, Alert, Application, EWSTracking
from schemas import ActionDeskItem, ActionDeskResponse

ORDERING = [
    'Overdue open alert actions', 'Other critical open alerts', 'Other open alerts',
    'Escalated assessments', 'Pending assessments', 'Gaps between recorded monitoring months',
    'Recorded months with unknown payment amounts', 'Approved facilities without monitoring records',
]
NOTES = [
    'Priority follows the published workflow order, then the oldest recorded date and a stable case reference. It is not a credit score or a default prediction.',
    'One facility can have several tasks. Task counts are not facility counts. Review tasks exclude completed and superseded assessments; alert tasks exclude closed alerts.',
    'Missing monitoring records or amounts do not prove missed payment. Verify the source records before contacting a borrower.',
    'This is a snapshot. Refresh after completing work. No decision, alert or payment record is changed by opening this desk.',
    'Role filtering uses the signed-in officer\'s current account role. It does not mean a task is assigned to that officer or that every decision is authorised; case-specific approval limits and all action permissions still apply.',
]

TASK_ROLES = {
    'any_officer': frozenset({'analyst', 'manager', 'admin'}),
    'manager_or_admin': frozenset({'manager', 'admin'}),
    'admin': frozenset({'admin'}),
}


def build_action_desk(db: Session, *, now: datetime | None = None, limit: int = 25,
                      offset: int = 0, kind: str | None = None, priority: str | None = None,
                      search: str | None = None, actionable_only: bool = False,
                      officer_role: str | None = None) -> ActionDeskResponse:
    captured = as_utc(now if now is not None else utc_now())
    today = business_date(captured)
    applications = db.execute(select(
        Application.id, Application.business_name, Application.decision_status,
        Application.created_at, Application.escalated_at, Application.reviewed_at,
        Application.tenure_months,
    ).where(Application.decision_status.in_(['Pending', 'Escalated', 'Approved']))).all()
    ranked: list[tuple[int, ActionDeskItem]] = []
    for app in applications:
        if app.decision_status not in ('Pending', 'Escalated'):
            continue
        escalated = app.decision_status == 'Escalated'
        opened = as_utc((app.escalated_at if escalated else None) or app.created_at)
        waiting = max((today - business_date(opened)).days, 0)
        ranked.append((3 if escalated else 4, ActionDeskItem(
            id=f'review:{app.id}', kind='review', priority='attention' if escalated else 'routine',
            application_id=app.id, business_name=app.business_name,
            title='Review escalated assessment' if escalated else 'Record an officer decision',
            reason=f'{app.decision_status} assessment; no final officer decision is recorded.',
            evidence=[f'{waiting} calendar days since ' + ('escalation.' if escalated else 'assessment.'),
                      'Open the assessment to review evidence and the recorded policy before deciding.'],
            opened_at=opened, required_role='admin' if escalated else 'manager_or_admin',
        )))

    alerts = db.execute(select(
        Alert.id, Alert.borrower_id, Alert.triggered_at, Alert.action_due_date,
        Alert.severity, Alert.assigned_to, Alert.alert_status, Application.business_name,
    ).join(Application, Application.id == Alert.borrower_id).where(
        Application.decision_status == 'Approved', Alert.alert_status.in_(ALERT_OPEN_STATUSES),
    )).all()
    for alert in alerts:
        overdue = alert.action_due_date is not None and alert.action_due_date < today
        rank = 0 if overdue else 1 if alert.severity == 'CRITICAL' else 2
        evidence = [f'Alert #{alert.id}: {alert.alert_status}.',
                    f'Severity: {alert.severity}.' if alert.severity else 'Legacy alert: no recorded severity.']
        if overdue:
            evidence.append(f'Action deadline passed {(today - alert.action_due_date).days} calendar days ago.')
        elif alert.action_due_date:
            evidence.append(f'Action deadline: {alert.action_due_date.isoformat()}.')
        evidence.append(f'Assigned to {alert.assigned_to}.' if alert.assigned_to else 'No follow-up owner is assigned.')
        ranked.append((rank, ActionDeskItem(
            id=f'alert:{alert.id}', kind='alert', priority='urgent' if rank < 2 else 'attention',
            application_id=alert.borrower_id, business_name=alert.business_name,
            title='Follow up overdue alert' if overdue else 'Review critical alert' if rank == 1 else 'Review open alert',
            reason='An open EWS alert needs officer follow-up.', evidence=evidence,
            opened_at=as_utc(alert.triggered_at), due_date=alert.action_due_date,
            assigned_to=alert.assigned_to, alert_id=alert.id, required_role='manager_or_admin',
        )))

    observations = defaultdict(list)
    for row in db.execute(select(
        EWSTracking.borrower_id, EWSTracking.month_number, EWSTracking.amount_paid_pkr,
    ).join(Application, Application.id == EWSTracking.borrower_id).where(
        Application.decision_status == 'Approved', EWSTracking.record_status == 'active',
    )):
        observations[row.borrower_id].append(row)
    for app in applications:
        if app.decision_status != 'Approved':
            continue
        rows = observations[app.id]
        coverage = {row.month_number for row in rows}
        last = max(coverage, default=0)
        missing = [month for month in range(1, min(last, app.tenure_months) + 1) if month not in coverage]
        unknown = sum(row.amount_paid_pkr is None for row in rows)
        if rows and not missing and not unknown:
            continue
        rank = 5 if missing else 6 if unknown else 7
        evidence = [f'{len(coverage)} active monthly observations recorded.']
        if missing:
            evidence.append(f'{len(missing)} earlier monitoring months missing; first gap is month {missing[0]}. Later records do not fill that gap.')
        if unknown:
            evidence.append(f'{unknown} recorded months have an unknown payment amount; unknown is not zero.')
        evidence.append('Check the monitoring history and source receipts. This is not a payment demand.')
        ranked.append((rank, ActionDeskItem(
            id=f'monitoring:{app.id}', kind='monitoring', priority='routine',
            application_id=app.id, business_name=app.business_name,
            title='Fill monitoring gaps' if missing else 'Verify unknown payment amounts' if unknown else 'Start facility monitoring',
            reason='The monitoring record is incomplete.', evidence=evidence,
            opened_at=as_utc(app.reviewed_at or app.created_at),
            first_missing_month=missing[0] if missing else 1 if not rows else None,
            required_role='manager_or_admin' if unknown and not missing else 'any_officer',
        )))

    ranked.sort(key=lambda pair: (pair[0], pair[1].opened_at, pair[1].application_id, pair[1].id))
    all_items = [item for _, item in ranked]
    actionable_ids = {item.id for item in all_items if officer_role in TASK_ROLES[item.required_role]}
    terms = (search or '').strip().casefold()
    selected = [item for item in all_items if
                (not actionable_only or item.id in actionable_ids) and
                (kind is None or item.kind == kind) and (priority is None or item.priority == priority) and
                (not terms or terms in f'{item.business_name} {item.application_id} {item.assigned_to or ""}'.casefold())]
    by_kind, by_priority = Counter(item.kind for item in all_items), Counter(item.priority for item in all_items)
    return ActionDeskResponse(
        as_of=captured, total_tasks=len(all_items), matching_tasks=len(selected),
        application_count=len({item.application_id for item in all_items}),
        officer_role=officer_role, actionable_only=actionable_only, actionable_tasks=len(actionable_ids),
        counts_by_kind={key: by_kind[key] for key in ('alert', 'review', 'monitoring')},
        counts_by_priority={key: by_priority[key] for key in ('urgent', 'attention', 'routine')},
        offset=offset, limit=limit, items=selected[offset:offset + limit], ordering=ORDERING, notes=NOTES,
    )
