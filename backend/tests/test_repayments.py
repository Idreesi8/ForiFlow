"""Real dated arrears arithmetic, transactional recording and preserved history."""
import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from models.database import Application, Base, RepaymentReceipt, RepaymentSchedule, User
from services import repayments
from tests.conftest import MID_APPLICANT


@pytest.fixture
def case(client, db_session_factory, monkeypatch):
    from business_time import business_date
    monkeypatch.setattr(repayments, 'business_date', lambda value=None: business_date(value) if value is not None else date(2026, 11, 8))
    monkeypatch.setattr(repayments, 'utc_now', lambda: datetime(2026, 11, 8, 10, tzinfo=timezone.utc))
    key = client.post('/score', json=MID_APPLICANT).json()['application_id']
    with db_session_factory() as db:
        row = db.get(Application, key)
        row.decision_status, row.decision_source = 'Approved', 'officer'
        row.reviewed_at = datetime(2026, 9, 30, tzinfo=timezone.utc)
        row.reviewed_by = 'test-admin'
        db.commit()
    return key


def plan(**changes):
    return dict(submission_key=str(uuid4()), expected_schedule_id=None, disbursed_on='2026-10-01',
        items=[dict(due_on='2026-11-01', amount_pkr='100.01'), dict(due_on='2026-12-01', amount_pkr='100.01')],
        source_note='Fictional signed contract reference QA-01', **changes)


def receipt(schedule, **changes):
    body = dict(submission_key=str(uuid4()), expected_schedule_id=schedule, paid_on='2026-11-02',
        reference='QA-PAY-01', allocations=[dict(installment=1, amount_pkr='20.01')])
    return {**body, **changes}


def save_plan(client, key, body=None):
    response = client.post(f'/repayments/{key}/schedule', json=body or plan())
    assert response.status_code == 200, response.text
    return response.json()


def snap(factory):
    with factory() as db:
        return {t.name: sorted(json.dumps(dict(row), default=str, sort_keys=True)
                              for row in db.execute(select(t)).mappings()) for t in Base.metadata.sorted_tables}


def test_empty_calendar_is_read_only_and_does_not_invent_contract(client, case, db_session_factory):
    before = snap(db_session_factory)
    body = client.get(f'/repayments/{case}').json()
    assert body['schedule'] is None and body['installments'] == []
    assert body['as_of_date'] == '2026-11-08'
    assert snap(db_session_factory) == before


def test_due_dates_exact_money_partial_payment_and_settlement(client, case, db_session_factory):
    body = save_plan(client, case)
    schedule = body['schedule']['id']
    assert body['overdue_pkr'] == '100.01' and body['maximum_days_past_due'] == 7
    paid = client.post(f'/repayments/{case}/receipts', json=receipt(schedule)).json()
    assert paid['installments'][0]['outstanding_pkr'] == '80.00'
    assert paid['installments'][0]['days_past_due'] == 7
    assert paid['installments'][1]['status'] == 'upcoming'
    completed = client.post(f'/repayments/{case}/receipts', json=receipt(schedule,
        reference='QA-PAY-02', paid_on='2026-11-06', allocations=[dict(installment=1, amount_pkr='80.00')])).json()
    assert completed['installments'][0]['status'] == 'paid'
    assert completed['installments'][0]['days_past_due'] == 0
    assert completed['installments'][0]['settled_late_days'] == 5
    assert completed['total_paid_pkr'] == '100.01' and completed['overdue_pkr'] == '0.00'
    with db_session_factory() as db:
        assert db.scalars(select(RepaymentReceipt)).first().allocations[0]['amount_minor'] == 2001


def test_prepayments_due_today_and_backdated_receipts_are_explicit(client, case):
    body = plan()
    body['items'][0]['due_on'] = '2026-11-08'
    report = save_plan(client, case, body)
    assert report['installments'][0]['status'] == 'due_today'
    report = client.post(f'/repayments/{case}/receipts', json=receipt(report['schedule']['id'],
        paid_on='2026-10-31', allocations=[dict(installment=1, amount_pkr='100.01'),
                                        dict(installment=2, amount_pkr='100.01')])).json()
    assert report['total_outstanding_pkr'] == '0.00'
    assert report['installments'][0]['settled_late_days'] == 0


