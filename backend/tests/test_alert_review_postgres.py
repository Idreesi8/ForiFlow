"""Overlapping writes on the guarded, disposable PostgreSQL test database only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

from fastapi import HTTPException
import pytest
from sqlalchemy import select, text

from models.database import Alert, Application, AuditLog, Borrower, User
from routers.ews import assign_alert
from schemas import AlertAssignRequest, AlertResponse
from services.audit_service import AuditContext
from services.team_access import lock_team_change
from tests.conftest import STRONG_APPLICANT
from tests.test_team_access_postgres import team_pg

pytestmark = pytest.mark.postgres


def seed_alert(factory):
    with factory() as db:
        borrower=Borrower(business_name='Synthetic review business',owner_name='Fictional officer fixture')
        db.add(borrower);db.flush()
        application=Application(**STRONG_APPLICANT,borrower_id=borrower.id,risk_score=75,decision='Approved',decision_status='Approved')
        db.add(application);db.flush()
        alert=Alert(borrower_id=application.id,baseline_score=75,current_score=40,score_drop=35,estimated_days_to_default=30)
        db.add(alert);db.commit();db.refresh(alert)
        return alert.id,AlertResponse.model_validate(alert).review_token


def test_concurrent_reviewed_reassignments_allow_exactly_one_write(team_pg):
    alert_id,token=seed_alert(team_pg);barrier=Barrier(2)
    def assign(actor_id,owner):
        with team_pg() as db:
            actor=db.get(User,actor_id)
            # Also preload the alert to prove populate_existing refreshes a stale identity map.
            db.get(Alert,alert_id);barrier.wait(timeout=5)
            try:
                asyncio.run(assign_alert(alert_id,AlertAssignRequest(assigned_to=owner,expected_review_token=token),db,actor,AuditContext()))
                return 200
            except HTTPException as error:
                db.rollback();return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(assign,1,'admin.one'),pool.submit(assign,2,'admin.two')]
        assert sorted(f.result(timeout=20) for f in futures)==[200,409]
    with team_pg() as db:
        assert db.get(Alert,alert_id).assigned_to in ('admin.one','admin.two')
        assert len(db.scalars(select(AuditLog).where(AuditLog.entity_type=='ews_alert')).all())==1


@pytest.mark.parametrize('target',['actor','assignee'])
def test_waiting_assignment_observes_committed_account_disable(team_pg,target):
    alert_id,token=seed_alert(team_pg);started=Event()
    def assign():
        with team_pg() as db:
            actor=db.get(User,2);assert actor.is_active
            started.set()
            try:
                asyncio.run(assign_alert(alert_id,AlertAssignRequest(assigned_to='admin.one',expected_review_token=token),db,actor,AuditContext()))
                return 200
            except HTTPException as error:
                db.rollback();return error.status_code
    with team_pg() as admin_db, ThreadPoolExecutor(max_workers=1) as pool:
        lock_team_change(admin_db,1)
        future=pool.submit(assign);assert started.wait(timeout=5)
        # Read pg_locks to establish that the action really is waiting on our lock.
        for _ in range(100):
            waiting=admin_db.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted"))
            if waiting:break
        assert waiting, 'The competing transaction never reached the access lock'
        admin_db.get(User,2 if target=='actor' else 1).is_active=False
        admin_db.commit()
        assert future.result(timeout=20)==(403 if target=='actor' else 422)
    with team_pg() as db:
        assert db.get(Alert,alert_id).assigned_to is None
        assert not db.scalars(select(AuditLog).where(AuditLog.entity_type=='ews_alert')).all()
