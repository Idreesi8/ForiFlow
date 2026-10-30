"""Complete alert lookup with bounded database pages and scope-wide counts."""
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import selectinload

from business_time import business_date
from models.database import ALERT_OPEN_STATUSES, Alert, Application
from schemas import AlertResponse


def alert_scope(*, search='', severity=None, facility_id=None):
    statement = select(Alert).join(Application, Alert.borrower_id == Application.id)
    if facility_id is not None:
        statement = statement.where(Alert.borrower_id == facility_id)
    if severity is not None:
        statement = statement.where(Alert.severity == severity)
    term = search.strip().lower()
    if term:
        pattern = '%' + term.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        terms = [func.lower(column).like(pattern, escape='!')
                 for column in (Application.business_name, Application.applicant_name)]
        identifier = term.removeprefix('#')
        if identifier.isascii() and identifier.isdecimal() and len(identifier) <= 18:
            terms.append(Alert.borrower_id == int(identifier))
        statement = statement.where(or_(*terms))
    return statement


def alert_page(db, statement, *, alert_status=None, open_only=False, limit=25, offset=0):
    if alert_status is not None:
        statement = statement.where(Alert.alert_status == alert_status)
    if open_only:
        statement = statement.where(Alert.alert_status.in_(ALERT_OPEN_STATUSES))
    matching = db.scalar(select(func.count()).select_from(statement.subquery()))
    ordered = statement.options(selectinload(Alert.borrower)).order_by(
        case((Alert.alert_status.in_(ALERT_OPEN_STATUSES), 0), else_=1),
        case((Alert.severity == 'CRITICAL', 2), (Alert.severity == 'WARNING', 1), else_=0).desc(),
        func.coalesce(Alert.score_drop, 0).desc(), Alert.triggered_at.desc(), Alert.id.desc(),
    )
    items = [AlertResponse.model_validate(row) for row in db.scalars(ordered.offset(offset).limit(limit))]
    return items, matching


def build_alert_queue(db, *, search='', severity=None, facility_id=None,
                      alert_status=None, open_only=False, limit=25, offset=0):
    scope = alert_scope(search=search, severity=severity, facility_id=facility_id)
    scoped = scope.subquery()
    opened = scoped.c.alert_status.in_(ALERT_OPEN_STATUSES)
    def count_when(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
    total, open_count, critical, overdue, worst_drop = db.execute(select(
        func.count(), count_when(opened),
        count_when(opened & (scoped.c.severity == 'CRITICAL')),
        count_when(opened & (scoped.c.action_due_date < business_date())),
        func.max(case((opened, scoped.c.score_drop))),
    ).select_from(scoped)).one()
    items, matching = alert_page(db, scope, alert_status=alert_status, open_only=open_only,
                                 limit=limit, offset=offset)
    return dict(items=items, total=total, matching=matching, limit=limit, offset=offset,
                counts=dict(open=open_count, critical=critical, overdue=overdue,
                            closed=total-open_count, worst_open_drop=worst_drop))
