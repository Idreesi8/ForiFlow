"""Task ordering, complete-portfolio coverage and evidence integrity."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event, select

from models.database import Alert, Application, AuditLog, Borrower, EWSTracking, User
from services.action_desk import build_action_desk
from tests.conftest import STRONG_APPLICANT

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def application(db, *, status='Approved', name='Synthetic workshop', day=1):
    borrower = Borrower(business_name=name, owner_name='Synthetic owner')
    db.add(borrower)
    db.flush()
    stamp = datetime(2026, 10, day, 12, tzinfo=timezone.utc)
    app = Application(**{**STRONG_APPLICANT, 'business_name': name}, borrower_id=borrower.id,
        risk_score=82, decision='Approved', decision_status=status, created_at=stamp,
        reviewed_at=stamp if status == 'Approved' else None,
        escalated_at=stamp if status == 'Escalated' else None)
    db.add(app)
    db.flush()
    return app


def observation(db, app, month=1, *, amount=100, state='active'):
    db.add(EWSTracking(borrower_id=app.id, month_number=month, installment_status='On Time',
        bureau_balance=1, pos_cash_balance=850_000, monthly_score=82,
        amount_paid_pkr=amount, data_source_primary='Bank Statement', record_status=state))
    db.flush()


def alert(db, app, *, due=None, severity='WARNING', status='Open', owner=None):
    row = Alert(borrower_id=app.id, baseline_score=82, current_score=55, score_drop=27,
        estimated_days_to_default=40, alert_status=status, severity=severity,
        triggered_at=app.created_at, action_due_date=due, assigned_to=owner)
    db.add(row)
    db.flush()
    return row


def test_empty_desk_is_explicit_and_read_only(client, db_session_factory):
    with db_session_factory() as db:
        before = len(db.scalars(select(AuditLog)).all())
    result = client.get('/portfolio/action-desk')
    assert result.status_code == 200
    body = result.json()
    assert body['total_tasks'] == body['matching_tasks'] == body['application_count'] == 0
    assert body['items'] == [] and body['timezone'] == 'Asia/Karachi'
    with db_session_factory() as db:
        assert len(db.scalars(select(AuditLog)).all()) == before


def test_model_approval_is_still_a_pending_human_review(db_session_factory):
    with db_session_factory() as db:
        app = application(db, status='Pending')
        item, = build_action_desk(db, now=NOW).items
        assert item.id == f'review:{app.id}' and item.kind == 'review'
        assert item.required_role == 'manager_or_admin'
        assert '21 calendar days' in item.evidence[0]
        assert app.decision_status == 'Pending'


def test_priority_order_and_distinct_case_counts(db_session_factory):
    with db_session_factory() as db:
        pending = application(db, status='Pending')
        escalated = application(db, status='Escalated')
        standard = application(db)
        critical = application(db)
        overdue = application(db, day=20)
        normal_alert = alert(db, standard, owner='officer_a')
        critical_alert = alert(db, critical, severity='CRITICAL')
        late_alert = alert(db, overdue, due=date(2026, 10, 21))
        result = build_action_desk(db, now=NOW)
        assert [item.id for item in result.items[:5]] == [f'alert:{late_alert.id}', f'alert:{critical_alert.id}',
            f'alert:{normal_alert.id}', f'review:{escalated.id}', f'review:{pending.id}']
        assert result.total_tasks == 8 and result.application_count == 5
        assert result.counts_by_priority == {'urgent': 2, 'attention': 2, 'routine': 4}
        assert result.items[3].required_role == 'admin'
        assert result.items[2].assigned_to == 'officer_a'


def test_due_today_is_not_overdue_and_pakistan_midnight_is_respected(db_session_factory):
    with db_session_factory() as db:
        row = alert(db, application(db), due=date(2026, 10, 22))
        assert build_action_desk(db, now=NOW, kind='alert').items[0].priority == 'attention'
        after_midnight = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)
        item = build_action_desk(db, now=after_midnight, kind='alert').items[0]
        assert item.id == f'alert:{row.id}' and item.priority == 'urgent'
        assert '1 calendar days' in item.evidence[-2]


@pytest.mark.parametrize('status', ['Rejected', 'Superseded'])
def test_closed_assessments_and_their_open_legacy_alerts_do_not_leak_into_tasks(db_session_factory, status):
    with db_session_factory() as db:
        app = application(db, status=status)
        alert(db, app, severity=None)
        observation(db, app, month=3, amount=None)
        assert build_action_desk(db, now=NOW).total_tasks == 0


@pytest.mark.parametrize('status', ['Resolved', 'Dismissed'])
def test_closed_alerts_are_excluded(db_session_factory, status):
    with db_session_factory() as db:
        app = application(db)
        observation(db, app)
        alert(db, app, status=status, due=date(2026, 10, 1))
        assert build_action_desk(db, now=NOW).total_tasks == 0


def test_legacy_alert_has_no_invented_severity_or_owner(db_session_factory):
    with db_session_factory() as db:
        alert(db, application(db), severity=None)
        item, = build_action_desk(db, now=NOW, kind='alert').items
        assert item.priority == 'attention'
        assert item.assigned_to is None
        assert 'Legacy alert: no recorded severity.' in item.evidence


def test_later_months_expose_earlier_gaps_and_unknown_is_not_zero(db_session_factory):
    with db_session_factory() as db:
        app = application(db)
        observation(db, app, month=3, amount=None)
        item, = build_action_desk(db, now=NOW).items
        assert item.first_missing_month == 1
        assert any('2 earlier monitoring months missing' in fact for fact in item.evidence)
        assert any('unknown is not zero' in fact for fact in item.evidence)
        assert not any('arrears' in fact or 'unpaid' in fact for fact in item.evidence)


def test_corrections_use_active_rows_and_unknown_amounts_need_verification(db_session_factory):
    with db_session_factory() as db:
        app = application(db)
        observation(db, app, amount=None, state='superseded')
        observation(db, app, amount=0)
        assert build_action_desk(db, now=NOW).items == []
        observation(db, app, month=2, amount=None)
        item, = build_action_desk(db, now=NOW).items
        assert item.title == 'Verify unknown payment amounts'
        assert item.first_missing_month is None and item.required_role == 'manager_or_admin'


def test_no_monitoring_is_onboarding_and_has_no_invented_deadline(db_session_factory):
    with db_session_factory() as db:
        application(db, day=22)
        item, = build_action_desk(db, now=NOW).items
        assert item.title == 'Start facility monitoring'
        assert item.first_missing_month == 1 and item.due_date is None and item.priority == 'routine'


def test_pagination_search_and_totals_cover_more_than_the_old_200_row_register(db_session_factory):
    with db_session_factory() as db:
        for number in range(205):
            application(db, status='Pending', name=f'Workshop {number:03}')
        result = build_action_desk(db, now=NOW, limit=2, offset=200)
        assert result.total_tasks == result.matching_tasks == result.application_count == 205
        assert [item.business_name for item in result.items] == ['Workshop 200', 'Workshop 201']
        match = build_action_desk(db, now=NOW, search='WORKSHOP 204')
        assert match.total_tasks == 205 and match.matching_tasks == 1
        assert match.items[0].business_name == 'Workshop 204'
        assert build_action_desk(db, now=NOW, priority='urgent').items == []


@pytest.mark.parametrize('actionable_only', [False, True])
def test_desk_uses_three_read_only_queries_independent_of_case_count(db_session_factory, actionable_only):
    with db_session_factory() as db:
        for _ in range(12):
            application(db)
        calls = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            calls.append(statement)
        event.listen(db.bind, 'before_cursor_execute', capture)
        try:
            build_action_desk(db, now=NOW, actionable_only=actionable_only, officer_role='analyst')
        finally:
            event.remove(db.bind, 'before_cursor_execute', capture)
        assert len(calls) == 3
        assert all(statement.lstrip().upper().startswith('SELECT') for statement in calls)
        assert not db.dirty and not db.new and not db.deleted


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'offset=-1', 'kind=unknown', 'priority=extreme', 'search=' + 'x' * 101])
def test_api_validates_filter_and_page_boundaries(client, query):
    assert client.get('/portfolio/action-desk?' + query).status_code == 422


def test_api_requires_login(anonymous_client):
    assert anonymous_client.get('/portfolio/action-desk').status_code == 401


@pytest.mark.parametrize('role', ['analyst', 'manager', 'admin'])
def test_all_officer_roles_can_view_tasks(client, db_session_factory, role):
    with db_session_factory() as db:
        db.get(User, 1).role = role
        db.commit()
    assert client.get('/portfolio/action-desk').status_code == 200


def role_tasks(db):
    """Five synthetic tasks spanning all three existing authority groups."""
    application(db, status='Pending', name='Pending review')
    application(db, status='Escalated', name='Escalated review')
    alerted = application(db, name='Critical follow-up')
    observation(db, alerted)
    alert(db, alerted, severity='CRITICAL', owner='another_officer')
    unknown = application(db, name='Unknown amount')
    observation(db, unknown, amount=None)
    application(db, name='Start monitoring')


@pytest.mark.parametrize(('role', 'expected'), [
    ('analyst', ['Start monitoring']),
    ('manager', ['Critical follow-up', 'Pending review', 'Unknown amount', 'Start monitoring']),
    ('admin', ['Critical follow-up', 'Escalated review', 'Pending review', 'Unknown amount', 'Start monitoring']),
])
def test_role_filter_uses_current_database_role_not_token_or_client_claims(client, db_session_factory, role, expected):
    # The shared client's token still claims admin. The database is authoritative.
    with db_session_factory() as db:
        role_tasks(db)
        db.get(User, 1).role = role
        db.commit()
    body = client.get('/portfolio/action-desk?actionable_only=true&officer_role=admin').json()
    assert body['officer_role'] == role and body['actionable_only'] is True
    assert body['actionable_tasks'] == body['matching_tasks'] == len(expected)
    assert [item['business_name'] for item in body['items']] == expected
    assert body['total_tasks'] == body['application_count'] == 5
    assert sum(body['counts_by_kind'].values()) == sum(body['counts_by_priority'].values()) == 5
    all_roles = client.get('/portfolio/action-desk').json()
    assert len(all_roles['items']) == 5 and all_roles['actionable_only'] is False
    assert all_roles['actionable_tasks'] == len(expected)


def test_role_change_is_reflected_on_next_request_without_new_token(client, db_session_factory):
    with db_session_factory() as db:
        role_tasks(db)
        db.commit()
    assert client.get('/portfolio/action-desk?actionable_only=true').json()['matching_tasks'] == 5
    with db_session_factory() as db:
        db.get(User, 1).role = 'analyst'
        db.commit()
    body = client.get('/portfolio/action-desk?actionable_only=true').json()
    assert body['officer_role'] == 'analyst' and body['matching_tasks'] == 1


def test_role_filter_precedes_pagination_and_preserves_portfolio_counts(db_session_factory):
    with db_session_factory() as db:
        for number in range(205):
            application(db, status='Pending', name=f'Review {number}')
        for number in range(3):
            application(db, name=f'Monitor {number}')
        result = build_action_desk(db, now=NOW, actionable_only=True, officer_role='analyst',
                                   kind='monitoring', priority='routine', search='MONITOR', limit=1, offset=1)
        assert result.total_tasks == result.application_count == 208
        assert result.actionable_tasks == result.matching_tasks == 3
        assert [item.business_name for item in result.items] == ['Monitor 1']
        assert result.counts_by_kind == {'alert': 0, 'review': 205, 'monitoring': 3}
        assert build_action_desk(db, now=NOW, actionable_only=True, officer_role='analyst', kind='review').matching_tasks == 0


def test_role_counts_cover_complete_portfolio_even_when_other_filters_match_nothing(db_session_factory):
    with db_session_factory() as db:
        role_tasks(db)
        result = build_action_desk(db, now=NOW, actionable_only=True, officer_role='manager', search='no match')
        assert result.items == [] and result.matching_tasks == 0
        assert result.actionable_tasks == 4 and result.total_tasks == 5


def test_role_filter_does_not_grant_write_permissions(client, db_session_factory):
    with db_session_factory() as db:
        app = application(db)
        row = alert(db, app)
        alert_id = row.id
        db.get(User, 1).role = 'analyst'
        db.commit()
    assert client.get('/portfolio/action-desk?actionable_only=false').status_code == 200
    assert client.post(f'/ews/alerts/{alert_id}/acknowledge').status_code == 403


def test_role_filter_rejects_invalid_boolean(client):
    assert client.get('/portfolio/action-desk?actionable_only=maybe').status_code == 422
