"""Operating figures are useful without inventing learned credit effects."""
import json
import math

import pytest
from sqlalchemy import event

from operating_schemas import OperatingFigures
from services.operating_checks import check_operating_figures
from services.statement_service import parse_statement
from tests.conftest import STRONG_APPLICANT
from tests.test_model_diagnostics import snapshot

FIGURES = {name: STRONG_APPLICANT[name] for name in OperatingFigures.model_fields}
CSV = 'date,type,amount\n' + '\n'.join(
    f'2026-{month}-02,CR,100000\n2026-{month}-27,DR,60000' for month in ['01', '02', '03'])


def metric_map(report):
    return {row['name']: row['value'] for row in report['metrics']}


def test_arithmetic_uses_recorded_values_with_correct_units(client):
    response = client.post('/model/operating-checks', json=FIGURES)
    assert response.status_code == 200
    body = response.json()
    assert body['inputs'] == FIGURES
    values = metric_map(body)
    assert values['principal_per_month'] == pytest.approx(2400000 / 36)
    assert values['cash_after_principal'] == pytest.approx(850000 - 2400000 / 36)
    assert values['principal_cashflow_ratio'] == pytest.approx((2400000 / 36) / 850000)
    assert values['debt_annual_cashflow_ratio'] == pytest.approx(400000 / (12 * 850000))
    assert values['stock_cycle_days'] == pytest.approx(365 / 9.5)
    assert values['digital_receipts_per_person'] == pytest.approx(3200000 / 45)
    assert values['order_consistency_gap'] is None
    assert response.headers['cache-control'] == 'no-store'
    assert not {'risk_score', 'recommendation', 'probability_of_default', 'borrower_id'} & body.keys()


@pytest.mark.parametrize('field,value,metric', [
    ('tenure_months', 24, 'principal_per_month'),
    ('existing_debt_pkr', 0, 'debt_annual_cashflow_ratio'),
    ('inventory_turnover', 5, 'stock_cycle_days'),
    ('num_employees', 2, 'digital_receipts_per_person'),
])
def test_each_previously_unused_figure_changes_its_own_calculation(client, field, value, metric):
    original = metric_map(client.post('/model/operating-checks', json=FIGURES).json())
    changed = metric_map(client.post('/model/operating-checks', json={**FIGURES, field: value}).json())
    assert original[metric] != changed[metric]


def test_zero_denominators_remain_unknown_instead_of_infinite_or_good(client):
    response = client.post('/model/operating-checks', json={**FIGURES, 'cash_flow_proxy': 0, 'inventory_turnover': 0, 'num_employees': 0})
    assert response.status_code == 200
    metrics = metric_map(response.json())
    for name in ['principal_cashflow_ratio', 'debt_annual_cashflow_ratio', 'stock_cycle_days', 'digital_receipts_per_person']:
        assert metrics[name] is None
    assert metrics['cash_after_principal'] < 0
    assert all(value is None or math.isfinite(value) for value in metrics.values())


def test_extreme_small_denominators_do_not_serialize_infinity(client):
    response = client.post('/model/operating-checks', json={**FIGURES, 'cash_flow_proxy': 1e-320, 'inventory_turnover': 1e-320})
    assert response.status_code == 200
    metrics = metric_map(response.json())
    assert metrics['stock_cycle_days'] is None
    assert metrics['principal_cashflow_ratio'] is None
    assert metrics['debt_annual_cashflow_ratio'] is None


def test_order_consistency_is_compared_only_to_reparsed_statement_receipts(client):
    summary = parse_statement(CSV)
    first = client.post('/model/operating-checks', json={**FIGURES, 'statement_csv': CSV, 'order_consistency': 100}).json()
    assert first['order_source'] == 'statement_receipts_proxy'
    assert first['receipt_consistency_reference'] == summary.suggested_order_consistency == 100
    assert metric_map(first)['order_consistency_gap'] == 0
    assert first['statement_sha256'] == summary.source_sha256
    changed = client.post('/model/operating-checks', json={**FIGURES, 'statement_csv': CSV, 'order_consistency': 50}).json()
    assert metric_map(changed)['order_consistency_gap'] == -50
    assert 'statement_csv' not in json.dumps(changed)
    assert any('not order volumes' in note for note in changed['notes'])


def test_invalid_statement_is_rejected_without_inventing_evidence(client):
    response = client.post('/model/operating-checks', json={**FIGURES, 'statement_csv': 'not,a,statement'})
    assert response.status_code == 422


