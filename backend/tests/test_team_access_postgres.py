"""Real overlapping transactions, only on an explicitly named disposable DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from models.database import Base, User, AuditLog
from routers.auth import set_user_role, set_user_status
from schemas import UserRoleUpdate, UserStatusUpdate
from services.audit_service import AuditContext
from tests.conftest import TEST_ADMIN_HASH

pytestmark=pytest.mark.postgres


@pytest.fixture
def team_pg():
    url=os.environ.get('FORIFLOW_TEAM_TEST_POSTGRES_URL')
    if not url: pytest.skip('Dedicated team PostgreSQL test database not configured')
    assert make_url(url).database=='foriflow_team_test', 'Refuse to reset any other database'
    engine=create_engine(url,connect_args={'options':'-c statement_timeout=10000'})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory() as db:
        db.add_all([User(id=1,username='admin.one',hashed_password=TEST_ADMIN_HASH,role='admin'),
                    User(id=2,username='admin.two',hashed_password=TEST_ADMIN_HASH,role='admin')]);db.commit()
    yield factory
    engine.dispose()


@pytest.mark.parametrize(('first_mode','second_mode'),[('role','role'),('status','status'),('role','status')])
def test_cross_admin_changes_preserve_one_enabled_admin(team_pg,first_mode,second_mode):
    """Both actors pass the initial role read before either mutation starts."""
    barrier=Barrier(2)
    def change(actor_id,target_id,mode):
        with team_pg() as db:
            actor=db.get(User,actor_id)
            assert actor.role=='admin' and actor.is_active
            barrier.wait(timeout=5)
            try:
                if mode=='role':
                    body=UserRoleUpdate(role='analyst',expected_role='admin',reason='Concurrent synthetic test')
                    asyncio.run(set_user_role(target_id,body,actor,db,AuditContext()))
                else:
                    body=UserStatusUpdate(is_active=False,expected_is_active=True,reason='Concurrent synthetic test')
                    asyncio.run(set_user_status(target_id,body,actor,db,AuditContext()))
                return 200
            except HTTPException as error:
                db.rollback();return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(change,1,2,first_mode);b=pool.submit(change,2,1,second_mode)
        outcomes=[a.result(timeout=20),b.result(timeout=20)]
    assert sorted(outcomes)==[200,403]
    with team_pg() as db:
        users=db.scalars(select(User)).all()
        assert sum(u.role=='admin' and u.is_active for u in users)==1
        assert len(db.scalars(select(AuditLog)).all())==1
