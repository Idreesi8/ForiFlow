"""Dated contract tracking using integer paisa and explicit receipt allocations.

No interest assumptions, automatic allocation, default labels or model changes.
Writes share the access-change lock and lock the facility before checking balances.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from business_time import as_utc, business_date, utc_now
from models.database import Application, RepaymentReceipt, RepaymentSchedule
from services import audit_service
from services.team_access import lock_officer_change

MANAGERS = frozenset({'admin', 'manager'})
OFFICERS = MANAGERS | {'analyst'}
LIMITS = [
    'Dates and amounts are officer-recorded from the loan agreement and payment evidence; there is no live bank feed or independent payment verification.',
    'Amounts are contractual scheduled amounts, not a principal balance, interest calculation or settlement quote. Receipts are allocated explicitly, never automatically.',
    'Overdue means unpaid according to this recorded schedule, in Pakistan calendar days. It is not a regulatory default or NPL classification.',
    'This calendar does not alter the credit score, monthly EWS observations, alerts or officer decision.',
    'The current calendar uses all recorded receipts, including backdated entries. It is not a reconstruction of what was known at an earlier time.',
]


def minor(amount):
    return int(Decimal(amount) * 100)


def money(value):
    return format(Decimal(value) / 100, '.2f')


def facility(db, key, *, locked=False):
    row = db.scalar(select(Application).where(Application.id == key).with_for_update()) if locked else db.get(Application, key)
    if row is None:
        raise HTTPException(404, 'Facility not found.')
    if row.decision_status != 'Approved':
        raise HTTPException(409, 'A recorded approved facility is required. A score recommendation alone does not create a repayment schedule.')
    return row


def current(db, key):
    return db.scalar(select(RepaymentSchedule).where(RepaymentSchedule.application_id == key)
                     .order_by(RepaymentSchedule.version.desc()).limit(1))


def receipt_rows(db, schedule_id):
    return list(db.scalars(select(RepaymentReceipt).where(RepaymentReceipt.schedule_id == schedule_id)
                           .order_by(RepaymentReceipt.id)))


def balances(schedule, receipts, today):
    paid, settled_dates = defaultdict(int), defaultdict(list)
    for receipt in receipts:
        if receipt.voided_at is not None or receipt.paid_on > today:
            continue
        for allocation in receipt.allocations:
            number = allocation['installment']
            paid[number] += allocation['amount_minor']
            settled_dates[number].append(receipt.paid_on)
    result = []
    for number, item in enumerate(schedule.items, 1):
        due = date.fromisoformat(item['due_on'])
        outstanding = item['amount_minor'] - paid[number]
        days = max(0, (today - due).days) if outstanding else 0
        settled = max(settled_dates[number]) if outstanding == 0 else None
        state = 'paid' if outstanding == 0 else 'overdue' if days else 'due_today' if due == today else 'upcoming'
        result.append(dict(installment=number, due_on=due.isoformat(), amount_pkr=money(item['amount_minor']),
            paid_pkr=money(paid[number]), outstanding_pkr=money(outstanding), days_past_due=days, status=state,
            settled_on=settled.isoformat() if settled else None,
            settled_late_days=max(0, (settled - due).days) if settled else None))
    return result


def report(db, key, *, now=None, schedule_id=None, receipt_offset=0):
    case = facility(db, key)
    today = business_date(now or utc_now())
    latest = current(db, key)
    schedule = db.scalar(select(RepaymentSchedule).where(RepaymentSchedule.id == schedule_id,
        RepaymentSchedule.application_id == key)) if schedule_id is not None else latest
    if schedule_id is not None and schedule is None:
        raise HTTPException(404, 'Schedule not found for this facility.')
    versions = list(db.scalars(select(RepaymentSchedule).where(RepaymentSchedule.application_id == key)
                              .order_by(RepaymentSchedule.version.desc())))
    base = dict(application_id=key, business_name=case.business_name, as_of_date=today.isoformat(),
                basis='Officer-recorded contractual schedule and explicitly allocated receipts.', limits=LIMITS,
                schedule=None, installments=[], recent_receipts=[], receipt_count=0, receipt_offset=receipt_offset,
                current_schedule_id=latest.id if latest else None,
                schedule_versions=[dict(id=v.id, version=v.version, created_at=as_utc(v.created_at), created_by=v.created_by) for v in versions])
    if schedule is None:
        return base
    receipts = receipt_rows(db, schedule.id)
    receipt_offset = min(receipt_offset, ((len(receipts) - 1) // 20) * 20) if receipts else 0
    base['receipt_offset'] = receipt_offset
    items = balances(schedule, receipts, today)
    base.update(schedule=dict(id=schedule.id, version=schedule.version, disbursed_on=schedule.disbursed_on.isoformat(),
        source_note=schedule.source_note, created_by=schedule.created_by, created_at=as_utc(schedule.created_at),
        replaces_id=schedule.replaces_id, is_current=schedule.id == latest.id,
        can_replace=schedule.id == latest.id and not any(r.voided_at is None for r in receipts)),
        installments=items, total_scheduled_pkr=money(sum(minor(i['amount_pkr']) for i in items)),
        total_paid_pkr=money(sum(minor(i['paid_pkr']) for i in items)),
        total_outstanding_pkr=money(sum(minor(i['outstanding_pkr']) for i in items)),
        overdue_pkr=money(sum(minor(i['outstanding_pkr']) for i in items if i['status'] == 'overdue')),
        maximum_days_past_due=max(i['days_past_due'] for i in items), receipt_count=len(receipts),
        recent_receipts=[dict(id=r.id, reference=r.reference, paid_on=r.paid_on.isoformat(),
            total_pkr=money(sum(a['amount_minor'] for a in r.allocations)),
            allocations=[dict(installment=a['installment'], amount_pkr=money(a['amount_minor'])) for a in r.allocations],
            created_by=r.created_by, created_at=as_utc(r.created_at),
            voided_at=as_utc(r.voided_at) if r.voided_at else None, voided_by=r.voided_by, void_reason=r.void_reason)
            for r in list(reversed(receipts))[receipt_offset:receipt_offset + 20]])
    return base


def save_schedule(db, key, body, actor, audit):
    actor = lock_officer_change(db, actor.id, MANAGERS)
    case = facility(db, key, locked=True)
    items = [dict(due_on=i.due_on.isoformat(), amount_minor=minor(i.amount_pkr)) for i in body.items]
    previous = db.scalar(select(RepaymentSchedule).where(RepaymentSchedule.submission_key == str(body.submission_key)))
    if previous:
        if (previous.application_id, previous.disbursed_on, previous.items, previous.source_note, previous.replaces_id) != (
            key, body.disbursed_on, items, body.source_note, body.expected_schedule_id):
            raise HTTPException(409, 'This save key belongs to different schedule details. Refresh before saving again.')
        return report(db, key)
    latest = current(db, key)
    if (latest.id if latest else None) != body.expected_schedule_id:
        raise HTTPException(409, 'The repayment schedule changed. Reload it before saving.')
    if body.disbursed_on > business_date():
        raise HTTPException(422, 'Disbursement cannot be recorded in the future.')
    # An approval is not evidence of disbursement; record that date explicitly.
    if case.reviewed_at and case.decision_source == 'officer' and body.disbursed_on < business_date(case.reviewed_at):
        raise HTTPException(422, 'Disbursement cannot predate the recorded officer approval.')
    if latest and any(r.voided_at is None for r in receipt_rows(db, latest.id)):
        raise HTTPException(409, 'This schedule has active receipts. A manager must review and void incorrect allocations before replacing the schedule; history is retained.')
    if latest and latest.version >= 100:
        raise HTTPException(409, 'This facility reached its 100-version schedule limit. Contact an administrator.')
    row = RepaymentSchedule(application_id=key, version=latest.version + 1 if latest else 1,
        submission_key=str(body.submission_key), replaces_id=latest.id if latest else None,
        disbursed_on=body.disbursed_on, items=items, source_note=body.source_note, created_by=actor.username)
    db.add(row)
    db.flush()
    audit_service.record(db, action='repayment.schedule_recorded', entity_type='application', entity_id=key,
        actor=actor, details=dict(schedule_id=row.id, version=row.version, replaces_id=row.replaces_id,
                                 disbursed_on=body.disbursed_on, items=items, source_note=body.source_note), context=audit)
    db.commit()
    return report(db, key)


def save_receipt(db, key, body, actor, audit):
    actor = lock_officer_change(db, actor.id, OFFICERS)
    facility(db, key, locked=True)
    allocations = sorted([dict(installment=a.installment, amount_minor=minor(a.amount_pkr)) for a in body.allocations], key=lambda a: a['installment'])
    reference = body.reference.upper()
    previous = db.scalar(select(RepaymentReceipt).where(RepaymentReceipt.submission_key == str(body.submission_key)))
    if previous:
        if (previous.application_id, previous.schedule_id, previous.paid_on, previous.reference, previous.allocations) != (
            key, body.expected_schedule_id, body.paid_on, reference, allocations):
            raise HTTPException(409, 'This save key belongs to different receipt details. Reload before saving.')
        return report(db, key)
    schedule = current(db, key)
    if schedule is None or schedule.id != body.expected_schedule_id:
        raise HTTPException(409, 'The repayment schedule changed or is missing. Reload before recording a receipt.')
    if not schedule.disbursed_on <= body.paid_on <= business_date():
        raise HTTPException(422, 'Payment date must be between recorded disbursement and today.')
    if db.scalar(select(RepaymentReceipt.id).where(RepaymentReceipt.application_id == key,
            RepaymentReceipt.reference == reference, RepaymentReceipt.voided_at.is_(None))):
        raise HTTPException(409, 'This payment reference is already recorded for the facility. Use one receipt with allocations across its instalments.')
    receipts = receipt_rows(db, schedule.id)
    if len(receipts) >= 1000:
        raise HTTPException(409, 'This schedule reached its 1,000-receipt recording limit. Contact an administrator.')
    remaining = balances(schedule, receipts, business_date())
    for allocation in allocations:
        number = allocation['installment']
        if number > len(remaining) or allocation['amount_minor'] > minor(remaining[number - 1]['outstanding_pkr']):
            raise HTTPException(422, 'An allocation exceeds the selected instalment balance or refers to an unknown instalment. Reload current balances.')
    row = RepaymentReceipt(application_id=key, schedule_id=schedule.id, submission_key=str(body.submission_key),
        paid_on=body.paid_on, reference=reference, allocations=allocations, created_by=actor.username)
    db.add(row)
    db.flush()
    audit_service.record(db, action='repayment.receipt_recorded', entity_type='application', entity_id=key,
        actor=actor, details=dict(receipt_id=row.id, schedule_id=schedule.id, paid_on=body.paid_on,
                                 reference=reference, allocations=allocations), context=audit)
    db.commit()
    return report(db, key)


def void_receipt(db, key, receipt_id, body, actor, audit):
    actor = lock_officer_change(db, actor.id, MANAGERS)
    facility(db, key, locked=True)
    receipt = db.scalar(select(RepaymentReceipt).where(RepaymentReceipt.id == receipt_id,
                                                     RepaymentReceipt.application_id == key))
    if receipt is None:
        raise HTTPException(404, 'Receipt not found for this facility.')
    if receipt.voided_at is not None:
        if receipt.void_reason != body.reason:
            raise HTTPException(409, 'This receipt was already voided with a different reason. Reload its history.')
        return report(db, key)
    receipt.voided_at, receipt.voided_by, receipt.void_reason = utc_now(), actor.username, body.reason
    audit_service.record(db, action='repayment.receipt_voided', entity_type='application', entity_id=key,
        actor=actor, details=dict(receipt_id=receipt.id, schedule_id=receipt.schedule_id, reason=body.reason), context=audit)
    db.commit()
    return report(db, key)
