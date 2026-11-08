"""Append-only source and permission evidence, with explicit limits on its meaning."""
import hashlib
import json
import unicodedata
from collections import Counter
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select

from business_time import as_utc, business_date, utc_now
from case_data_schemas import FIELD_LABELS
from models.database import Application, CaseDataRecord
from services import audit_service
from services.team_access import lock_officer_change

MANAGERS = frozenset({'manager', 'admin'})
OFFICERS = MANAGERS | {'analyst'}
STATES = ('recorded', 'recorded_no_expiry', 'missing', 'expired', 'withdrawn')
LIMITS = [
    'These are officer-recorded references, not independently verified consent, signatures, source ownership or legal authority. The platform grants no data access.',
    'Records are attached after an assessment. They do not establish what was known or authorised when that assessment was scored, and do not alter its inputs, recommendation or officer decision.',
    'Credit assessment, loan monitoring and model research are separate purposes. Recording a credit-purpose reference never supplies research permission.',
    'A missing expiry date is unknown, not indefinite permission. A document reference does not prove its terms, authenticity or permitted scope.',
    'Withdrawal is an appended restriction record, not automatic deletion or enforcement in an external provider. Retention and further processing need the lender\'s approved process.',
    'This register does not block existing intake, import external data, certify compliance, authorise training or make a dataset training-ready.',
]


def application(db, key, *, locked=False):
    query = select(Application).where(Application.id == key)
    row = db.scalar(query.with_for_update() if locked else query)
    if row is None:
        raise HTTPException(404, 'Application not found.')
    return row


def records(db, key):
    return list(db.scalars(select(CaseDataRecord).where(CaseDataRecord.application_id == key).order_by(CaseDataRecord.id)))


def latest_by_stream(rows):
    return {row.stream_key: row for row in rows}


def describe(row, case, today):
    data = row.payload
    flags = []
    if row.event_kind == 'withdrawn':
        state = 'withdrawn'
    elif data['permission_basis'] == 'not_recorded':
        state = 'missing'
    elif data['permission_expires_on'] and date.fromisoformat(data['permission_expires_on']) < today:
        state = 'expired'
    elif data['permission_expires_on'] is None:
        state = 'recorded_no_expiry'
        flags.append('No expiry date recorded; review the referenced terms.')
    else:
        state = 'recorded'
    assessed = business_date(case.created_at)
    if date.fromisoformat(data['captured_on']) > assessed:
        flags.append('Source capture is dated after this assessment.')
    if data['permission_on'] and date.fromisoformat(data['permission_on']) > assessed:
        flags.append('Permission evidence is dated after this assessment.')
    if data['period_from'] is None:
        flags.append('Source coverage period not recorded.')
    if data['source_kind'] == 'applicant_declaration':
        flags.append('Applicant declaration; no independent source verification is established.')
    return dict(id=row.id, application_id=row.application_id, stream_key=row.stream_key, revision=row.revision, supersedes_id=row.supersedes_id,
        event_kind=row.event_kind, status=state, **data, input_snapshot=row.input_snapshot,
        note=row.note, created_by=row.created_by, created_at=as_utc(row.created_at), flags=flags)


