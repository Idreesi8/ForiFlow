"""Complete alert search, count scope, priority and compatibility checks."""
from datetime import timedelta

import pytest
from sqlalchemy import event, select, func

from business_time import business_date
from models.database import Alert, AuditLog
from services.alert_queue import build_alert_queue
from tests.test_application_register import add_case


def add_alert(db, case, *, status='Open', severity='WARNING', drop=20, due=None):
    row = Alert(borrower_id=case.id, baseline_score=80, current_score=80-drop,
                score_drop=drop, estimated_days_to_default=30, alert_status=status,
                severity=severity, action_due_date=due)
    db.add(row)
    db.flush()
    return row


def test_complete_queue_finds_closed_alert_beyond_two_hundred_open_ones(client, db_session_factory):
    with db_session_factory() as db:
        old = add_case(db, name='Old Needle Workshop', status='Approved')
        closed = add_alert(db, old, status='Resolved', severity=None)
        closed_id, facility = closed.id, old.id
        for number in range(205):
            case = add_case(db, name=f'Recent shop {number}', status='Approved')
            add_alert(db, case, severity='CRITICAL' if number == 0 else 'WARNING',
                      due=business_date()-timedelta(days=1) if number == 0 else None,
                      drop=65 if number == 204 else 20)
        db.commit()
    assert closed_id not in [row['id'] for row in client.get('/ews/alerts', params={'limit': 200}).json()]
    body = client.get('/ews/alert-queue', params={'alert_status': 'Resolved'}).json()
    assert body['matching'] == 1 and body['total'] == 206
    assert body['items'][0]['id'] == closed_id
    assert body['counts'] == dict(open=205, closed=1, critical=1, overdue=1, worst_open_drop=65)
    search = client.get('/ews/alert-queue', params={'search': '  NEEDLE  '}).json()
    assert search['matching'] == search['total'] == 1
    assert search['counts']['open'] == 0 and search['counts']['worst_open_drop'] is None
    assert client.get('/ews/alert-queue', params={'search': f'#{facility}'}).json()['items'][0]['id'] == closed_id
    pages = [client.get('/ews/alert-queue', params={'open_only': True, 'limit': 100, 'offset': offset}).json()
             for offset in (0, 100, 200)]
    identifiers = [row['id'] for page in pages for row in page['items']]
    assert len(identifiers) == len(set(identifiers)) == 205
    assert pages[0]['items'][0]['severity'] == 'CRITICAL'
    assert all(page['matching'] == 205 and page['total'] == 206 for page in pages)
    legacy = client.get('/ews/alerts', params={'open_only': True, 'limit': 100, 'offset': 100}).json()
    assert [row['id'] for row in legacy] == [row['id'] for row in pages[1]['items']]


def test_literal_search_and_scope_counts_are_independent_of_selected_status(client, db_session_factory):
    with db_session_factory() as db:
        case = add_case(db, name="100%_! O'Brien Workshop", status='Approved')
        add_alert(db, case, status='Resolved', severity='CRITICAL', due=business_date()-timedelta(days=1))
        add_alert(db, case, status='Acknowledged', due=business_date())
        other = add_case(db, name='Other workshop', status='Approved')
        add_alert(db, other, status='Action Required', severity='CRITICAL')
        db.commit()
        facility = case.id
    for term in ['%', '_', '!', "O'Brien"]:
        body = client.get('/ews/alert-queue', params={'search': term, 'alert_status': 'Resolved'}).json()
        assert body['total'] == 2 and body['matching'] == 1
        assert body['counts']['open'] == 1 and body['counts']['critical'] == body['counts']['overdue'] == 0
    assert client.get('/ews/alert-queue', params={'search': "' OR 1=1 --"}).json()['total'] == 0
    scope = client.get('/ews/alert-queue', params={'facility_id': facility, 'severity': 'CRITICAL'}).json()
    assert scope['total'] == 1 and scope['counts']['closed'] == 1
    assert client.get('/ews/alert-queue', params={'open_only': True, 'alert_status': 'Resolved'}).json()['matching'] == 0


def test_empty_and_out_of_range_pages_have_truthful_counts(client, db_session_factory):
    body = client.get('/ews/alert-queue').json()
    assert body['items'] == [] and body['total'] == body['matching'] == 0
    with db_session_factory() as db:
        case = add_case(db, status='Approved')
        for _ in range(4):
            add_alert(db, case, status='Dismissed')
        db.commit()
    body = client.get('/ews/alert-queue', params={'offset': 100}).json()
    assert body['items'] == [] and body['total'] == body['matching'] == 4
    assert body['counts']['closed'] == 4


@pytest.mark.parametrize('params', [{'limit': 0}, {'limit': 201}, {'offset': -1},
    {'facility_id': 0}, {'alert_status': 'unknown'}, {'severity': 'unknown'}, {'search': 'x'*121}])
def test_queue_rejects_invalid_parameters(client, params):
    assert client.get('/ews/alert-queue', params=params).status_code == 422


def test_queue_is_authenticated(anonymous_client):
    assert anonymous_client.get('/ews/alert-queue').status_code == 401


def test_queries_are_bounded_read_only_and_ties_are_stable(db_session_factory):
    with db_session_factory() as db:
        case = add_case(db, status='Approved')
        for _ in range(7):
            add_alert(db, case, status='Resolved')
        db.commit()
        before = db.scalar(select(func.count(AuditLog.id)))
        statements = []
        def capture(conn, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(db.bind, 'before_cursor_execute', capture)
        try:
            first = build_alert_queue(db, limit=3)
            second = build_alert_queue(db, limit=3, offset=3)
        finally:
            event.remove(db.bind, 'before_cursor_execute', capture)
        assert [row.id for row in first['items'] + second['items']] == [7, 6, 5, 4, 3, 2]
        assert all(sql.lstrip().upper().startswith('SELECT') for sql in statements)
        assert any('LIMIT' in sql.upper() and 'OFFSET' in sql.upper() for sql in statements)
        assert db.scalar(select(func.count(AuditLog.id))) == before
