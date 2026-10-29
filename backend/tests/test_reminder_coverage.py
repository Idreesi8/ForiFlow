"""An out-of-order EWS month cannot make earlier missing installments disappear."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.database import Application
from routers import portfolio
import business_time
from tests.conftest import STRONG_APPLICANT, decide


@pytest.fixture(autouse=True)
def fixed_reminder_date(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 15, tzinfo=timezone.utc)

    monkeypatch.setattr(business_time, 'datetime', Clock)


def _facility(client, db_session_factory, *, tenure=3, amount=90_000):
    response = client.post('/score', json={
        **STRONG_APPLICANT, 'loan_amount_pkr': amount, 'tenure_months': tenure,
    })
    assert response.status_code == 201, response.text
    facility_id = response.json()['application_id']
    decide(client, facility_id)
    with db_session_factory() as db:
        application = db.get(Application, facility_id)
        application.reviewed_at = datetime(2026, 1, 31, tzinfo=timezone.utc)
        db.commit()
    return facility_id


def _record(client, facility_id, month, amount=30_000, status='On Time'):
    response = client.post('/ews/monitor', json={
        'borrower_id': facility_id, 'month_number': month,
        'installment_status': status, 'amount_paid_pkr': amount,
        'bureau_balance': 1, 'pos_cash_balance': 850_000,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _reminders(client):
    response = client.get('/portfolio/reminders')
    assert response.status_code == 200, response.text
    return {row['application_id']: row for row in response.json()}


def test_a_later_month_cannot_clear_the_first_missing_month(client, db_session_factory):
    facility_id = _facility(client, db_session_factory)
    _record(client, facility_id, 3)
    reminder = _reminders(client)[facility_id]
    assert reminder['installment_number'] == 1
    assert reminder['kind'] == 'overdue'
    assert reminder['due_date'] == '2026-02-28'
    assert reminder['days_until_due'] == -15
    assert reminder['latest_recorded_month'] == 3
    assert reminder['has_recording_gap'] is True
    assert reminder['arrears_pkr'] == 0  # a missing month is not invented payment evidence


def test_filling_a_gap_advances_to_the_next_missing_month_and_keeps_the_anchor(client, db_session_factory, monkeypatch):
    facility_id = _facility(client, db_session_factory)
    _record(client, facility_id, 3)
    _record(client, facility_id, 1)
    # Jan 31 -> Feb 28 -> Mar 31: do not compound February's clipped day.
    assert facility_id not in _reminders(client)

    class DueSoonClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 25, tzinfo=timezone.utc)

    monkeypatch.setattr(business_time, 'datetime', DueSoonClock)
    reminder = _reminders(client)[facility_id]
    assert reminder['installment_number'] == 2
    assert reminder['due_date'] == '2026-03-31'
    assert reminder['days_until_due'] == 6
    assert reminder['has_recording_gap'] is True
    _record(client, facility_id, 2)
    assert facility_id not in _reminders(client)


def test_payment_amounts_that_are_not_recorded_stay_unknown(client, db_session_factory):
    facility_id = _facility(client, db_session_factory)
    _record(client, facility_id, 3, amount=None)
    reminder = _reminders(client)[facility_id]
    assert reminder['recorded_months_without_amount'] == 1
    assert reminder['arrears_pkr'] == 0
    assert reminder['installment_number'] == 1


def test_gap_and_known_later_shortfall_are_reported_without_calling_it_earlier_arrears(client, db_session_factory):
    facility_id = _facility(client, db_session_factory)
    _record(client, facility_id, 3, amount=10_000)
    reminder = _reminders(client)[facility_id]
    assert reminder['arrears_pkr'] == 20_000
    assert reminder['has_recording_gap'] is True
    assert 'PKR 20,000.00 in recorded installments' in reminder['message_en']
    assert 'earlier installments' not in reminder['message_en']


def test_whole_rupee_tolerance_is_preserved_and_drafts_keep_paisa(client, db_session_factory):
    facility_id = _facility(client, db_session_factory, amount=100_000)
    _record(client, facility_id, 3, amount=33_333)
    reminder = _reminders(client)[facility_id]
    assert reminder['arrears_pkr'] == 0
    assert reminder['installment_pkr'] == 33_333.33
    assert 'PKR 33,333.33' in reminder['message_en']
    assert 'PKR 33,333.33' in reminder['message_ur']


def test_latest_default_still_goes_to_remedial_management(client, db_session_factory):
    facility_id = _facility(client, db_session_factory)
    _record(client, facility_id, 3, amount=0, status='Default')
    assert facility_id not in _reminders(client)


def test_corrections_use_only_active_amounts_and_leave_gap_coverage_intact(client, db_session_factory):
    facility_id = _facility(client, db_session_factory)
    original = _record(client, facility_id, 3, amount=None)
    corrected = client.post(f"/ews/observations/{original['tracking']['id']}/correct", json={
        'installment_status': 'On Time', 'amount_paid_pkr': 10_000,
        'bureau_balance': 1, 'pos_cash_balance': 850_000,
        'correction_reason': 'Verified the missing amount against the payment receipt.',
    })
    assert corrected.status_code == 201, corrected.text
    reminder = _reminders(client)[facility_id]
    assert reminder['installment_number'] == 1
    assert reminder['latest_recorded_month'] == 3
    assert reminder['recorded_months_without_amount'] == 0
    assert reminder['arrears_pkr'] == 20_000
