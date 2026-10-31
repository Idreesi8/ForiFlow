"""Transactional assessment-save deduplication, scoped to the authenticated officer."""
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from models.database import ScoreSubmission, utcnow
from schemas import ScoreResponse


def claim_submission(db, *, officer_id, key, applicant, include_explanation):
    canonical = json.dumps({'version': 1, 'applicant': applicant.model_dump(mode='json'),
                            'include_explanation': include_explanation},
                           sort_keys=True, separators=(',', ':'), allow_nan=False)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    insert = postgres_insert if db.bind.dialect.name == 'postgresql' else sqlite_insert
    statement = insert(ScoreSubmission).values(user_id=officer_id, submission_key=str(key),
        payload_hash=fingerprint, created_at=utcnow()).on_conflict_do_nothing(
            index_elements=['user_id', 'submission_key']).returning(ScoreSubmission.id)
    created = db.execute(statement).scalar_one_or_none()
    # A conflicting INSERT waits for the first transaction: its case, audit and
    # receipt either commit together, or the reservation rolls back for retry.
    row = db.scalars(select(ScoreSubmission).where(ScoreSubmission.user_id == officer_id,
        ScoreSubmission.submission_key == str(key))).one()
    if row.payload_hash != fingerprint:
        raise HTTPException(status_code=409, detail='This submission key was already used for different assessment inputs. Use the original submission to recover its result.')
    if created is not None:
        return row, None
    if row.application_id is None or not row.response_json:
        raise HTTPException(status_code=409, detail='This assessment save has no verified receipt. Check the register before starting another submission.')
    receipt = ScoreResponse.model_validate(row.response_json)
    if receipt.application_id != row.application_id:
        raise HTTPException(status_code=409, detail='The saved receipt does not match its assessment. Check the register before starting another submission.')
    return row, receipt


def finish_submission(row, receipt):
    row.application_id = receipt.application_id
    row.response_json = receipt.model_dump(mode='json')
