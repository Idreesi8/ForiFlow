"""Unsaved checks use real trained inputs and never create a credit record."""
import copy
import json

import pytest
from sqlalchemy import event

from diagnostic_schemas import ModelInputRequest, InputApplicability
from schemas import SMEApplicant
from services import applicability_service
from services.input_checks import describe_inputs
from tests.conftest import STRONG_APPLICANT
from tests.test_model_diagnostics import snapshot

FIELDS = tuple(ModelInputRequest.model_fields)
DRAFT = {name: STRONG_APPLICANT[name] for name in FIELDS}


def test_requires_authentication(anonymous_client):
    assert anonymous_client.post('/model/input-checks', json=DRAFT).status_code == 401


@pytest.mark.parametrize('role', ['analyst', 'manager', 'admin'])
def test_every_officer_can_inspect_without_deciding(ml_client, db_session_factory, role):
    from models.database import User
    with db_session_factory() as db:
        db.get(User, 1).role = role
        db.commit()
    response = ml_client.post('/model/input-checks', json=DRAFT)
    assert response.status_code == 200 and response.json()['status'] == 'ready'


@pytest.mark.parametrize('changes', [
    {}, {'monthly_digital_payments': 0, 'cash_flow_proxy': 3_200_000},
    {'monthly_digital_payments': 0, 'cash_flow_proxy': 0},
    {'loan_amount_pkr': 1000, 'years_in_operation': 40},
    {'payment_history_score': 52.5}, {'payment_history_score': 52.5001},
    {'loan_amount_pkr': 500_000_000, 'monthly_digital_payments': 1_000_000_000},
])
def test_draft_matches_canonical_credit_feature_mapping_and_real_anomaly(ml_client, ml_service, changes):
    inputs = {**DRAFT, **changes}
    response = ml_client.post('/model/input-checks', json=inputs)
    assert response.status_code == 200, response.text
    report = response.json()
    _, effective, raw = ml_service._feature_frame(SMEApplicant(**{**STRONG_APPLICANT, **changes}))
    assert report['inputs'] == inputs
    assert report['input_checks'] == describe_inputs(ml_service, raw, effective)
    assert report['applicability'] == InputApplicability(**applicability_service.assess(ml_service, raw)).model_dump(mode='json')
    assert report['credit_artifact_sha256'] == ml_service.artifact_sha256
    assert report['model_version'] == ml_service.model_version
    assert response.headers['cache-control'] == 'no-store'
    assert not {'risk_score', 'recommendation', 'application_id', 'borrower_id'} & report.keys()


def test_checks_cannot_call_scoring_registration_or_mutate_any_table(ml_client, ml_service, db_session_factory, monkeypatch):
    before = snapshot(db_session_factory)
    statements = []
    engine = db_session_factory.kw['bind']
    def capture(_conn, _cursor, statement, *_args): statements.append(statement.strip())
    def forbidden(*_args, **_kwargs): pytest.fail('Credit inference or registration called')
    monkeypatch.setattr(ml_service, 'score', forbidden)
    monkeypatch.setattr(ml_service, '_member_probabilities', forbidden)
    monkeypatch.setattr('services.model_registry.ensure_registered', forbidden)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        for _ in range(3):
            assert ml_client.post('/model/input-checks', json=DRAFT).json()['status'] == 'ready'
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert snapshot(db_session_factory) == before
    assert statements and all(statement.upper().startswith('SELECT') for statement in statements)


@pytest.mark.parametrize('field,value', [
    ('loan_amount_pkr', 0), ('loan_amount_pkr', 500_000_001),
    ('monthly_digital_payments', -1), ('monthly_digital_payments', 1_000_000_001),
    ('cash_flow_proxy', -1), ('cash_flow_proxy', 1_000_000_001),
    ('payment_history_score', -1), ('payment_history_score', 100.01),
    ('years_in_operation', -0.1), ('years_in_operation', 100.01),
    ('loan_amount_pkr', True), ('cash_flow_proxy', 'Infinity'),
    ('payment_history_score', None),
])
def test_invalid_or_non_numeric_figures_are_rejected(client, field, value):
    assert client.post('/model/input-checks', json={**DRAFT, field: value}).status_code == 422


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity'])
def test_nonfinite_json_is_rejected_safely(client, literal):
    body = json.dumps(DRAFT).replace(str(DRAFT['loan_amount_pkr']), literal, 1)
    assert client.post('/model/input-checks', content=body, headers={'Content-Type': 'application/json'}).status_code == 422


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity'])
def test_existing_assessment_validation_also_rejects_nonfinite_json_safely(client, literal):
    body = json.dumps(STRONG_APPLICANT).replace(str(STRONG_APPLICANT['loan_amount_pkr']), literal, 1)
    response = client.post('/score', content=body, headers={'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], list)


@pytest.mark.parametrize('extra', ['applicant_name', 'borrower_identifier', 'statement_csv', 'tenure_months'])
def test_identity_documents_and_unused_fields_are_not_accepted(client, extra):
    assert client.post('/model/input-checks', json={**DRAFT, extra: 'not part of this contract'}).status_code == 422


def test_incomplete_inputs_are_not_imputed(client):
    for name in FIELDS:
        inputs = copy.copy(DRAFT)
        inputs.pop(name)
        assert client.post('/model/input-checks', json=inputs).status_code == 422


def test_missing_reference_is_honest_partial_with_valid_transformations(ml_client, monkeypatch, tmp_path):
    monkeypatch.setattr(applicability_service, 'MODEL_PATH', tmp_path / 'missing.pkl')
    report = ml_client.post('/model/input-checks', json=DRAFT).json()
    assert report['status'] == 'partial' and len(report['input_checks']) == 3
    assert report['applicability']['status'] == 'unavailable'
    assert report['applicability']['training_percentile'] is None


def test_demo_engine_never_invents_trained_checks(client):
    report = client.post('/model/input-checks', json=DRAFT).json()
    assert report['status'] == 'unavailable' and not report['input_checks']
    assert report['applicability'] is None


def test_different_feature_contract_is_withheld(ml_client, ml_service, monkeypatch):
    monkeypatch.setattr(ml_service, 'feature_names', [*ml_service.feature_names, 'tenure_months'])
    report = ml_client.post('/model/input-checks', json=DRAFT).json()
    assert report['status'] == 'unavailable' and not report['input_checks']
