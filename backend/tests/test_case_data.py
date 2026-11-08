"""Permission references never become grants, labels or mutable credit facts."""
import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from models.database import Application, Base, CaseDataRecord, User
from services import case_data
from tests.conftest import MID_APPLICANT


@pytest.fixture
def case(client, db_session_factory, monkeypatch):
    from business_time import business_date
    monkeypatch.setattr(case_data, 'business_date', lambda value=None: business_date(value) if value is not None else date(2026, 11, 8))
    monkeypatch.setattr(case_data, 'utc_now', lambda: datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
    key = client.post('/score', json=MID_APPLICANT).json()['application_id']
    with db_session_factory() as db:
        db.get(Application, key).created_at = datetime(2026, 10, 10, tzinfo=timezone.utc)
        db.commit()
    return key


def body(**changes):
    return {**dict(submission_key=str(uuid4()), source_kind='bank_statement', source_reference='FICTIONAL-STATEMENT-QA-01',
        captured_on='2026-10-01', period_from=None, period_to=None,
        input_fields=['monthly_digital_payments', 'cash_flow_proxy'], permission_basis='not_recorded',
        permission_reference=None, permission_on=None, permission_expires_on=None,
        purposes=['credit_assessment'], note='Fictional evidence reference, not independently verified.'), **changes}


def documented(**changes):
    return body(**{**dict(permission_basis='consent_record', permission_reference='FICTIONAL-CONSENT-QA-01',
        permission_on='2026-09-30', permission_expires_on='2026-12-31'), **changes})


def record(client, key, payload=None):
    response = client.post(f'/case-data/{key}/records', json=payload or body())
    assert response.status_code == 200, response.text
    return response.json()


def snap(factory):
    with factory() as db:
        return {t.name: sorted(json.dumps(dict(row), default=str, sort_keys=True)
            for row in db.execute(select(t)).mappings()) for t in Base.metadata.sorted_tables}


def test_empty_register_is_unknown_read_only_and_never_authorises_training(client, case, db_session_factory):
    before = snap(db_session_factory)
    response = client.get(f'/case-data/{case}')
    assert response.status_code == 200
    report = response.json()
    assert report['total'] == 0 and report['rows'] == []
    assert report['training_authorised'] is False and report['data_access_granted'] is False
    assert all(field['source_records'] == 0 for field in report['field_coverage'])
    assert snap(db_session_factory) == before


def test_snapshot_matches_only_linked_saved_financial_fields(client, case, db_session_factory):
    before = snap(db_session_factory)
    report = record(client, case)
    entry = report['rows'][0]
    assert entry['status'] == 'missing'
    assert entry['input_snapshot'] == {'monthly_digital_payments': 500000, 'cash_flow_proxy': 220000}
    assert entry['purposes'] == ['credit_assessment']
    assert 'model_research' not in entry['purposes']
    after = snap(db_session_factory)
    for table in before.keys() - {'case_data_records', 'audit_logs'}:
        assert before[table] == after[table], table


@pytest.mark.parametrize('expiry,status', [('2026-11-08', 'recorded'), ('2026-11-07', 'expired'), (None, 'recorded_no_expiry')])
def test_expiry_is_inclusive_and_absent_expiry_is_not_indefinite_permission(client, case, expiry, status):
    report = record(client, case, documented(permission_expires_on=expiry))
    assert report['rows'][0]['status'] == status
    assert report['training_authorised'] is False and report['data_access_granted'] is False


def test_even_explicit_research_scope_is_not_training_authorisation(client, case):
    report = record(client, case, documented(purposes=['model_research']))
    assert report['rows'][0]['purposes'] == ['model_research']
    assert report['training_authorised'] is False


@pytest.mark.parametrize('change', [
    {'captured_on': '2026-11-09'}, {'permission_on': '2026-11-09'},
    {'permission_expires_on': '2026-09-29'}, {'permission_reference': None},
    {'input_fields': []}, {'input_fields': ['applicant_name']}, {'input_fields': ['cash_flow_proxy', 'cash_flow_proxy']},
    {'purposes': []}, {'purposes': ['credit_assessment', 'credit_assessment']},
    {'period_from': '2026-09-01'}, {'period_from': '2026-09-02', 'period_to': '2026-09-01'},
    {'period_from': '2026-09-01', 'period_to': '2026-10-02'},
    {'permission_basis': 'not_recorded'}, {'note': 'short'},
])
def test_invalid_evidence_never_writes_any_table(client, case, db_session_factory, change):
    before = snap(db_session_factory)
    response = client.post(f'/case-data/{case}/records', json=documented(**change))
    assert response.status_code == 422, response.text
    assert snap(db_session_factory) == before


def test_dates_after_assessment_are_flagged_without_rewriting_the_assessment(client, case):
    row = record(client, case, documented(captured_on='2026-11-01', permission_on='2026-11-01'))['rows'][0]
    assert any('capture' in flag and 'after' in flag for flag in row['flags'])
    assert any('Permission' in flag and 'after' in flag for flag in row['flags'])


def test_save_key_replays_without_another_record_or_audit_event(client, case, db_session_factory):
    payload = documented()
    first = record(client, case, payload)
    before = snap(db_session_factory)
    assert record(client, case, payload) == first
    assert snap(db_session_factory) == before
    assert client.post(f'/case-data/{case}/records', json={**payload, 'note': 'Different fictional note with the same key'}).status_code == 409
    assert snap(db_session_factory) == before


def test_correction_preserves_history_and_stale_changes_are_refused(client, case, db_session_factory):
    first = record(client, case)['rows'][0]
    response = client.post(f"/case-data/{case}/records/{first['id']}/replace", json=documented())
    assert response.status_code == 200, response.text
    second = response.json()['rows'][0]
    assert second['revision'] == 2 and second['supersedes_id'] == first['id']
    assert response.json()['total'] == 1
    before = snap(db_session_factory)
    assert client.post(f"/case-data/{case}/records/{first['id']}/replace", json=documented()).status_code == 409
    history = client.get(f"/case-data/{case}/history/{first['stream_key']}").json()
    assert [row['revision'] for row in history['rows']] == [2, 1]
    assert history['rows'][1]['permission_basis'] == 'not_recorded'
    assert snap(db_session_factory) == before


def test_withdrawal_is_append_only_idempotent_and_requires_new_evidence_to_reinstate(client, case, db_session_factory):
    original_payload = documented()
    first = record(client, case, original_payload)['rows'][0]
    withdrawal = {'submission_key': str(uuid4()), 'reason': 'Fictional withdrawal request reference QA-WITHDRAW-01'}
    response = client.post(f"/case-data/{case}/records/{first['id']}/withdraw", json=withdrawal)
    assert response.status_code == 200, response.text
    withdrawn = response.json()['rows'][0]
    assert withdrawn['status'] == 'withdrawn' and withdrawn['revision'] == 2
    before = snap(db_session_factory)
    assert client.post(f"/case-data/{case}/records/{first['id']}/withdraw", json=withdrawal).status_code == 200
    assert record(client, case, original_payload)['rows'][0]['status'] == 'withdrawn'
    assert snap(db_session_factory) == before
    assert client.post(f"/case-data/{case}/records/{withdrawn['id']}/replace", json=documented()).status_code == 422
    assert snap(db_session_factory) == before
    restored = client.post(f"/case-data/{case}/records/{withdrawn['id']}/replace",
        json=documented(permission_on='2026-11-08', permission_reference='FICTIONAL-NEW-CONSENT-QA-02'))
    assert restored.status_code == 200, restored.text
    assert restored.json()['rows'][0]['revision'] == 3
    assert restored.json()['training_authorised'] is False


def test_record_history_cannot_cross_application_boundaries(client, case, db_session_factory):
    payload = documented()
    first = record(client, case, payload)['rows'][0]
    other = client.post('/score', json=MID_APPLICANT).json()['application_id']
    before = snap(db_session_factory)
    assert client.get(f"/case-data/{other}/history/{first['stream_key']}").status_code == 404
    assert client.post(f'/case-data/{other}/records', json=payload).status_code == 409
    assert client.post(f"/case-data/{other}/records/{first['id']}/replace", json=documented()).status_code == 404
    assert snap(db_session_factory) == before


def test_same_source_cannot_be_recreated_to_hide_its_withdrawal(client, case, db_session_factory):
    first = record(client, case, documented())['rows'][0]
    response = client.post(f"/case-data/{case}/records/{first['id']}/withdraw", json={
        'submission_key': str(uuid4()), 'reason': 'Fictional documented withdrawal request QA-01'})
    assert response.status_code == 200
    before = snap(db_session_factory)
    assert client.post(f'/case-data/{case}/records', json=documented(source_reference='fictional-statement-qa-01')).status_code == 409
    assert snap(db_session_factory) == before


def test_analysts_record_references_but_only_managers_correct_or_withdraw(client, case, db_session_factory):
    with db_session_factory() as db:
        db.get(User, 1).role = 'analyst'
        db.commit()
    row = record(client, case)['rows'][0]
    before = snap(db_session_factory)
    assert client.post(f"/case-data/{case}/records/{row['id']}/replace", json=documented()).status_code == 403
    assert client.post(f"/case-data/{case}/records/{row['id']}/withdraw", json={'submission_key': str(uuid4()), 'reason': 'Fictional withdrawal request'}).status_code == 403
    assert snap(db_session_factory) == before


@pytest.mark.parametrize('statement', ['UPDATE case_data_records SET note=note', 'DELETE FROM case_data_records'])
def test_database_rejects_changes_that_bypass_the_api(client, case, db_session_factory, statement):
    record(client, case)
    before = snap(db_session_factory)
    with db_session_factory() as db:
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()
    assert snap(db_session_factory) == before


def test_paging_is_read_only_and_counts_current_sources_not_versions(client, case, db_session_factory):
    for number in range(11):
        record(client, case, body(source_reference=f'FICTIONAL-SOURCE-{number}'))
    before = snap(db_session_factory)
    first = client.get(f'/case-data/{case}').json()
    older = client.get(f'/case-data/{case}?offset=10').json()
    beyond = client.get(f'/case-data/{case}?offset=500').json()
    assert first['total'] == older['total'] == 11
    assert len(first['rows']) == 10 and len(older['rows']) == 1
    assert beyond['offset'] == 10
    assert snap(db_session_factory) == before


def test_endpoints_require_authentication(anonymous_client):
    assert anonymous_client.get('/case-data/1').status_code == 401


def test_unknown_case_returns_not_found(client):
    assert client.get('/case-data/9999').status_code == 404
