"""Concurrent financial writes on the disposable PostgreSQL test database."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from models.database import Application, AuditLog, Base, RepaymentReceipt, RepaymentSchedule, User
from repayment_schemas import ReceiptCreate, ScheduleCreate
from services import repayments
from services.audit_service import AuditContext
from tests.conftest import MID_APPLICANT, TEST_ADMIN_HASH

pytestmark = pytest.mark.postgres


@pytest.fixture
def ledger_pg(monkeypatch):
    url = os.environ.get('FORIFLOW_TEAM_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Dedicated PostgreSQL concurrency database is not configured')
    assert make_url(url).database == 'foriflow_team_test', 'Refuse to reset any other database'
    engine = create_engine(url, connect_args={'options': '-c statement_timeout=15000'})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    from business_time import business_date
    monkeypatch.setattr(repayments, 'business_date', lambda value=None: business_date(value) if value is not None else date(2026, 11, 8))
    monkeypatch.setattr(repayments, 'utc_now', lambda: datetime(2026, 11, 8, 10, tzinfo=timezone.utc))
    with factory() as db:
        db.add(User(id=1, username='ledger.qa', hashed_password=TEST_ADMIN_HASH, role='admin'))
        db.add(Application(id=1, **MID_APPLICANT, risk_score=60, decision='Manual Review',
            decision_status='Approved', decision_source='officer', reviewed_by='ledger.qa',
            reviewed_at=datetime(2026, 9, 30, tzinfo=timezone.utc)))
        db.commit()
    yield factory
    engine.dispose()


def schedule_body():
    return ScheduleCreate(submission_key=uuid4(), expected_schedule_id=None, disbursed_on='2026-10-01',
        items=[dict(due_on='2026-11-01', amount_pkr='100.01')], source_note='Fictional PostgreSQL contract QA-01')


@pytest.mark.parametrize('same_key', [False, True])
def test_concurrent_schedule_create_cannot_replace_an_unseen_contract(ledger_pg, same_key):
    barrier = Barrier(2)
    body = schedule_body()
    def save(payload):
        with ledger_pg() as db:
            actor = db.get(User, 1)
            barrier.wait(timeout=8)
            try:
                repayments.save_schedule(db, 1, payload, actor, AuditContext())
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, body), pool.submit(save, body if same_key else schedule_body())]
        assert sorted(f.result(timeout=30) for f in futures) == ([200, 200] if same_key else [200, 409])
    with ledger_pg() as db:
        assert len(db.scalars(select(RepaymentSchedule)).all()) == 1
        assert len(db.scalars(select(AuditLog)).all()) == 1


@pytest.mark.parametrize('same_reference', [False, True])
def test_concurrent_receipts_cannot_overallocate_or_duplicate_reference(ledger_pg, same_reference):
    with ledger_pg() as db:
        schedule_id = repayments.save_schedule(db, 1, schedule_body(), db.get(User, 1), AuditContext())['schedule']['id']
    barrier = Barrier(2)
    def save(number):
        with ledger_pg() as db:
            actor = db.get(User, 1)
            body = ReceiptCreate(submission_key=uuid4(), expected_schedule_id=schedule_id,
                paid_on='2026-11-02', reference='QA-PAY' if same_reference else f'QA-PAY-{number}',
                allocations=[dict(installment=1, amount_pkr='100.01')])
            barrier.wait(timeout=8)
            try:
                repayments.save_receipt(db, 1, body, actor, AuditContext())
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save, n) for n in (1, 2)]
        assert sorted(f.result(timeout=30) for f in futures) == [200, 409 if same_reference else 422]
    with ledger_pg() as db:
        assert len(db.scalars(select(RepaymentReceipt)).all()) == 1
        assert repayments.report(db, 1)['total_outstanding_pkr'] == '0.00'


def test_actor_permission_is_rechecked_inside_the_write_lock(ledger_pg):
    with ledger_pg() as stale:
        actor = stale.get(User, 1)
        assert actor.is_active
        with ledger_pg() as other:
            other.get(User, 1).is_active = False
            other.commit()
        with pytest.raises(HTTPException) as error:
            repayments.save_schedule(stale, 1, schedule_body(), actor, AuditContext())
        assert error.value.status_code == 403
        stale.rollback()
    with ledger_pg() as db:
        assert not db.scalars(select(RepaymentSchedule)).all()
        assert not db.scalars(select(AuditLog)).all()
