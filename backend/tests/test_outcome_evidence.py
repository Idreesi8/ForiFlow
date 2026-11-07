"""Repayment evidence must not turn missing, early or corrected data into outcomes."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from models.database import Application, AuditLog, Borrower, EWSTracking, ScoreSubmission
from services.outcome_evidence import anniversary, build_outcome_evidence
from tests.conftest import STRONG_APPLICANT

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def facility(db, *, anchor=datetime(2026, 1, 31, tzinfo=timezone.utc),
             source='officer', status='Approved', term=12, borrower=None):
    if borrower is None:
        borrower = Borrower(business_name='Fictional Workshop', owner_name='Fictional Owner')
        db.add(borrower)
        db.flush()
    row = Application(**{**STRONG_APPLICANT, 'tenure_months': term},
        borrower_id=borrower.id, risk_score=65, decision='Manual Review', decision_status=status,
        decision_source=source, reviewed_at=anchor, reviewed_by='admin',
        created_at=datetime(2025, 12, 1, tzinfo=timezone.utc), scoring_engine='surrogate',
        model_version='surrogate-linear-v1')
    db.add(row)
    db.flush()
    return row


def observe(db, app, number, **changes):
    when = anniversary(app.reviewed_at.date(), number)
    values = dict(borrower_id=app.id, month_number=number, installment_status='On Time',
        days_late=0, bureau_balance=100, pos_cash_balance=100, monthly_score=60,
        data_source_primary='Self Reported', amount_paid_pkr=100, observation_date=when,
        created_at=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
        created_by='admin', score_source='ews_rule_adjusted', record_status='active')
    row = EWSTracking(**{**values, **changes})
    db.add(row)
    db.flush()
    return row


def report(db, **changes):
    return build_outcome_evidence(db, now=NOW, **changes)


def test_no_approved_evidence_is_not_zero_default_or_perfect_accuracy(db_session_factory):
    with db_session_factory() as db:
        facility(db, status='Pending')
        facility(db, status='Rejected')
        facility(db, status='Superseded')
        result = report(db)
        assert result.total == result.counts.approved_facilities == 0
        assert not result.training_ready
        assert result.rows == []
        assert 'accuracy' not in result.model_dump()


def test_later_month_does_not_fill_an_earlier_gap(db_session_factory):
    with db_session_factory() as db:
        app = facility(db)
        observe(db, app, 3)
        row = report(db).rows[0]
        assert row.status == 'needs_evidence'
        assert row.missing_months == [1, 2]
        assert row.recorded_months == row.usable_months == 1


@pytest.mark.parametrize(('changes', 'reason'), [
    ({'amount_paid_pkr': None}, 'Payment amount unknown'),
    ({'days_late': None}, 'Exact days late unknown'),
    ({'days_late': 40}, 'Days late conflict'),
    ({'observation_date': None}, 'Observation date missing'),
    ({'observation_date': date(2026, 2, 1)}, 'predates'),
    ({'observation_date': date(2027, 1, 1)}, 'in the future'),
    ({'created_at': datetime(2027, 1, 1, tzinfo=timezone.utc)}, 'timestamp is in the future'),
    ({'created_by': None}, 'provenance incomplete'),
    ({'score_source': 'legacy_unknown'}, 'provenance incomplete'),
])
def test_incomplete_month_is_unknown_not_a_negative_label(db_session_factory, changes, reason):
    with db_session_factory() as db:
        app = facility(db)
        for number in (1, 2, 3):
            observe(db, app, number, **(changes if number == 3 else {}))
        row = report(db).rows[0]
        assert row.status == 'needs_evidence'
        assert row.incomplete_months == [3] and row.usable_months == 2
        assert any(reason in value for value in row.reasons)


def test_active_correction_replaces_the_old_signal_without_erasing_history(db_session_factory):
    with db_session_factory() as db:
        app = facility(db)
        original = observe(db, app, 1, installment_status='Default', days_late=90,
            record_status='superseded')
        observe(db, app, 1, supersedes_observation_id=original.id)
        observe(db, app, 2)
        observe(db, app, 3)
        result = report(db)
        assert result.counts.covered == 1
        assert result.counts.covered_with_30_plus == 0
        assert result.rows[0].recorded_months == 3
        assert db.scalar(select(func.count(EWSTracking.id))) == 4


def test_only_selected_window_counts_and_late_is_descriptive_not_default(db_session_factory):
    with db_session_factory() as db:
        app = facility(db)
        for number in (1, 2, 3, 4):
            observe(db, app, number, **({'installment_status':'Late 30-59','days_late':30} if number==4 else {}))
        assert report(db).counts.covered_with_30_plus == 0
        observe(db, app, 5)
        observe(db, app, 6)
        result = report(db, horizon=6)
        assert result.counts.covered_with_30_plus == result.counts.covered == 1
        assert not result.training_ready


def test_immature_short_and_legacy_facilities_are_separate(db_session_factory):
    with db_session_factory() as db:
        facility(db, anchor=datetime(2026, 10, 31, tzinfo=timezone.utc))
        facility(db, term=3)
        facility(db, anchor=None)
        facility(db, source='legacy_auto')
        result = report(db, horizon=6)
        assert result.counts.collecting == 1
        assert result.counts.shorter_term == 1
        assert result.counts.needs_approval_record == 2
        assert result.counts.approved_facilities == 4


def test_window_matures_on_pakistan_day_with_end_of_month_clamping(db_session_factory):
    with db_session_factory() as db:
        facility(db)
        before = build_outcome_evidence(db, now=datetime(2026, 4, 29, 18, 59, tzinfo=timezone.utc))
        after = build_outcome_evidence(db, now=datetime(2026, 4, 29, 19, tzinfo=timezone.utc))
        assert before.rows[0].status == 'collecting'
        assert after.rows[0].status == 'needs_evidence'
        assert after.rows[0].window_end == date(2026, 4, 30)


def test_repeated_facilities_are_one_real_borrower_and_counts_are_not_page_counts(db_session_factory):
    with db_session_factory() as db:
        first = facility(db)
        facility(db, borrower=db.get(Borrower, first.borrower_id))
        facility(db)
        result = report(db, limit=1, offset=1, status_filter='needs_evidence')
        assert result.counts.approved_facilities == result.total == 3
        assert result.counts.distinct_linked_borrowers == 2
        assert result.counts.additional_repeat_facilities == 1
        assert len(result.rows) == 1 and result.offset == 1
        assert report(db, offset=50).rows == []


def test_api_is_authenticated_no_store_and_read_only(client, db_session_factory, monkeypatch):
    monkeypatch.setattr('services.outcome_evidence.utc_now', lambda: NOW)
    with db_session_factory() as db:
        facility(db)
        db.commit()
        before = {model.__tablename__: db.scalar(select(func.count(model.id)))
            for model in (Application, AuditLog, ScoreSubmission)}
    response = client.get('/model/outcome-evidence', params={'horizon':6,'limit':1})
    assert response.status_code == 200, response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.json()['horizon_months'] == 6
    assert response.json()['counts']['approved_facilities'] == 1
    with db_session_factory() as db:
        assert before == {model.__tablename__: db.scalar(select(func.count(model.id)))
            for model in (Application, AuditLog, ScoreSubmission)}
    client.headers.pop('Authorization')
    assert client.get('/model/outcome-evidence').status_code == 401


@pytest.mark.parametrize('query', ['horizon=4','horizon=3.5','limit=0','limit=101','offset=-1','status_filter=defaulted'])
def test_bad_windows_paging_and_invented_labels_are_refused(client, query):
    assert client.get('/model/outcome-evidence?'+query).status_code == 422
