"""Real-ensemble diagnostics, no-write guarantees and fail-closed provenance."""
import copy
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import event, select

from ml.train_applicability import fit_reference
from models.database import Application, Base, ModelVersion, User
from schemas import SMEApplicant
from services import applicability_service
from services.policy_rules import ScoreBands
from services.scoring_service import get_scoring_service
from tests.conftest import STRONG_APPLICANT


def create_case(client, **changes):
    result = client.post('/score', json={**STRONG_APPLICANT, **changes})
    assert result.status_code == 201, result.text
    return result.json()['application_id']


def diagnostics(client, identifier):
    response = client.get(f'/model/applications/{identifier}/diagnostics')
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(factory):
    with factory() as db:
        return {name: list(db.execute(select(table)).all()) for name, table in Base.metadata.tables.items()}


def test_authentication(anonymous_client):
    for path in ['/model/applicability', '/model/applications/1/diagnostics']:
        assert anonymous_client.get(path).status_code == 401


def test_missing_case(client):
    assert client.get('/model/applications/9999/diagnostics').status_code == 404


@pytest.mark.parametrize('role', ['analyst', 'manager', 'admin'])
def test_each_officer_role_can_read_without_deciding(ml_client, db_session_factory, role):
    key = create_case(ml_client)
    with db_session_factory() as db:
        db.get(User, 1).role = role
        db.commit()
    assert diagnostics(ml_client, key)['status'] == 'ready'


def test_surrogate_is_not_presented_as_trained_ml(client):
    key = create_case(client)
    report = diagnostics(client, key)
    assert report['status'] == 'unavailable' and not report['source_verified']
    assert not report['members'] and not report['scenarios']
    assert client.get('/model/applicability').json()['status'] == 'unavailable'


def test_real_reference_is_bound_to_credit_model_and_never_exposes_reference_rows(ml_client, ml_service):
    report = ml_client.get('/model/applicability').json()
    assert report['status'] == 'ready'
    assert report['algorithm'] == 'IsolationForest' and report['n_estimators'] == 128
    assert report['credit_artifact_sha256'] == ml_service.artifact_sha256
    assert report['train_rows'] == 19449 and report['validation_rows'] == 6483
    assert report['validation_flagged'] == 314 and report['training_flagged'] == 973
    assert report['final_test_used'] is False
    assert 'training_scores_sorted' not in report
    assert len(report['reference_sha256']) == 64


def test_diagnostics_use_only_reads_and_preserve_every_table(ml_client, db_session_factory):
    key = create_case(ml_client)
    before = snapshot(db_session_factory)
    with db_session_factory() as db:
        engine = db.bind
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        report = diagnostics(ml_client, key)
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert report['status'] == 'ready' and report['source_verified'] is True
    assert report['stored_score'] == report['recomputed_score']
    assert len(report['scenarios']) == 25
    assert statements and all(statement.lstrip().upper().startswith('SELECT') for statement in statements)
    assert snapshot(db_session_factory) == before


def test_scenarios_and_member_weights_reproduce_the_actual_credit_engine(ml_client, ml_service):
    key = create_case(ml_client)
    report = diagnostics(ml_client, key)
    members = report['members']
    assert sum(member['weight'] for member in members) == pytest.approx(1)
    weighted = sum(member['weight'] * member['raw_default_probability'] for member in members)
    assert weighted == pytest.approx(report['ensemble_raw_default_probability'])
    assert round(100 * (1 - weighted), 2) == report['stored_score']
    probabilities = [member['raw_default_probability'] for member in members]
    assert report['member_spread_pp'] == pytest.approx(100 * (max(probabilities) - min(probabilities)), abs=0.0001)
    for row in report['scenarios']:
        applicant = SMEApplicant(**{**STRONG_APPLICANT, 'loan_amount_pkr': row['loan_amount_pkr'],
            'monthly_digital_payments': row['monthly_digital_payments'], 'cash_flow_proxy': row['cash_flow_proxy']})
        actual = ml_service.score(applicant)
        assert row['score'] == actual.risk_score
        assert row['score_change'] == pytest.approx(actual.risk_score - report['stored_score'], abs=0.0001)
        assert row['loan_amount_pkr'] == STRONG_APPLICANT['loan_amount_pkr'] * row['loan_factor']
        assert row['monthly_digital_payments'] == STRONG_APPLICANT['monthly_digital_payments'] * row['receipts_factor']
        assert row['cash_flow_proxy'] == STRONG_APPLICANT['cash_flow_proxy'] * row['receipts_factor']
    baseline, = [row for row in report['scenarios'] if row['loan_factor'] == row['receipts_factor'] == 1]
    assert baseline['score'] == report['stored_score'] and baseline['score_change'] == 0


