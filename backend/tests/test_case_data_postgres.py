"""Concurrent append-only evidence writes on the dedicated disposable database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from case_data_schemas import RecordCreate, WithdrawRecord
from models.database import AuditLog, CaseDataRecord, User
from services import case_data
from services.audit_service import AuditContext
from tests.test_case_data import documented
from tests.test_repayments_postgres import ledger_pg

pytestmark = pytest.mark.postgres


@pytest.fixture
def evidence_pg(ledger_pg, monkeypatch):
    from business_time import business_date
    monkeypatch.setattr(case_data, 'business_date', lambda value=None: business_date(value) if value is not None else date(2026, 11, 8))
    monkeypatch.setattr(case_data, 'utc_now', lambda: datetime(2026, 11, 8, 12, tzinfo=timezone.utc))
    return ledger_pg


def initial(factory):
    with factory() as db:
        return case_data.write(db, 1, RecordCreate.model_validate(documented()), db.get(User, 1), AuditContext())['rows'][0]


def test_same_intent_concurrently_records_one_source_and_one_audit(evidence_pg):
    barrier = Barrier(2)
    payload = RecordCreate.model_validate(documented())
    def save():
        with evidence_pg() as db:
            actor = db.get(User, 1)
            barrier.wait(timeout=8)
            return case_data.write(db, 1, payload, actor, AuditContext())['total']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(save), pool.submit(save)]
        assert [future.result(timeout=30) for future in futures] == [1, 1]
    with evidence_pg() as db:
        assert len(db.scalars(select(CaseDataRecord)).all()) == 1
        assert len(db.scalars(select(AuditLog)).all()) == 1


def test_correction_and_withdrawal_compete_against_the_same_original_revision(evidence_pg):
    first = initial(evidence_pg)
    barrier = Barrier(2)
    def change(withdraw):
        with evidence_pg() as db:
            actor = db.get(User, 1)
            payload = WithdrawRecord(submission_key=uuid4(), reason='Fictional concurrent withdrawal QA-01') if withdraw else RecordCreate.model_validate(documented(note='Fictional concurrent correction QA-02'))
            barrier.wait(timeout=8)
            try:
                case_data.write(db, 1, payload, actor, AuditContext(), target_id=first['id'], withdraw=withdraw)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change, mode) for mode in (False, True)]
        assert sorted(f.result(timeout=30) for f in futures) == [200, 409]
    with evidence_pg() as db:
        assert len(db.scalars(select(CaseDataRecord)).all()) == 2
        assert len(db.scalars(select(AuditLog)).all()) == 2


@pytest.mark.parametrize('statement', ['UPDATE case_data_records SET note=note', 'DELETE FROM case_data_records', 'TRUNCATE case_data_records'])
def test_postgres_rejects_history_mutation_even_outside_the_api(evidence_pg, statement):
    initial(evidence_pg)
    with evidence_pg() as db:
        with pytest.raises(DBAPIError, match='append-only'):
            db.execute(text(statement))
        db.rollback()
        assert len(db.scalars(select(CaseDataRecord)).all()) == 1


def test_disabled_actor_is_rechecked_before_append(evidence_pg):
    with evidence_pg() as stale:
        actor = stale.get(User, 1)
        with evidence_pg() as other:
            other.get(User, 1).is_active = False
            other.commit()
        with pytest.raises(HTTPException) as error:
            case_data.write(stale, 1, RecordCreate.model_validate(documented()), actor, AuditContext())
        assert error.value.status_code == 403
        stale.rollback()
    with evidence_pg() as db:
        assert not db.scalars(select(CaseDataRecord)).all()
