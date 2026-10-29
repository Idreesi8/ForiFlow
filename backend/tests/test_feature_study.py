"""Only complete, model-matched research may reach the user."""
import copy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from services import feature_study as service


@pytest.fixture
def report():
    return json.loads(service.REPORT_PATH.read_text(encoding='utf-8'))


def test_published_study_has_measured_folds_and_reference(report):
    summary = service.summarise(report)
    assert summary.training_rows == 19449 and summary.folds == 5
    assert len(summary.candidates) == 4 and len(summary.permutation) == 3
    assert summary.status == 'research_only'
    assert summary.candidates[0].paired_auc_delta == 0


def test_means_are_recalculated_from_folds_instead_of_trusting_summary(report):
    before = service.summarise(report)
    report['candidates'][0]['auc_roc_mean'] = 0.99
    assert service.summarise(report) == before


@pytest.mark.parametrize('change', [
    lambda r: r.update(promoted=True),
    lambda r: r.update(serving_artifacts_unchanged=False),
    lambda r: r.update(version='other'),
    lambda r: r['protocol'].update(training_rows=5),
    lambda r: r['candidates'].pop(),
    lambda r: r['candidates'][0]['per_fold'].pop(),
    lambda r: r['candidates'][0]['per_fold'][0].update(auc_roc=float('nan')),
    lambda r: r['candidates'][0]['per_fold'][0].update(brier=-1),
    lambda r: r['permutation'][0]['per_fold_auc_drop'].pop(),
    lambda r: r['candidates'][0]['per_fold'][0]['sampling'].update(non_category_history_rows=1000000),
    lambda r: r['folds'][0].update(score_rows=1),
    lambda r: r['training_diagnostics'].update(rows_in_conflicting_vectors=1000000),
])
def test_incomplete_or_nonfinite_study_is_withheld(report, change):
    change(report)
    with pytest.raises((ValueError, KeyError, TypeError)):
        service.summarise(report)


def test_different_model_or_surrogate_cannot_display_the_study():
    with pytest.raises(ValueError): service.load_study(SimpleNamespace(engine='ml', artifact_sha256='different'))
    with pytest.raises(ValueError): service.load_study(SimpleNamespace(engine='surrogate'))


def test_publication_refuses_drift_and_preserves_existing_record(tmp_path, report, monkeypatch):
    source = tmp_path / 'report.json'
    source.write_text(json.dumps(report), encoding='utf-8')
    target = tmp_path / 'published.json'
    target.write_text('preserved')
    monkeypatch.setattr(service, 'REPORT_PATH', target)
    with pytest.raises(FileExistsError): service.publish(source)
    assert target.read_text() == 'preserved'
    report['protocol']['serving_artifacts']['scaler.pkl'] = '0' * 64
    source.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(ValueError): service.publish(source)
    assert target.read_text() == 'preserved'


def test_endpoint_requires_a_session(anonymous_client):
    assert anonymous_client.get('/model/feature-study').status_code == 401


def test_endpoint_is_read_only_and_matches_active_model(ml_client, ml_service, db_session_factory, monkeypatch):
    statements = []
    def forbidden(*a, **kw): pytest.fail('Research display called credit inference')
    monkeypatch.setattr(ml_service, 'score', forbidden)
    engine = db_session_factory.kw['bind']
    def record(_conn, _cursor, statement, *_args): statements.append(statement.strip())
    event.listen(engine, 'before_cursor_execute', record)
    try:
        response = ml_client.get('/model/feature-study')
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    assert response.json()['credit_artifact_sha256'] == ml_service.artifact_sha256
    assert response.headers['cache-control'] == 'no-store'
    assert statements and all(s.upper().startswith('SELECT') for s in statements)


def test_missing_and_unverifiable_report_are_explained(client, tmp_path, monkeypatch):
    path = tmp_path / 'missing.json'
    monkeypatch.setattr(service, 'REPORT_PATH', path)
    assert client.get('/model/feature-study').status_code == 404
    path.write_text('{invalid')
    response = client.get('/model/feature-study')
    assert response.status_code == 409 and 'withheld' in response.json()['detail']