def test_clip_loss_and_binary_history_encoding_are_not_confused(ml_client):
    key = create_case(ml_client, loan_amount_pkr=1000, years_in_operation=40, payment_history_score=92)
    report = diagnostics(ml_client, key)
    inputs = {item['name']: item for item in report['input_checks']}
    assert inputs['loan_to_income']['clipped'] is True
    assert inputs['loan_to_income']['transformation'] == 'clipped_low'
    assert inputs['years_in_operation']['model_value'] == 18 and inputs['years_in_operation']['clipped'] is True
    assert inputs['payment_history_score']['entered'] == 92
    assert inputs['payment_history_score']['model_value'] == 80
    assert inputs['payment_history_score']['transformation'] == 'clean_history'
    assert inputs['payment_history_score']['clipped'] is False


@pytest.mark.parametrize('value,expected', [(52.5, 'adverse_history'), (52.5001, 'clean_history')])
def test_history_boundary_uses_the_serving_transform(ml_client, value, expected):
    key = create_case(ml_client, payment_history_score=value)
    item = next(item for item in diagnostics(ml_client, key)['input_checks'] if item['name'] == 'payment_history_score')
    assert item['transformation'] == expected


def test_obviously_unusual_inputs_are_not_labelled_a_default_probability(ml_client):
    key = create_case(ml_client, monthly_digital_payments=0, cash_flow_proxy=0)
    report = diagnostics(ml_client, key)
    assert report['applicability']['atypical'] is True
    assert 'Not a default probability' in report['applicability']['interpretation']
    assert all(row['monthly_digital_payments'] == row['cash_flow_proxy'] == 0 for row in report['scenarios'])


@pytest.mark.parametrize('change', ['missing_id', 'wrong_fingerprint', 'different_version', 'changed_score'])
def test_unverified_historical_cases_do_not_receive_current_model_diagnostics(ml_client, db_session_factory, change):
    key = create_case(ml_client)
    with db_session_factory() as db:
        row = db.get(Application, key)
        if change == 'missing_id': row.model_version_id = None
        elif change == 'wrong_fingerprint': db.get(ModelVersion, row.model_version_id).artifact_sha256 = '0' * 64
        elif change == 'different_version': row.model_version = 'other-model'
        else: row.risk_score -= 1
        db.commit()
    report = diagnostics(ml_client, key)
    assert report['status'] == 'unavailable' and report['source_verified'] is False
    assert report['scenarios'] == report['members'] == []


@pytest.mark.parametrize('field', ['monthly_digital_payments', 'cash_flow_proxy', 'payment_history_score', 'years_in_operation'])
def test_nonfinite_stored_inputs_fail_closed(ml_client, db_session_factory, field):
    key = create_case(ml_client)
    with db_session_factory() as db:
        setattr(db.get(Application, key), field, float('inf'))
        db.commit()
    report = diagnostics(ml_client, key)
    assert report['status'] == 'unavailable' and report['scenarios'] == []


