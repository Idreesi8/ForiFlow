"""A save intent may be retried without creating another assessment."""
from uuid import uuid4
import pytest

from sqlalchemy import func, select

from models.database import Application, AuditLog, Borrower, ScoreSubmission, User
from tests.conftest import STRONG_APPLICANT, TEST_ADMIN_HASH, bearer_header, decide


def test_same_submission_key_replays_the_original_case(client, db_session_factory):
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    assert first.status_code == 201, first.text
    with db_session_factory() as db:
        audit_count = db.scalar(select(func.count(AuditLog.id)))
    second = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    assert second.status_code == 201, second.text
    with db_session_factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 1
        assert db.scalar(select(func.count(AuditLog.id))) == audit_count
    assert second.json() == first.json()
    assert second.headers['Idempotency-Replayed'] == 'true'


def test_key_binds_to_the_reviewed_inputs(client, db_session_factory):
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    changed = client.post('/score', json={**STRONG_APPLICANT, 'loan_amount_pkr': 2400001}, headers=headers)
    assert changed.status_code == 409
    assert 'different assessment inputs' in changed.json()['detail']
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).json() == first.json()
    with db_session_factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 1


def test_equivalent_normalized_inputs_replay(client):
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    same = {**STRONG_APPLICANT, 'applicant_name': '  '+STRONG_APPLICANT['applicant_name']+' ',
            'loan_amount_pkr': 2400000.0}
    assert client.post('/score', json=same, headers=headers).json() == first.json()


def test_explicit_new_key_is_a_separate_assessment_and_legacy_callers_still_work(client, db_session_factory):
    bodies = [client.post('/score', json=STRONG_APPLICANT, headers={'Idempotency-Key': str(uuid4())}).json()
              for _ in range(2)]
    legacy = client.post('/score', json=STRONG_APPLICANT)
    assert legacy.status_code == 201 and len({body['application_id'] for body in bodies}) == 2
    with db_session_factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 3
        assert db.scalar(select(func.count(ScoreSubmission.id))) == 2


def test_same_key_is_scoped_to_each_authenticated_officer(client, db_session_factory):
    with db_session_factory() as db:
        db.add(User(username='second.officer', hashed_password=TEST_ADMIN_HASH, role='analyst'))
        db.commit()
    key = str(uuid4())
    first = client.post('/score', json=STRONG_APPLICANT, headers={'Idempotency-Key': key})
    headers = {**bearer_header('second.officer', 'analyst'), 'Idempotency-Key': key}
    second = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    assert second.status_code == 201
    assert second.json()['application_id'] != first.json()['application_id']
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).json() == second.json()


def test_replay_keeps_original_model_receipt_after_officer_decision(client, db_session_factory):
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    decide(client, first.json()['application_id'])
    with db_session_factory() as db:
        audits = db.scalar(select(func.count(AuditLog.id)))
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).json() == first.json()
    assert client.get(f"/score/applications/{first.json()['application_id']}").json()['decision_status'] == 'Approved'
    with db_session_factory() as db:
        assert db.scalar(select(func.count(AuditLog.id))) == audits


def test_replay_does_not_rescore_when_the_model_changes(client, monkeypatch):
    from main import app
    from services.scoring_service import get_scoring_service
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=STRONG_APPLICANT, headers=headers)
    class MustNotScore:
        def score(self, *args, **kwargs):
            raise AssertionError('Replay invoked the scorer')
    monkeypatch.setitem(app.dependency_overrides, get_scoring_service, lambda: MustNotScore())
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).json() == first.json()


def test_explanation_option_is_part_of_the_save_intent(client):
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score?include_explanation=false', json=STRONG_APPLICANT, headers=headers)
    assert first.status_code == 201 and first.json()['explanation'] is None
    assert client.post('/score?include_explanation=false', json=STRONG_APPLICANT, headers=headers).json() == first.json()
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).status_code == 409


def test_rescore_retry_returns_the_existing_replacement_after_original_is_superseded(client, db_session_factory):
    original = client.post('/score', json=STRONG_APPLICANT).json()
    payload = {**STRONG_APPLICANT, 'rescore_of_application_id': original['application_id'], 'loan_amount_pkr': 2300000}
    headers = {'Idempotency-Key': str(uuid4())}
    first = client.post('/score', json=payload, headers=headers)
    assert first.status_code == 201
    assert client.post('/score', json=payload, headers=headers).json() == first.json()
    with db_session_factory() as db:
        assert db.scalar(select(func.count(Application.id))) == 2
        assert db.get(Application, original['application_id']).decision_status == 'Superseded'
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'application.rescored')) == 1


@pytest.mark.parametrize('key', ['', 'not-a-uuid', 'x'*500])
def test_invalid_key_is_rejected_before_writing(client, db_session_factory, key):
    assert client.post('/score', json=STRONG_APPLICANT, headers={'Idempotency-Key': key}).status_code == 422
    with db_session_factory() as db:
        assert db.scalar(select(func.count(Application.id))) == db.scalar(select(func.count(ScoreSubmission.id))) == 0


def test_validation_failure_does_not_consume_the_key(client, db_session_factory):
    headers = {'Idempotency-Key': str(uuid4())}
    assert client.post('/score', json={**STRONG_APPLICANT, 'tenure_months': 0}, headers=headers).status_code == 422
    with db_session_factory() as db:
        assert db.scalar(select(func.count(ScoreSubmission.id))) == 0
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).status_code == 201


def test_failed_transaction_rolls_back_case_borrower_reservation_and_audit(client, db_session_factory, monkeypatch):
    from main import app
    from services.scoring_service import ScoringService, get_scoring_service
    class BrokenScorer(ScoringService):
        def score(self, *args, **kwargs):
            raise RuntimeError('Fictional scoring failure')
    headers = {'Idempotency-Key': str(uuid4())}
    with db_session_factory() as db:
        before = db.scalar(select(func.count(AuditLog.id)))
    with monkeypatch.context() as patch:
        patch.setitem(app.dependency_overrides, get_scoring_service, lambda: BrokenScorer())
        with pytest.raises(RuntimeError, match='Fictional scoring failure'):
            client.post('/score', json=STRONG_APPLICANT, headers=headers)
    with db_session_factory() as db:
        for model in (Application, Borrower, ScoreSubmission):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count(AuditLog.id))) == before
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).status_code == 201


def test_disabled_officer_cannot_replay(client, db_session_factory):
    headers = {'Idempotency-Key': str(uuid4())}
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).status_code == 201
    with db_session_factory() as db:
        db.scalars(select(User).where(User.username == 'admin')).one().is_active = False
        db.commit()
    assert client.post('/score', json=STRONG_APPLICANT, headers=headers).status_code == 401


def test_replay_needs_authentication(client, anonymous_client):
    assert anonymous_client.post('/score', json=STRONG_APPLICANT, headers={'Idempotency-Key': str(uuid4())}).status_code == 401
