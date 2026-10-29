"""Account role transitions, current authority and append-only access history."""
import pytest
from sqlalchemy import select
from models.database import AuditLog, User
from services.audit_service import Action, record
from tests.conftest import TEST_ADMIN_HASH, bearer_header


def officer(factory, role='analyst', active=True, username='role.officer'):
    with factory() as db:
        user = User(username=username, hashed_password=TEST_ADMIN_HASH, role=role, is_active=active)
        db.add(user); db.commit(); return user.id


def payload(role='manager', expected='analyst'):
    return {'role':role, 'expected_role':expected, 'reason':'Branch responsibilities updated.'}


@pytest.mark.parametrize(('before','after'),[(a,b) for a in ('admin','manager','analyst') for b in ('admin','manager','analyst') if a!=b])
def test_role_transition_is_atomic_and_audited(client, db_session_factory, before, after):
    uid=officer(db_session_factory,before)
    response=client.patch(f'/auth/users/{uid}/role',json=payload(after,before))
    assert response.status_code==200,response.text
    assert response.json()['role']==after and 'hashed_password' not in response.text
    with db_session_factory() as db:
        assert db.get(User,uid).role==after
        events=db.scalars(select(AuditLog).where(AuditLog.action==Action.USER_ROLE_CHANGED)).all()
        assert len(events)==1
        event=events[0]
        assert event.entity_id==str(uid) and event.username=='admin' and event.role=='admin'
        assert event.previous_state=={'role':before} and event.new_state['role']==after
        assert event.details['reason']=='Branch responsibilities updated.'


@pytest.mark.parametrize('role',['manager','analyst'])
def test_non_admin_cannot_change_role_or_read_account_history(client,db_session_factory,role):
    uid=officer(db_session_factory,role)
    headers=bearer_header('role.officer','admin')  # signed claim cannot grant admin
    assert client.patch(f'/auth/users/1/role',json=payload(),headers=headers).status_code==403
    assert client.get(f'/auth/users/{uid}/access-history',headers=headers).status_code==403


def test_anonymous_cannot_change_or_inspect_accounts(anonymous_client):
    assert anonymous_client.patch('/auth/users/1/role',json=payload()).status_code==401
    assert anonymous_client.get('/auth/users/1/access-history').status_code==401


def test_demoting_own_account_is_refused_without_losing_last_admin(client,db_session_factory):
    admin=client.get('/auth/me').json()
    response=client.patch(f"/auth/users/{admin['id']}/role",json=payload('analyst','admin'))
    assert response.status_code==409 and 'own role' in response.json()['detail']
    assert client.get('/auth/users').status_code==200
    with db_session_factory() as db:
        assert not db.scalars(select(AuditLog).where(AuditLog.action==Action.USER_ROLE_CHANGED)).all()


def test_stale_request_cannot_overwrite_and_repeat_is_noop(client,db_session_factory):
    uid=officer(db_session_factory)
    assert client.patch(f'/auth/users/{uid}/role',json=payload()).status_code==200
    assert client.patch(f'/auth/users/{uid}/role',json=payload('admin')).status_code==409
    assert client.patch(f'/auth/users/{uid}/role',json=payload('manager','manager')).status_code==200
    assert len(client.get(f'/auth/users/{uid}/access-history').json())==1


def test_existing_token_observes_promotion_and_demotion_immediately(client,db_session_factory):
    uid=officer(db_session_factory)
    token=bearer_header('role.officer','analyst')
    assert client.get('/auth/users',headers=token).status_code==403
    assert client.patch(f'/auth/users/{uid}/role',json=payload('admin')).status_code==200
    assert client.get('/auth/users',headers=token).status_code==200
    assert client.get('/auth/me',headers=token).json()['role']=='admin'
    assert client.patch(f'/auth/users/{uid}/role',json=payload('analyst','admin')).status_code==200
    assert client.get('/auth/users',headers=token).status_code==403
    assert client.get('/auth/me',headers=token).json()['role']=='analyst'


def test_role_change_does_not_enable_disabled_account(client,db_session_factory):
    uid=officer(db_session_factory,active=False)
    response=client.patch(f'/auth/users/{uid}/role',json=payload('admin'))
    assert response.status_code==200 and response.json()['is_active'] is False
    assert client.get('/auth/me',headers=bearer_header('role.officer','admin')).status_code==401


@pytest.mark.parametrize('body',[
    {'role':'owner','expected_role':'analyst','reason':'reason'},
    {'role':'admin','reason':'reason'},
    {'role':'admin','expected_role':'analyst','reason':'   '},
    {'role':'admin','expected_role':'analyst','reason':'x'*301},
    {'role':'admin','expected_role':'analyst','reason':'reason','is_active':True},
])
def test_invalid_role_payload_is_refused(client,body):
    assert client.patch('/auth/users/1/role',json=body).status_code==422


def test_missing_target_and_stale_status(client,db_session_factory):
    assert client.patch('/auth/users/99999/role',json=payload()).status_code==404
    assert client.get('/auth/users/99999/access-history').status_code==404
    uid=officer(db_session_factory)
    response=client.patch(f'/auth/users/{uid}/status',json={'is_active':False,'expected_is_active':False})
    assert response.status_code==409
    assert client.get('/auth/users').json()[-1]['is_active'] is True


def test_access_history_is_scoped_bounded_and_excludes_signins(client,db_session_factory):
    uid=officer(db_session_factory)
    other=officer(db_session_factory,username='other.officer')
    with db_session_factory() as db:
        for i in range(55):
            record(db,action=Action.USER_ROLE_CHANGED,entity_type='user',entity_id=uid,
                   username='test.audit',previous={'role':'analyst'},new={'role':'manager'},details={'reason':f'Change {i}'})
        record(db,action=Action.LOGIN,entity_type='user',entity_id=uid,username='test.audit')
        record(db,action=Action.USER_DISABLED,entity_type='user',entity_id=other,username='other.audit')
        db.commit()
    response=client.get(f'/auth/users/{uid}/access-history')
    assert response.status_code==200
    rows=response.json()
    assert len(rows)==50 and all(row['action']==Action.USER_ROLE_CHANGED for row in rows)
    assert rows[0]['details']['reason']=='Change 54' and rows[-1]['details']['reason']=='Change 5'
    assert 'ip_address' not in rows[0] and 'hashed_password' not in response.text


def test_actor_is_rechecked_after_serialisation(db_session_factory):
    from fastapi import HTTPException
    from services.team_access import lock_team_change
    with db_session_factory() as db:
        actor=db.scalar(select(User).where(User.username=='admin'))
        actor.role='analyst';db.commit()
        with pytest.raises(HTTPException) as error: lock_team_change(db,actor.id)
        assert error.value.status_code==403


def test_audit_failure_rolls_back_role_change(client,db_session_factory,monkeypatch):
    uid=officer(db_session_factory)
    from routers import auth
    def fail(*args,**kwargs): raise RuntimeError('synthetic audit failure')
    monkeypatch.setattr(auth.audit_service,'record',fail)
    with pytest.raises(RuntimeError,match='synthetic audit failure'):
        client.patch(f'/auth/users/{uid}/role',json=payload())
    with db_session_factory() as db: assert db.get(User,uid).role=='analyst'
