"""Reviewed activation is stale-safe, transactional and compatible with old callers."""
import asyncio

from fastapi import HTTPException
import pytest
from sqlalchemy import select, update

from models.database import AuditLog, CreditPolicy, User
from routers.policy import activate_policy_version
from schemas import PolicyActivation
from services import audit_service
from services.audit_service import AuditContext
from tests.test_policy_and_decisions import POLICY_V2


def prepare(client):
    current=client.get('/policy/active').json()
    draft=client.post('/policy/versions',json=POLICY_V2)
    assert draft.status_code==201
    return current,draft.json()


def state(factory):
    with factory() as db:
        return {'policies':[(p.id,p.status,p.activated_at,p.retired_at) for p in db.scalars(select(CreditPolicy).order_by(CreditPolicy.id))],
                'audit':[(a.id,a.action,a.details) for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]}


def test_reviewed_activation_records_trimmed_reason_on_both_events(client,db_session_factory):
    current,draft=prepare(client)
    result=client.post(f"/policy/versions/{draft['id']}/activate",json={'expected_active_id':current['id'],'reason':'  Synthetic reviewed policy change  '})
    assert result.status_code==200,result.text
    with db_session_factory() as db:
        events=db.scalars(select(AuditLog).where(AuditLog.action.in_(['policy.activated','policy.retired'])).order_by(AuditLog.id)).all()
        assert len(events)==3  # seeded activation plus this retirement/activation
        assert all(event.details['reason']=='Synthetic reviewed policy change' for event in events[-2:])
        assert all(event.username=='admin' for event in events[-2:])


def test_stale_review_cannot_replace_an_intervening_activation(client,db_session_factory):
    current,draft=prepare(client)
    other=client.post('/policy/versions',json={**POLICY_V2,'version':'3.0'}).json()
    assert client.post(f"/policy/versions/{other['id']}/activate").status_code==200
    before=state(db_session_factory)
    result=client.post(f"/policy/versions/{draft['id']}/activate",json={'expected_active_id':current['id'],'reason':'Synthetic stale comparison'})
    assert result.status_code==409 and 'changed' in result.json()['detail']
    assert state(db_session_factory)==before


@pytest.mark.parametrize('body',[{}, {'reason':'valid reason'}, {'expected_active_id':1},
    {'expected_active_id':0,'reason':'valid reason'}, {'expected_active_id':True,'reason':'valid reason'},
    {'expected_active_id':'1','reason':'valid reason'}, {'expected_active_id':1,'reason':'  '},
    {'expected_active_id':1,'reason':'ab'}, {'expected_active_id':1,'reason':'x'*301},
    {'expected_active_id':1,'reason':'valid reason','unknown':1}])
def test_invalid_review_body_never_changes_policy_or_audit(client,db_session_factory,body):
    _,draft=prepare(client);before=state(db_session_factory)
    assert client.post(f"/policy/versions/{draft['id']}/activate",json=body).status_code==422
    assert state(db_session_factory)==before


def test_explicit_no_active_expectation_is_not_a_bypass(client,db_session_factory):
    _,draft=prepare(client);before=state(db_session_factory)
    assert client.post(f"/policy/versions/{draft['id']}/activate",json={'expected_active_id':None,'reason':'Synthetic null expectation'}).status_code==409
    assert state(db_session_factory)==before


def test_actor_is_rechecked_after_lock_even_if_initial_admin_object_is_stale(client,db_session_factory):
    current,draft=prepare(client)
    with db_session_factory() as stale:
        actor=stale.scalar(select(User).where(User.username=='admin'))
        with db_session_factory() as other:
            other.execute(update(User).where(User.id==actor.id).values(role='analyst'));other.commit()
        assert actor.role=='admin'
        with pytest.raises(HTTPException) as error:
            asyncio.run(activate_policy_version(draft['id'],stale,actor,AuditContext(),PolicyActivation(expected_active_id=current['id'],reason='Synthetic stale authority')))
        assert error.value.status_code==403
    assert client.get('/policy/active').json()['id']==current['id']


def test_audit_failure_rolls_back_retirement_and_activation(client,db_session_factory,monkeypatch):
    current,draft=prepare(client);before=state(db_session_factory)
    def fail(*args,**kwargs):raise RuntimeError('Synthetic audit unavailable')
    monkeypatch.setattr(audit_service,'record',fail)
    with pytest.raises(RuntimeError,match='Synthetic audit unavailable'):
        client.post(f"/policy/versions/{draft['id']}/activate",json={'expected_active_id':current['id'],'reason':'Synthetic transaction test'})
    assert state(db_session_factory)==before