def report(db, key, *, offset=0, now=None):
    case = application(db, key)
    today = business_date(now or utc_now())
    latest = sorted(latest_by_stream(records(db, key)).values(), key=lambda row: row.id, reverse=True)
    described = [describe(row, case, today) for row in latest]
    counts = Counter(row['status'] for row in described)
    offset = min(offset, ((len(latest) - 1) // 10) * 10) if latest else 0
    return dict(application_id=key, business_name=case.business_name, assessed_at=as_utc(case.created_at),
        as_of_date=today.isoformat(), training_authorised=False, data_access_granted=False,
        limits=LIMITS, counts={state: counts[state] for state in STATES}, total=len(latest), offset=offset, limit=10,
        rows=described[offset:offset + 10],
        field_coverage=[dict(field=name, label=label, saved_value=getattr(case, name),
            source_records=sum(name in row['input_fields'] for row in described),
            dated_permission_record_count=sum(name in row['input_fields'] and row['status'] == 'recorded' for row in described))
            for name, label in FIELD_LABELS.items()])


def history(db, key, stream_key, *, offset=0):
    case = application(db, key)
    rows = list(db.scalars(select(CaseDataRecord).where(CaseDataRecord.application_id == key,
        CaseDataRecord.stream_key == str(stream_key)).order_by(CaseDataRecord.revision.desc())))
    if not rows:
        raise HTTPException(404, 'Evidence history not found for this application.')
    offset = min(offset, ((len(rows) - 1) // 20) * 20)
    return dict(application_id=key, stream_key=str(stream_key), as_of_date=business_date().isoformat(), total=len(rows), offset=offset, limit=20,
        rows=[describe(row, case, business_date()) for row in rows[offset:offset + 20]])


def write(db, key, body, actor, audit, *, target_id=None, withdraw=False):
    actor = lock_officer_change(db, actor.id, MANAGERS if target_id is not None else OFFICERS)
    case = application(db, key, locked=True)
    operation = 'withdraw' if withdraw else 'replace' if target_id is not None else 'record'
    canonical = json.dumps(dict(application_id=key, operation=operation, target_id=target_id,
        request=body.model_dump(mode='json', exclude={'submission_key'})), sort_keys=True, separators=(',', ':'))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    existing = db.scalar(select(CaseDataRecord).where(CaseDataRecord.submission_key == str(body.submission_key)))
    if existing:
        if existing.payload_hash != fingerprint:
            raise HTTPException(409, 'This save key belongs to different evidence details. Retry the original details or discard the draft before starting again.')
        return report(db, key)
    rows = records(db, key)
    latest = latest_by_stream(rows)
    previous = None
    if target_id is not None:
        previous = next((row for row in rows if row.id == target_id), None)
        if previous is None:
            raise HTTPException(404, 'Evidence record not found for this application.')
        if latest[previous.stream_key].id != target_id:
            raise HTTPException(409, 'This evidence record changed. Discard the draft and reload its latest revision before recording a correction or withdrawal.')
    elif len(latest) >= 50:
        raise HTTPException(409, 'This application reached its 50-source recording limit. Contact an administrator.')
    if len(rows) >= 500:
        raise HTTPException(409, 'This application reached its 500-event evidence-history limit. Contact an administrator.')
    if withdraw:
        if previous.event_kind == 'withdrawn':
            raise HTTPException(409, 'Withdrawal is already recorded. Reload the source history.')
        payload = previous.payload
        snapshot = previous.input_snapshot
        note = body.reason
    else:
        # A later create must not hide an existing withdrawal behind a second
        # stream for the same reference. This is reference deduplication, not
        # independent document identity verification.
        normalise = lambda value: ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
        duplicate = next((row for row in rows if normalise(row.payload['source_reference']) == normalise(body.source_reference)
                          and (previous is None or row.stream_key != previous.stream_key)), None)
        if duplicate:
            raise HTTPException(409, 'This source reference already has a history for this case. Open its latest record to correct it; a new source cannot bypass a recorded withdrawal.')
        today = business_date()
        if body.captured_on > today or (body.permission_on and body.permission_on > today):
            raise HTTPException(422, 'Source capture and permission evidence dates cannot be in the future.')
        if previous and previous.event_kind == 'withdrawn' and body.permission_on and body.permission_on < business_date(previous.created_at):
            raise HTTPException(422, 'A withdrawn record needs new permission evidence dated on or after the recorded withdrawal. Earlier evidence cannot silently reinstate it.')
        payload = body.model_dump(mode='json', exclude={'submission_key', 'note'})
        snapshot = {field: getattr(case, field) for field in body.input_fields}
        note = body.note
    row = CaseDataRecord(application_id=key, stream_key=previous.stream_key if previous else str(body.submission_key),
        revision=previous.revision + 1 if previous else 1, supersedes_id=previous.id if previous else None,
        submission_key=str(body.submission_key), payload_hash=fingerprint, event_kind='withdrawn' if withdraw else 'recorded',
        payload=payload, input_snapshot=snapshot, note=note, created_by=actor.username, created_at=utc_now())
    db.add(row)
    db.flush()
    audit_service.record(db, action='case_data.' + operation, entity_type='application', entity_id=key,
        actor=actor, details=dict(record_id=row.id, stream_key=row.stream_key, revision=row.revision,
            supersedes_id=row.supersedes_id, payload_hash=fingerprint), context=audit)
    db.commit()
    return report(db, key)
