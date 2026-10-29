"""Complete-register retrieval, literal search, authority semantics and read-only queries."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from models.database import Application, AuditLog, Borrower
from services.application_register import build_register
from tests.conftest import STRONG_APPLICANT


def add_case(db, *, name='Synthetic business', status='Pending', recommendation='Approved',
             score=82, amount=2400000, reference=None):
    owner = Borrower(business_name=name, owner_name='Synthetic owner', public_id=reference)
    db.add(owner)
    db.flush()
    case = Application(**{**STRONG_APPLICANT, 'business_name': name, 'loan_amount_pkr': amount},
        borrower_id=owner.id, risk_score=score, decision=recommendation, decision_status=status,
        contact_phone='+923001234567', created_at=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
        turnover_evidence_json='{"private": "Not for the register"}')
    db.add(case)
    db.flush()
    return case


def test_empty_register_is_explicit_and_requires_auth(client, anonymous_client):
    assert anonymous_client.get('/score/register').status_code == 401


def test_empty_register(client):
    assert client.get('/score/register').json() == {'items': [], 'total': 0, 'matching': 0, 'limit': 25, 'offset': 0}


def test_full_register_finds_old_case_beyond_first_two_hundred(client, db_session_factory):
    with db_session_factory() as db:
        old = add_case(db, name='Old Needle Workshop', reference='BRW-009876')
        old.created_at = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        for number in range(210):
            add_case(db, name=f'Synthetic recent case {number}')
        db.commit()
        old_id = old.id
    assert old_id not in [row['id'] for row in client.get('/score/applications', params={'limit': 200}).json()]
    response = client.get('/score/register', params={'search': 'needle'})
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 211 and body['matching'] == 1
    assert body['items'][0]['id'] == old_id
    assert client.get('/score/register', params={'search': 'brw-009876'}).json()['items'][0]['id'] == old_id


def test_literal_wildcards_and_quotes_are_not_query_syntax(client, db_session_factory):
    with db_session_factory() as db:
        add_case(db, name="100%_! O'Brien Workshop")
        add_case(db, name='Other workshop')
        db.commit()
    for search in ['%', '_', '!', "O'Brien", '100%_!']:
        body = client.get('/score/register', params={'search': search}).json()
        assert body['matching'] == 1, search
    assert client.get('/score/register', params={'search': "' OR 1=1 --"}).json()['matching'] == 0


def test_exact_case_ids_and_trimmed_case_insensitive_names(client, db_session_factory):
    with db_session_factory() as db:
        for _ in range(12):
            add_case(db, name='Synthetic Workshop')
        db.commit()
    for term in ['#2', '2', '0002']:
        assert [row['id'] for row in client.get('/score/register', params={'search': term}).json()['items']] == [2]
    # Names can also match numeric text; these names deliberately contain no numbers.
    assert client.get('/score/register', params={'search': '  wOrKsHoP  '}).json()['matching'] == 12


def test_recommendation_does_not_become_an_officer_decision(client, db_session_factory):
    with db_session_factory() as db:
        pending = add_case(db, recommendation='Approved', status='Pending')
        escalated = add_case(db, recommendation='Rejected', status='Escalated')
        approved = add_case(db, recommendation='Manual Review', status='Approved')
        add_case(db, status='Superseded')
        db.commit()
        ids = {pending.id, escalated.id}
    awaiting = client.get('/score/register', params={'status': 'Awaiting decision'}).json()
    assert {row['id'] for row in awaiting['items']} == ids
    assert all(row['final_decision'] is None for row in awaiting['items'])
    row, = client.get('/score/register', params={'status': 'Approved'}).json()['items']
    assert row['id'] == approved.id and row['decision'] == 'Manual Review' and row['final_decision'] == 'Approved'
    assert client.get('/score/register', params={'status': 'Superseded'}).json()['matching'] == 1


@pytest.mark.parametrize('sort', ['id', 'applicant_name', 'business_name', 'loan_amount_pkr',
    'tenure_months', 'risk_score', 'decision', 'final', 'created_at'])
def test_pagination_has_stable_ties_and_no_duplicates(client, db_session_factory, sort):
    with db_session_factory() as db:
        for _ in range(7):
            add_case(db)
        db.commit()
    pages = [client.get('/score/register', params={'sort': sort, 'limit': 3, 'offset': offset}).json() for offset in [0, 3, 6]]
    combined = [item['id'] for page in pages for item in page['items']]
    assert len(set(combined)) == 7
    assert combined == ([7, 6, 5, 4, 3, 2, 1])
    assert all(page['total'] == page['matching'] == 7 for page in pages)


def test_sort_is_global_and_recommendations_sort_by_displayed_wording(client, db_session_factory):
    with db_session_factory() as db:
        add_case(db, score=90, recommendation='Manual Review')
        add_case(db, score=20, recommendation='Approved')
        add_case(db, score=70, recommendation='Rejected')
        db.commit()
    assert [row['risk_score'] for row in client.get('/score/register', params={'sort': 'risk_score', 'direction': 'asc', 'limit': 2}).json()['items']] == [20, 70]
    assert [row['decision'] for row in client.get('/score/register', params={'sort': 'decision', 'direction': 'asc'}).json()['items']] == ['Approved', 'Rejected', 'Manual Review']


def test_compact_response_excludes_contact_and_private_financial_evidence(client, db_session_factory):
    with db_session_factory() as db:
        add_case(db)
        db.commit()
    row, = client.get('/score/register').json()['items']
    assert not {'contact_phone', 'turnover_evidence', 'raw_pd', 'policy_evaluation', 'review_note'} & row.keys()


def test_two_read_queries_and_no_mutation(db_session_factory):
    with db_session_factory() as db:
        add_case(db)
        db.commit()
        before = db.scalar(select(func.count(AuditLog.id)))
        statements = []
        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(db.bind, 'before_cursor_execute', capture)
        try:
            result = build_register(db, search='Synthetic', limit=1)
        finally:
            event.remove(db.bind, 'before_cursor_execute', capture)
        assert result.matching == 1 and len(statements) == 2
        assert all(statement.lstrip().upper().startswith('SELECT') for statement in statements)
        assert db.scalar(select(func.count(AuditLog.id))) == before


@pytest.mark.parametrize('params', [{'sort': 'DROP TABLE'}, {'direction': 'sideways'}, {'status': 'Finished'},
    {'limit': 101}, {'limit': 0}, {'offset': -1}, {'offset': 1000000001}, {'search': 'a' * 121}])
def test_query_constraints(client, params):
    assert client.get('/score/register', params=params).status_code == 422


def test_no_match_and_out_of_range_page_keep_true_counts(client, db_session_factory):
    with db_session_factory() as db:
        add_case(db)
        db.commit()
    missing = client.get('/score/register', params={'search': 'nonexistent'}).json()
    assert missing['items'] == [] and missing['total'] == 1 and missing['matching'] == 0
    beyond = client.get('/score/register', params={'offset': 25}).json()
    assert beyond['items'] == [] and beyond['total'] == beyond['matching'] == 1
