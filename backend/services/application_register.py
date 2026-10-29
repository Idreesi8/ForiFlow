"""Read-only, complete-register lookup with bounded pages and stable ordering."""
from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from models.database import Application, Borrower
from schemas import ApplicationRegister, ApplicationRegisterItem

SORT_COLUMNS = {
    'id': Application.id, 'applicant_name': func.lower(Application.applicant_name),
    'business_name': func.lower(Application.business_name), 'loan_amount_pkr': Application.loan_amount_pkr,
    'tenure_months': Application.tenure_months, 'risk_score': Application.risk_score,
    'decision': case((Application.decision == 'Approved', 'Approve'),
                     (Application.decision == 'Rejected', 'Decline'), else_='Manual Review'),
    'final': Application.decision_status, 'created_at': Application.created_at,
}


def build_register(db: Session, *, search='', status=None, sort='created_at', direction='desc', limit=25, offset=0):
    conditions = []
    term = search.strip().lower()
    if term:
        # LIKE metacharacters are literal user text, never wildcard instructions.
        pattern = '%' + term.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        names = [func.lower(column).like(pattern, escape='!')
                 for column in (Application.applicant_name, Application.business_name, Borrower.public_id)]
        identifier = term.removeprefix('#')
        if identifier.isascii() and identifier.isdecimal() and len(identifier) <= 18:
            names.append(Application.id == int(identifier))
        conditions.append(or_(*names))
    if status == 'Awaiting decision':
        conditions.append(Application.decision_status.in_(['Pending', 'Escalated']))
    elif status:
        conditions.append(Application.decision_status == status)
    matches = and_(*conditions) if conditions else true()
    total, matching = db.execute(select(func.count(Application.id),
        func.coalesce(func.sum(case((matches, 1), else_=0)), 0))
        .select_from(Application).outerjoin(Borrower, Application.borrower_id == Borrower.id)).one()
    column = SORT_COLUMNS[sort]
    order = column.desc() if direction == 'desc' else column.asc()
    rows = db.execute(select(Application.id, Borrower.public_id.label('borrower_public_id'),
        Application.applicant_name, Application.business_name, Application.loan_amount_pkr,
        Application.tenure_months, Application.risk_score, Application.decision,
        Application.decision_status, Application.reviewed_by, Application.created_at)
        .outerjoin(Borrower, Application.borrower_id == Borrower.id).where(matches)
        .order_by(order, Application.id.desc()).offset(offset).limit(limit)).mappings()
    return ApplicationRegister(items=[ApplicationRegisterItem.model_validate(dict(row)) for row in rows],
        total=total, matching=matching, offset=offset, limit=limit)
