"""Statement scenarios keep observations, provenance and decision boundaries honest."""
from __future__ import annotations

import hashlib
import json

import pytest

from services.statement_resilience import assess_statement_resilience
from services.statement_service import parse_statement
from tests.conftest import STRONG_APPLICANT


def _statement() -> str:
    return 'date,type,amount\n' + '\n'.join(
        f'2026-{month:02d}-02,CR,100000\n2026-{month:02d}-27,DR,60000'
        for month in range(1, 7)
    )


def test_scenarios_use_actual_principal_and_fixed_observed_outflows() -> None:
    result = assess_statement_resilience(parse_statement(_statement()), 900_000, 36)
    assert result['monthly_principal_pkr'] == 25_000
    assert [x['median_remainder_pkr'] for x in result['scenarios']] == [15_000, 5_000, -5_000, -15_000]
    assert [x['months_covering_principal'] for x in result['scenarios']] == [6, 6, 0, 0]
    assert all(x['months_observed'] == 6 for x in result['scenarios'])
    assert result['method_version'] == 'principal-stress-v1'
    assert 'Interest and fees are excluded' in result['assumptions'][0]
    assert not {'decision', 'recommendation', 'probability_of_default'} & result.keys()


def test_quiet_months_and_negative_net_cash_are_kept() -> None:
    statement = ('date,type,amount\n2026-01-02,CR,100000\n2026-01-27,DR,60000\n'
                 '2026-03-02,CR,50000\n2026-03-27,DR,60000')
    summary = parse_statement(statement)
    result = assess_statement_resilience(summary, 90_000, 3)
    baseline = result['scenarios'][0]
    assert baseline['months_observed'] == 3
    assert baseline['months_covering_principal'] == 1
    assert baseline['median_remainder_pkr'] == -30_000
    assert baseline['lowest_remainder_pkr'] == -40_000
    assert summary.months_without_transactions == ['2026-02']


def test_month_coverage_compares_unrounded_principal() -> None:
    statement = 'date,type,amount\n' + '\n'.join(
        f'2026-{month:02d}-02,CR,0.34\n2026-{month:02d}-27,DR,0.01'
        for month in range(1, 4)
    )
    result = assess_statement_resilience(parse_statement(statement), 1, 3)
    assert result['monthly_principal_pkr'] == 0.33
    assert result['scenarios'][0]['months_covering_principal'] == 0
    assert result['scenarios'][0]['median_remainder_pkr'] == 0


@pytest.mark.parametrize('amount,tenure', [(0, 36), (-1, 36), (float('inf'), 36), (float('nan'), 36), (100, 0), (100, 1.5), (100, True)])
def test_invalid_facility_terms_are_refused(amount, tenure) -> None:
    with pytest.raises(ValueError):
        assess_statement_resilience(parse_statement(_statement()), amount, tenure)


def test_provenance_identifies_the_exact_csv_and_reports_unreadable_rows() -> None:
    statement = _statement() + '\n2026-02-12,CR,not-money'
    summary = parse_statement(statement)
    assert summary.source_sha256 == hashlib.sha256(statement.encode()).hexdigest()
    assert summary.unreadable_transactions == 1
    assert summary.parser_version == 'statement-v2'
    json.dumps(summary.as_dict(), allow_nan=False)


def test_new_assessment_returns_and_persists_the_same_server_computed_scenarios(client) -> None:
    statement = _statement()
    payload = {**STRONG_APPLICANT, 'statement_csv': statement,
               'loan_amount_pkr': 900_000, 'tenure_months': 36}
    response = client.post('/score', json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    stored = client.get(f"/score/applications/{body['application_id']}").json()
    evidence = body['turnover_evidence']
    assert stored['turnover_evidence'] == evidence
    assert evidence['resilience']['scenarios'][2]['median_remainder_pkr'] == -5_000
    assert evidence['source_sha256'] == hashlib.sha256(statement.encode()).hexdigest()
    assert body['decision_status'] == 'Pending'
    # Evidence calculations cannot change the scorer or policy recommendation.
    without = client.post('/score', json={k: v for k, v in payload.items() if k != 'statement_csv'}).json()
    assert body['risk_score'] == without['risk_score']
    assert body['recommendation'] == without['recommendation']
    assert without['turnover_evidence'] is None


def test_small_turnover_edits_cannot_be_claimed_as_exact_statement_evidence(client) -> None:
    statement = _statement()
    response = client.post('/score', json={
        **STRONG_APPLICANT, 'statement_csv': statement,
        'monthly_digital_payments': 100_001, 'cash_flow_proxy': 40_000,
    })
    assert response.status_code == 201
    evidence = response.json()['turnover_evidence']
    assert evidence['matches_statement'] is False
    assert evidence['monthly_inflow_median'] == 100_000