def test_schedule_and_receipt_save_keys_are_idempotent(client, case, db_session_factory):
    body = plan()
    report = save_plan(client, case, body)
    before = snap(db_session_factory)
    assert save_plan(client, case, body) == report
    assert snap(db_session_factory) == before
    payment = receipt(report['schedule']['id'])
    first = client.post(f'/repayments/{case}/receipts', json=payment)
    assert first.status_code == 200
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/receipts', json=payment).json() == first.json()
    assert snap(db_session_factory) == before
    payment['allocations'][0]['amount_pkr'] = '1.00'
    assert client.post(f'/repayments/{case}/receipts', json=payment).status_code == 409
    assert snap(db_session_factory) == before


def test_schedule_key_cannot_be_reused_for_different_content(client, case, db_session_factory):
    body = plan()
    save_plan(client, case, body)
    before = snap(db_session_factory)
    body['source_note'] = 'Different fictional contract source'
    assert client.post(f'/repayments/{case}/schedule', json=body).status_code == 409
    assert snap(db_session_factory) == before


@pytest.mark.parametrize('change,status', [
    ({'paid_on': '2026-11-09'}, 422), ({'paid_on': '2026-09-30'}, 422),
    ({'expected_schedule_id': 9999}, 409),
    ({'allocations': [{'installment': 3, 'amount_pkr': '1.00'}]}, 422),
    ({'allocations': [{'installment': 1, 'amount_pkr': '100.02'}]}, 422),
    ({'allocations': [{'installment': 1, 'amount_pkr': '0.001'}]}, 422),
    ({'allocations': [{'installment': 1, 'amount_pkr': '-1'}]}, 422),
    ({'allocations': [{'installment': 1, 'amount_pkr': 'NaN'}]}, 422),
    ({'allocations': [{'installment': 1, 'amount_pkr': '1'}, {'installment': 1, 'amount_pkr': '1'}]}, 422),
])
def test_invalid_receipts_never_change_any_table(client, case, db_session_factory, change, status):
    report = save_plan(client, case)
    before = snap(db_session_factory)
    response = client.post(f'/repayments/{case}/receipts', json=receipt(report['schedule']['id'], **change))
    assert response.status_code == status, response.text
    assert snap(db_session_factory) == before


@pytest.mark.parametrize('change', [
    {'disbursed_on': '2026-11-09'}, {'disbursed_on': '2026-09-29'},
    {'items': []}, {'items': [{'due_on': '2026-09-30', 'amount_pkr': '10'}]},
    {'items': [{'due_on': '2026-11-01', 'amount_pkr': '1'}, {'due_on': '2026-11-01', 'amount_pkr': '1'}]},
    {'items': [{'due_on': '2026-12-01', 'amount_pkr': '1'}, {'due_on': '2026-11-01', 'amount_pkr': '1'}]},
])
def test_invalid_schedules_never_write(client, case, db_session_factory, change):
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/schedule', json={**plan(), **change}).status_code == 422
    assert snap(db_session_factory) == before


def test_duplicate_reference_cannot_double_count_but_can_split_one_receipt(client, case, db_session_factory):
    report = save_plan(client, case)
    body = receipt(report['schedule']['id'])
    assert client.post(f'/repayments/{case}/receipts', json=body).status_code == 200
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/receipts', json=receipt(report['schedule']['id'], reference='qa-pay-01')).status_code == 409
    assert snap(db_session_factory) == before


def test_void_keeps_history_restores_arrears_and_allows_corrected_entry(client, case, db_session_factory):
    report = save_plan(client, case)
    body = receipt(report['schedule']['id'])
    first = client.post(f'/repayments/{case}/receipts', json=body).json()
    key = first['recent_receipts'][0]['id']
    reason = {'reason': 'Wrong allocation in fictional payment evidence'}
    void = client.post(f'/repayments/{case}/receipts/{key}/void', json=reason)
    assert void.status_code == 200, void.text
    assert void.json()['overdue_pkr'] == '100.01'
    assert void.json()['recent_receipts'][0]['voided_by']
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/receipts/{key}/void', json=reason).status_code == 200
    assert snap(db_session_factory) == before
    assert client.post(f'/repayments/{case}/receipts', json=receipt(report['schedule']['id'])).status_code == 200
    with db_session_factory() as db:
        assert len(db.scalars(select(RepaymentReceipt)).all()) == 2


