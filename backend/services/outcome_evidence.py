"""Read-only repayment evidence inventory, separate from predictive performance.

The window keeps the application's recorded officer-approval anchor. The separate
repayment calendar's officer-entered dates are not silently substituted for
existing reporting-month definitions. Complete evidence is not a validated target,
default, causal effect, accuracy result, or permission to retrain.
"""
import calendar
import math
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select

from business_time import as_utc, business_date, utc_now
from models.database import Application, Borrower, EWSTracking
from outcome_schemas import OutcomeCase, OutcomeCounts, OutcomeEvidence
from schemas import DAYS_LATE_RANGE, InstallmentStatus

STATUSES = ('needs_approval_record', 'shorter_term', 'collecting', 'needs_evidence', 'covered')
BASIS = 'First N reporting months, dated from recorded officer approval; approval is a proxy, not a recorded disbursement date.'
LIMITS = [
    'Coverage describes officer-entered records, not independently verified payments or a model accuracy result.',
    'Missing or incomplete months are unknown, not evidence of repayment or default. A later record never fills an earlier gap.',
    'A recorded 30+ day delay is a monitoring signal, not a lender-agreed default label. Complete coverage does not establish a default definition or outcome horizon.',
    'Only approved facilities have repayment evidence here. Rejected and undecided cases have no observed loan outcome; this selection limits conclusions about all applicants.',
    'Repeat facilities for the same borrower must stay together in validation splits, and later originations must be tested separately from earlier training data.',
    'No independent disbursement date, validated default target or training authorisation is established by this report. No model is retrained or promoted.',
]


def anniversary(start, number):
    index = start.month - 1 + number
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def record_issues(row, due, captured):
    issues = []
    today = business_date(captured)
    if row.observation_date is None:
        issues.append('Observation date missing')
    elif row.observation_date < due:
        issues.append('Observation predates its approval-based month anniversary')
    elif row.observation_date > today:
        issues.append('Observation date is in the future')
    if not (row.created_by or '').strip() or row.created_at is None or row.score_source == 'legacy_unknown':
        issues.append('Recording provenance incomplete')
    elif as_utc(row.created_at) > captured:
        issues.append('Record timestamp is in the future')
    elif row.observation_date is not None and business_date(row.created_at) < row.observation_date:
        issues.append('Record timestamp predates its observation date')
    amount = row.amount_paid_pkr
    if amount is None:
        issues.append('Payment amount unknown')
    elif not math.isfinite(amount) or amount < 0:
        issues.append('Payment amount invalid')
    try:
        low, high = DAYS_LATE_RANGE[InstallmentStatus(row.installment_status)]
        late = row.days_late
        if late is None:
            issues.append('Exact days late unknown')
        elif not low <= late <= (high if high is not None else 3650):
            issues.append('Days late conflict with payment status')
    except ValueError:
        issues.append('Payment status unsupported')
    return issues


def build_outcome_evidence(db, *, horizon=3, limit=10, offset=0, status_filter=None, now=None):
    if horizon not in (3, 6, 12) or status_filter not in (*STATUSES, None):
        raise ValueError('Unsupported evidence window or status')
    captured = as_utc(now if now is not None else utc_now())
    today = business_date(captured)
    # Read only the fields needed; no relationship loads, identity inference,
    # per-facility queries, CSV reconstruction, model calls or database writes.
    cases = db.execute(select(Application.id, Application.business_name,
        Application.borrower_id, Borrower.id.label('linked_borrower_id'), Borrower.public_id, Application.model_version,
        Application.scoring_engine, Application.reviewed_at, Application.reviewed_by, Application.decision_source,
        Application.tenure_months).outerjoin(Borrower, Borrower.id == Application.borrower_id)
        .where(Application.decision_status == 'Approved').order_by(Application.id)).all()
    observations = defaultdict(dict)
    for row in db.execute(select(EWSTracking.borrower_id, EWSTracking.month_number,
        EWSTracking.observation_date, EWSTracking.created_at, EWSTracking.created_by,
        EWSTracking.score_source, EWSTracking.amount_paid_pkr, EWSTracking.days_late,
        EWSTracking.installment_status).join(Application, Application.id == EWSTracking.borrower_id)
        .where(Application.decision_status == 'Approved', EWSTracking.record_status == 'active',
               EWSTracking.month_number.between(1, horizon))):
        observations[row.borrower_id][row.month_number] = row
    result = []
    groups = Counter(case.linked_borrower_id for case in cases if case.linked_borrower_id is not None)
    for case in cases:
        anchor = business_date(case.reviewed_at) if case.reviewed_at is not None else None
        records = observations[case.id]
        missing = [month for month in range(1, horizon + 1) if month not in records]
        incomplete, reasons, usable, late = [], [], 0, False
        end = anniversary(anchor, horizon) if anchor else None
        for number, row in sorted(records.items()):
            issues = record_issues(row, anniversary(anchor, number), captured) if anchor else ['Approval date missing']
            if issues:
                incomplete.append(number)
                reasons.extend(f'Month {number}: {issue}.' for issue in issues)
            else:
                usable += 1
                late = late or row.days_late >= 30
        if anchor is None or as_utc(case.reviewed_at) > captured or case.decision_source != 'officer' or not (case.reviewed_by or '').strip():
            state = 'needs_approval_record'
            reasons.insert(0, 'A dated officer approval is required; a recommendation or legacy automatic decision is not a verified approval anchor.')
        elif case.tenure_months < horizon:
            state = 'shorter_term'
            reasons.insert(0, 'Facility tenure is shorter than the selected reporting window.')
        elif end > today:
            state = 'collecting'
            reasons.insert(0, f'The approval-based window reaches month {horizon} on {end.isoformat()}.')
        elif missing or incomplete:
            state = 'needs_evidence'
            if missing:
                reasons.insert(0, 'Missing reporting months: ' + ', '.join(map(str, missing)) + '.')
        else:
            state = 'covered'
            reasons = ['Every selected month has dated recording provenance, a payment amount and consistent exact days late. Source accuracy is not independently verified.']
        result.append(OutcomeCase(application_id=case.id, business_name=case.business_name,
            borrower_public_id=case.public_id, model_version=case.model_version,
            scoring_engine=case.scoring_engine, status=state, window_end=end,
            recorded_months=len(records), usable_months=usable, missing_months=missing,
            incomplete_months=incomplete, reasons=reasons, recorded_30_plus=late))
    states = Counter(row.status for row in result)
    counts = OutcomeCounts(approved_facilities=len(cases), **{state: states[state] for state in STATUSES},
        covered_with_30_plus=sum(row.status == 'covered' and row.recorded_30_plus for row in result),
        distinct_linked_borrowers=len(groups), additional_repeat_facilities=sum(n-1 for n in groups.values()),
        unlinked_facilities=sum(case.linked_borrower_id is None for case in cases))
    filtered = [row for row in result if status_filter is None or row.status == status_filter]
    return OutcomeEvidence(captured_at=captured, as_of_date=today, horizon_months=horizon,
        basis=BASIS, limits=LIMITS, counts=counts, total=len(filtered), limit=limit,
        offset=offset, status_filter=status_filter, rows=filtered[offset:offset+limit])