@pytest.mark.parametrize('summary', [
    {}, ['unrecognized legacy evidence'], {'suggested_order_consistency': float('nan')},
    {'suggested_order_consistency': 90, 'source_sha256': 'a'*64, 'full_months': 2},
    {'suggested_order_consistency': 90, 'source_sha256': 'not-verified', 'full_months': 3},
])
def test_unverifiable_legacy_summary_withholds_the_receipts_comparison(summary):
    result = check_operating_figures(OperatingFigures(**FIGURES), summary)
    assert result.order_source == 'officer_entered'
    assert result.receipt_consistency_reference is None


@pytest.mark.parametrize('field,value', [
    ('tenure_months', 2), ('tenure_months', 85), ('tenure_months', 24.5), ('tenure_months', True),
    ('loan_amount_pkr', 0), ('loan_amount_pkr', 500000001),
    ('existing_debt_pkr', -1), ('existing_debt_pkr', 1000000001),
    ('inventory_turnover', -1), ('inventory_turnover', 50.1),
    ('order_consistency', -1), ('order_consistency', 101),
    ('num_employees', 2.5), ('num_employees', 5001),
    ('cash_flow_proxy', 'Infinity'), ('monthly_digital_payments', None),
])
def test_boundaries_and_types_are_validated(client, field, value):
    assert client.post('/model/operating-checks', json={**FIGURES, field: value}).status_code == 422


@pytest.mark.parametrize('name', list(FIGURES))
def test_missing_values_are_not_imputed(client, name):
    assert client.post('/model/operating-checks', json={key: value for key, value in FIGURES.items() if key != name}).status_code == 422


@pytest.mark.parametrize('name', ['applicant_name', 'borrower_identifier', 'receipt_consistency_reference', 'risk_score'])
def test_identity_and_forged_reference_values_are_rejected(client, name):
    assert client.post('/model/operating-checks', json={**FIGURES, name: 'not allowed'}).status_code == 422


def test_authentication(anonymous_client):
    assert anonymous_client.post('/model/operating-checks', json=FIGURES).status_code == 401
    assert anonymous_client.get('/model/sme-field-research').status_code == 401


def test_missing_case(client):
    assert client.get('/model/applications/999999/operating-checks').status_code == 404


@pytest.mark.parametrize('role', ['analyst', 'manager', 'admin'])
def test_all_roles_can_read_arithmetic_without_inference_or_database_writes(client, db_session_factory, monkeypatch, role):
    from models.database import User
    with db_session_factory() as db:
        db.get(User, 1).role = role
        db.commit()
    before = snapshot(db_session_factory)
    statements = []
    def capture(_conn, _cursor, statement, *_args): statements.append(statement.strip())
    def forbidden(*args, **kwargs): pytest.fail('Credit inference or registration was called')
    monkeypatch.setattr('services.scoring_service.ScoringService.score', forbidden)
    monkeypatch.setattr('services.model_registry.ensure_registered', forbidden)
    engine = db_session_factory.kw['bind']
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        assert client.post('/model/operating-checks', json=FIGURES).status_code == 200
        assert client.get('/model/sme-field-research').status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert snapshot(db_session_factory) == before
    assert statements and all(statement.upper().startswith('SELECT') for statement in statements)


def test_saved_case_checks_use_persisted_fields_and_leave_the_record_unchanged(client, db_session_factory):
    result = client.post('/score', json={**STRONG_APPLICANT, 'statement_csv': CSV}).json()
    before = snapshot(db_session_factory)
    response = client.get(f"/model/applications/{result['application_id']}/operating-checks")
    assert response.status_code == 200
    body = response.json()
    assert body['application_id'] == result['application_id']
    assert body['inputs'] == FIGURES
    assert body['order_source'] == 'statement_receipts_proxy'
    assert snapshot(db_session_factory) == before


def test_research_gate_names_semantic_gaps_and_never_claims_training_ready(client):
    body = client.get('/model/sme-field-research').json()
    assert body['training_ready'] is False and body['serving_model_changed'] is False
    assert {row['field'] for row in body['field_coverage']} == {'tenure_months', 'existing_debt_pkr', 'inventory_turnover', 'order_consistency', 'num_employees'}
    sources = {row['id']: row for row in body['sources']}
    assert sources['bangladesh']['rows_downloaded'] == 1200
    assert sources['bangladesh']['target_alias_identical'] is True
    assert sources['pakistan_metadata']['microdata_downloaded'] is False
    assert sources['sba_dictionary']['loan_microdata_downloaded'] is False