def test_replacement_preserves_versions_and_requires_fresh_schedule_id(client, case, db_session_factory):
    first = save_plan(client, case)
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/schedule', json=plan()).status_code == 409
    assert snap(db_session_factory) == before
    body = plan()
    body['expected_schedule_id'] = first['schedule']['id']
    second = save_plan(client, case, body)
    assert second['schedule']['version'] == 2 and second['schedule']['replaces_id'] == first['schedule']['id']
    with db_session_factory() as db:
        assert len(db.scalars(select(RepaymentSchedule)).all()) == 2
    assert client.post(f'/repayments/{case}/receipts', json=receipt(first['schedule']['id'])).status_code == 409


def test_active_receipts_block_schedule_replacement(client, case, db_session_factory):
    first = save_plan(client, case)
    assert client.post(f'/repayments/{case}/receipts', json=receipt(first['schedule']['id'])).status_code == 200
    body = plan()
    body['expected_schedule_id'] = first['schedule']['id']
    before = snap(db_session_factory)
    assert client.post(f'/repayments/{case}/schedule', json=body).status_code == 409
    assert snap(db_session_factory) == before


def test_calendar_never_updates_score_policy_ews_or_decision(client, case, db_session_factory):
    before = snap(db_session_factory)
    first = save_plan(client, case)
    client.post(f'/repayments/{case}/receipts', json=receipt(first['schedule']['id']))
    after = snap(db_session_factory)
    for table in before.keys() - {'audit_logs', 'repayment_schedules', 'repayment_receipts'}:
        assert before[table] == after[table], table


def test_only_recorded_approval_can_start_schedule(client, db_session_factory):
    key = client.post('/score', json=MID_APPLICANT).json()['application_id']
    assert client.post(f'/repayments/{key}/schedule', json=plan()).status_code == 409
    assert client.get('/repayments/99999').status_code == 404


def test_analyst_reads_and_records_receipts_but_cannot_change_contract_or_void(client, case, db_session_factory):
    first = save_plan(client, case)
    with db_session_factory() as db:
        db.get(User, 1).role = 'analyst'
        db.commit()
    assert client.get(f'/repayments/{case}').status_code == 200
    assert client.post(f'/repayments/{case}/schedule', json=plan()).status_code == 403
    response = client.post(f'/repayments/{case}/receipts', json=receipt(first['schedule']['id']))
    assert response.status_code == 200, response.text
    key = response.json()['recent_receipts'][0]['id']
    assert client.post(f'/repayments/{case}/receipts/{key}/void', json={'reason': 'Fictional correction request'}).status_code == 403


def test_no_anonymous_access(anonymous_client):
    assert anonymous_client.get('/repayments/1').status_code == 401


def test_midnight_uses_pakistan_calendar(client, case, monkeypatch):
    from business_time import business_date
    monkeypatch.setattr(repayments, 'business_date', business_date)
    monkeypatch.setattr(repayments, 'utc_now', lambda: datetime(2026, 11, 7, 20, tzinfo=timezone.utc))
    assert client.get(f'/repayments/{case}').json()['as_of_date'] == '2026-11-08'


def test_archived_schedule_is_readable_without_reassigning_payments(client, case, db_session_factory):
    first = save_plan(client, case)
    body = plan()
    body['expected_schedule_id'] = first['schedule']['id']
    second = save_plan(client, case, body)
    before = snap(db_session_factory)
    historic = client.get(f"/repayments/{case}?schedule_id={first['schedule']['id']}").json()
    assert historic['schedule']['is_current'] is False and not historic['schedule']['can_replace']
    assert historic['current_schedule_id'] == second['schedule']['id']
    assert [v['version'] for v in historic['schedule_versions']] == [2, 1]
    assert client.get(f'/repayments/{case}?schedule_id=99999').status_code == 404
    assert snap(db_session_factory) == before


def test_receipt_paging_does_not_change_total_allocated_balances(client, case, db_session_factory):
    first = save_plan(client, case)
    schedule = first['schedule']['id']
    for number in range(21):
        response = client.post(f'/repayments/{case}/receipts', json=receipt(schedule,
            reference=f'QA-REFERENCE-{number}', allocations=[dict(installment=1, amount_pkr='0.01')]))
        assert response.status_code == 200, response.text
    before = snap(db_session_factory)
    page1 = client.get(f'/repayments/{case}').json()
    page2 = client.get(f'/repayments/{case}?receipt_offset=20').json()
    assert len(page1['recent_receipts']) == 20 and len(page2['recent_receipts']) == 1
    assert page1['total_paid_pkr'] == page2['total_paid_pkr'] == '0.21'
    assert snap(db_session_factory) == before
