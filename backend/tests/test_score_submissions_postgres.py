"""Overlapping assessment saves on a dedicated disposable PostgreSQL database."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import event, func, select

from models.database import Application, AuditLog, ScoreSubmission, User
from routers.score import score_application
from schemas import SMEApplicant
from services.audit_service import AuditContext
from services.scoring_service import ScoringService
from tests.conftest import STRONG_APPLICANT
from tests.test_team_access_postgres import team_pg

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize('mode', ['replay', 'changed', 'rollback'])
def test_overlapping_save_intents_are_atomic(team_pg, mode):
    first_inside, release_first, second_insert = Event(), Event(), Event()
    key = uuid4()

    class HeldScorer(ScoringService):
        def score(self, *args, **kwargs):
            first_inside.set()
            assert release_first.wait(8)
            if mode == 'rollback':
                raise RuntimeError('Fictional first transaction rollback')
            return super().score(*args, **kwargs)

    def observe(conn, cursor, statement, parameters, context, many):
        if conn.info.get('score_attempt') == 'second' and statement.startswith('INSERT INTO score_submissions'):
            second_insert.set()

    engine = team_pg.kw['bind']
    event.listen(engine, 'before_cursor_execute', observe)
    def save(first):
        with team_pg() as db:
            actor = db.get(User, 1)
            db.connection().info['score_attempt'] = 'first' if first else 'second'
            payload = {**STRONG_APPLICANT, **({'loan_amount_pkr': 2400001} if not first and mode == 'changed' else {})}
            response = Response()
            try:
                body = asyncio.run(score_application(applicant=SMEApplicant.model_validate(payload), db=db,
                    scorer=HeldScorer() if first else ScoringService(), officer=actor,
                    audit=AuditContext(), response=response, include_explanation=True, idempotency_key=key))
                return 201, body.model_dump(mode='json'), response.headers.get('Idempotency-Replayed')
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, None, None
            except RuntimeError:
                db.rollback()
                return 500, None, None
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save, True)
            assert first_inside.wait(8)
            second = pool.submit(save, False)
            try:
                assert second_insert.wait(8)
                assert not second.done(), 'Second save finished while the first transaction was held'
            finally:
                release_first.set()
            results = [first.result(timeout=20), second.result(timeout=20)]
    finally:
        release_first.set()
        event.remove(engine, 'before_cursor_execute', observe)
    assert [result[0] for result in results] == {'replay': [201, 201], 'changed': [201, 409], 'rollback': [500, 201]}[mode]
    if mode == 'replay':
        assert results[0][1] == results[1][1]
        assert [result[2] for result in results] == ['false', 'true']
    with team_pg() as db:
        assert db.scalar(select(func.count(Application.id))) == 1
        assert db.scalar(select(func.count(ScoreSubmission.id))) == 1
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == 'application.created')) == 1
