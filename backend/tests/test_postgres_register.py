"""Check register query semantics on the explicitly supplied disposable PostgreSQL."""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from models.database import Base
from services.application_register import build_register
from tests.test_application_register import add_case


@pytest.mark.postgres
def test_register_search_and_global_sort_on_private_postgresql():
    address = os.getenv('FORIFLOW_TEST_POSTGRES_URL', '')
    if not address:
        pytest.skip('Private PostgreSQL URL not supplied')
    url = make_url(address)
    assert url.host == '127.0.0.1' and url.database.startswith('foriflow_test_'), 'Use only the private test runner'
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            old = add_case(db, name="Needle 100%_! O'Brien", reference='BRW-001234', score=18)
            for number in range(205):
                add_case(db, name='Synthetic recent business', status='Approved', score=80)
            add_case(db, status='Escalated', recommendation='Rejected', score=7)
            db.flush()
            for search in ['needle', '%', '_', '!', "O'Brien", 'brw-001234', f'#{old.id}']:
                result = build_register(db, search=search)
                assert result.matching == 1 and result.items[0].id == old.id
            result = build_register(db, status='Awaiting decision', sort='risk_score', direction='asc', limit=1)
            assert result.total == 207 and result.matching == 2
            assert result.items[0].risk_score == 7 and result.items[0].final_decision is None
            assert len(build_register(db, offset=200).items) == 7
            assert build_register(db, search="' OR 1=1 --").matching == 0
            db.rollback()
    finally:
        engine.dispose()
