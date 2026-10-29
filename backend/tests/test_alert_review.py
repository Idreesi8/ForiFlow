"""Fictional fixtures only: stale alert writes, disabled owners, current authority."""
import asyncio
from datetime import timedelta

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from business_time import business_date
from models.database import Alert, AuditLog, User
from routers.ews import assign_alert
from schemas import AlertAssignRequest, AlertResponse
from services.audit_service import AuditContext
from tests.test_ews_monitoring import facility_fixture, officers_fixture, _record


@pytest.fixture
def raised(client, facility, officers):
    return _record(client, facility, 1, installment_status='Default')['alert']


@pytest.mark.parametrize(('step','payload'), [
    ('acknowledge', {}), ('assign', {'assigned_to':'ana'}),
    ('due-date', {'due_date':(business_date()+timedelta(days=2)).isoformat()}),
    ('action-required', {'action_note':'Collect verified statements.'}),
    ('resolve', {'note':'Verified arrears were cleared.'}),
    ('dismiss', {'note':'Verified data-entry error.'}),
])
def test_all_reviewed_steps_refuse_stale_snapshot_without_audit(client, raised, step, payload):
    url=f"/ews/alerts/{raised['id']}"
    assert client.post(url+'/assign',json={'assigned_to':'mona'}).status_code==200
    before=client.get(url).json();history=client.get(url+'/history').json()
    response=client.post(url+'/'+step,json={**payload,'expected_review_token':raised['review_token']})
    assert response.status_code==409, response.text
    assert client.get(url).json()==before
    assert client.get(url+'/history').json()==history


def test_guard_binds_new_monitoring_evidence_too(client, raised, facility):
    _record(client,facility,2,installment_status='Default',bureau_balance=8000000)
    url=f"/ews/alerts/{raised['id']}"
    assert client.get(url).json()['review_token']!=raised['review_token']
    assert client.post(url+'/resolve',json={'note':'Old evidence was reviewed.','expected_review_token':raised['review_token']}).status_code==409


def test_fresh_review_saves_and_exact_replay_is_refused(client, raised):
    url=f"/ews/alerts/{raised['id']}";payload={'assigned_to':'ana','expected_review_token':raised['review_token']}
    saved=client.post(url+'/assign',json=payload)
    assert saved.status_code==200,saved.text
    assert saved.json()['review_token']!=raised['review_token']
    assert client.post(url+'/assign',json=payload).status_code==409
    assert len([event for event in client.get(url+'/history').json() if event['action']=='ews.alert_assigned'])==1


@pytest.mark.parametrize('step',['assign','action-required'])
def test_disabled_assignees_rejected_on_both_routes(client, raised, db_session_factory, step):
    url=f"/ews/alerts/{raised['id']}"
    if step=='action-required':assert client.post(url+'/acknowledge').status_code==200
    with db_session_factory() as db:
        db.scalar(select(User).where(User.username=='ana')).is_active=False;db.commit()
    before=client.get(url).json();history=client.get(url+'/history').json()
    result=client.post(url+'/'+step,json={'assigned_to':'ana','action_note':'Collect verified statements.'})
    assert result.status_code==422 and 'disabled' in result.json()['detail']
    assert client.get(url).json()==before and client.get(url+'/history').json()==history
    names=[user['username'] for user in client.get('/ews/assignees').json()]
    assert 'ana' not in names and 'mona' in names


def test_assignee_directory_has_minimal_fields_and_needs_manager(client, officers):
    result=client.get('/ews/assignees')
    assert result.status_code==200 and all(set(user)=={'username','role'} for user in result.json())
    assert client.get('/ews/assignees',headers=officers['analyst']).status_code==403


@pytest.mark.parametrize('change',['disabled','demoted'])
def test_authority_rechecked_even_when_dependency_user_is_stale(client, raised, db_session_factory, change):
    with db_session_factory() as action_db:
        actor=action_db.scalar(select(User).where(User.username=='mona'))
        with db_session_factory() as admin_db:
            target=admin_db.get(User,actor.id)
            if change=='disabled':target.is_active=False
            else:target.role='analyst'
            admin_db.commit()
        with pytest.raises(HTTPException) as error:
            asyncio.run(assign_alert(raised['id'],AlertAssignRequest(assigned_to='ana'),action_db,actor,AuditContext()))
        assert error.value.status_code==403
        action_db.rollback()
    assert client.get(f"/ews/alerts/{raised['id']}").json()['assigned_to'] is None


def test_review_token_does_not_change_at_midnight(client, raised):
    first=AlertResponse(**{key:value for key,value in raised.items() if key!='review_token'})
    second=first.model_copy(update={'is_overdue':not first.is_overdue,'business_name':'Renamed display'})
    assert first.review_token==second.review_token


@pytest.mark.parametrize('value',['wrong','f'*63,'G'*64,1])
def test_invalid_guard_is_not_silently_ignored(client, raised, value):
    response=client.post(f"/ews/alerts/{raised['id']}/assign",json={'assigned_to':'ana','expected_review_token':value})
    assert response.status_code==422
