"""Overlapping activations on the already guarded disposable team test DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from models.database import AuditLog, CreditPolicy, User
from routers.policy import activate_policy_version
from schemas import PolicyActivation, PolicyCreate
from services import policy_service
from services.audit_service import AuditContext
from tests.test_policy_and_decisions import POLICY_V2
from tests.test_team_access_postgres import team_pg

pytestmark=pytest.mark.postgres


def test_two_reviewed_activations_serialize_before_locking_different_targets(team_pg):
    with team_pg() as db:
        actor=db.get(User,1);current=policy_service.active_policy(db)
        first=policy_service.create_version(db,PolicyCreate(**POLICY_V2),actor=actor,context=None)
        second=policy_service.create_version(db,PolicyCreate(**{**POLICY_V2,'version':'3.0'}),actor=actor,context=None)
        current_id,targets=current.id,[first.id,second.id];db.commit()
    barrier=Barrier(2)
    def change(target):
        with team_pg() as db:
            actor=db.get(User,1);barrier.wait(timeout=5)
            try:
                asyncio.run(activate_policy_version(target,db,actor,AuditContext(),PolicyActivation(expected_active_id=current_id,reason='Synthetic simultaneous review')))
                return 200
            except HTTPException as error:
                db.rollback();return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(change,target) for target in targets]
        assert sorted(future.result(timeout=20) for future in futures)==[200,409]
    with team_pg() as db:
        active=db.scalars(select(CreditPolicy).where(CreditPolicy.status=='active')).all()
        assert len(active)==1 and active[0].id in targets
        events=db.scalars(select(AuditLog).where(AuditLog.action=='policy.activated',AuditLog.entity_id.in_([str(target) for target in targets]))).all()
        assert len(events)==1 and events[0].details['reason']=='Synthetic simultaneous review'