def test_missing_recorded_policy_never_substitutes_the_active_policy(ml_client, db_session_factory):
    key = create_case(ml_client)
    with db_session_factory() as db:
        db.get(Application, key).policy_evaluation = {}
        db.commit()
    report = diagnostics(ml_client, key)
    assert report['status'] == 'ready'
    assert report['baseline_recommendation'] is None
    assert all(row['recommendation'] is None for row in report['scenarios'])
    assert 'today’s policy is not substituted' in report['policy_note']


def test_retained_policy_controls_hypothetical_recommendations(ml_client, db_session_factory):
    key = create_case(ml_client)
    with db_session_factory() as db:
        row = db.get(Application, key)
        snapshot_value = copy.deepcopy(row.policy_evaluation)
        snapshot_value['bands']['decline_max_score'] = 10
        snapshot_value['bands']['manual_review_max_score'] = 20
        row.policy_evaluation = snapshot_value
        db.commit()
    report = diagnostics(ml_client, key)
    for row in report['scenarios']:
        expected = 'Decline' if row['score'] <= 10 else 'Manual Review' if row['score'] <= 20 else 'Approve'
        assert row['recommendation'] == expected


def test_missing_sidecar_keeps_verified_ensemble_checks_available(ml_client, monkeypatch, tmp_path):
    key = create_case(ml_client)
    monkeypatch.setattr(applicability_service, 'MODEL_PATH', tmp_path / 'missing.pkl')
    report = diagnostics(ml_client, key)
    assert report['status'] == 'partial' and report['source_verified'] is True
    assert report['applicability']['status'] == 'unavailable'
    assert len(report['members']) == 2 and len(report['scenarios']) == 25


@pytest.mark.parametrize('change', ['fingerprint', 'training_ids', 'runtime', 'test_used', 'malformed', 'unsorted', 'corrupt_model'])
def test_bad_sidecar_does_not_invent_anomaly_results(ml_client, monkeypatch, tmp_path, change):
    key = create_case(ml_client)
    data = json.loads(applicability_service.MANIFEST_PATH.read_text())
    model_bytes = applicability_service.MODEL_PATH.read_bytes()
    if change == 'fingerprint': data['credit_artifact_sha256'] = 'x'
    elif change == 'training_ids': data['train_ids_sha256'] = 'x'
    elif change == 'runtime': data['sklearn_version'] = '0.0.0'
    elif change == 'test_used': data['final_test_used'] = True
    elif change == 'malformed': data = []
    elif change == 'unsorted': data['training_scores_sorted'].reverse()
    else: model_bytes += b'corruption'
    manifest_path, model_path = tmp_path / 'reference.json', tmp_path / 'model.pkl'
    manifest_path.write_text(json.dumps(data))
    model_path.write_bytes(model_bytes)
    monkeypatch.setattr(applicability_service, 'MANIFEST_PATH', manifest_path)
    monkeypatch.setattr(applicability_service, 'MODEL_PATH', model_path)
    report = diagnostics(ml_client, key)
    assert report['status'] == 'partial' and report['applicability']['status'] == 'unavailable'
    assert report['applicability']['training_percentile'] is None


def test_validation_values_cannot_change_fitted_reference_or_threshold():
    rng = np.random.default_rng(42)
    train = pd.DataFrame(rng.normal(size=(512, 3)), columns=['a', 'b', 'c'])
    normal = pd.DataFrame(rng.normal(size=(100, 3)), columns=train.columns)
    unusual = normal + 100
    medians = train.median().to_dict()
    first, first_stats = fit_reference(train, normal, list(train.columns), medians)
    second, second_stats = fit_reference(train, unusual, list(train.columns), medians)
    assert first_stats['threshold'] == second_stats['threshold']
    assert first_stats['training_scores_sorted'] == second_stats['training_scores_sorted']
    np.testing.assert_array_equal(first.score_samples(train.to_numpy()), second.score_samples(train.to_numpy()))
    assert first_stats['validation_flagged'] < second_stats['validation_flagged']
