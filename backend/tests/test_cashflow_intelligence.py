"""Known series, future isolation, evidence gates and no-write endpoint checks."""
import hashlib
from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import event

from services import cashflow_intelligence as ci
from services.statement_service import MonthTotals, StatementError, parse_statement


def statement(values):
    lines = ['date,type,amount']
    for i, value in enumerate(values):
        y, m = 2023 + i//12, i%12+1
        lines.extend([f'{y}-{m:02d}-02,CR,{value}', f'{y}-{m:02d}-27,DR,50'])
    return '\n'.join(lines)


def months(values):
    return [MonthTotals(f'{2023+i//12}-{i%12+1:02d}', value, 50, 2) for i, value in enumerate(values)]


def test_theil_sen_recovers_known_trend_despite_one_extreme_outlier():
    values = [100+10*i for i in range(12)]
    values[5] += 10000
    assert ci.robust_line(values) == pytest.approx((10, 100))


@pytest.mark.parametrize('values', [[], [1], list(range(13)), [0, float('inf')]])
def test_invalid_robust_windows_are_rejected(values):
    with pytest.raises(ValueError): ci.robust_line(values)


def test_all_methods_have_known_reference_values():
    past = list(range(12))
    assert ci.predict('last_month', past) == 11
    assert ci.predict('median_6', past) == 8.5
    assert ci.predict('theil_sen_12', past) == 12
    assert ci.predict('same_month_last_year', past) == 0
    assert ci.predict('theil_sen_12', list(range(11,-1,-1))) == 0
    with pytest.raises(ValueError): ci.predict('last_month', [1,2])
    with pytest.raises(ValueError): ci.predict('invented', past)


def test_linear_series_selects_robust_trend_on_development_only():
    result = ci.forecast(months([100+10*i for i in range(36)]))
    assert result['selected_method'] == 'theil_sen_12'
    assert result['predicted_pkr'] == 460 and result['next_month'] == '2026-01'
    assert result['test_mae_pkr'] == 0 and result['baseline_test_mae_pkr'] == 10
    assert result['test_months_inside_band'] == 6 and result['empirical_radius_pkr'] == 0


def test_constant_ties_favour_simple_baseline_without_fabricating_uncertainty():
    result = ci.forecast(months([100]*30))
    assert result['selected_method'] == 'last_month'
    assert result['test_mae_pkr'] == 0
    assert result['lower_pkr'] == result['upper_pkr'] == 100


def test_seasonal_reference_can_win_without_claiming_detected_seasonality():
    cycle = [100,500,200,800,300,700,50,600,400,1000,900,150]
    result = ci.forecast(months(cycle*3))
    assert result['selected_method'] == 'same_month_last_year'
    assert result['predicted_pkr'] == 100 and result['test_mae_pkr'] == 0


def test_poisoning_later_test_outcomes_cannot_change_selection_or_band():
    values = [100+3*i for i in range(36)]
    original = ci.forecast(months(values))
    changed = ci.forecast(months(values[:-6]+[90000]*6))
    assert changed['selected_method'] == original['selected_method']
    assert changed['candidates'] == original['candidates']
    assert changed['empirical_radius_pkr'] == original['empirical_radius_pkr']
    assert changed['test_months'][0]['predicted_pkr'] == original['test_months'][0]['predicted_pkr']
    assert changed['test_mae_pkr'] > original['test_mae_pkr']


def test_each_test_forecast_sees_only_preceding_months():
    values = [100+3*i+(i%3)*5 for i in range(36)]
    original = ci.forecast(months(values))
    for offset in range(6):
        poisoned = values.copy()
        poisoned[len(values)-6+offset:] = [99999]*(6-offset)
        altered = ci.forecast(months(poisoned))
        assert altered['test_months'][offset]['predicted_pkr'] == original['test_months'][offset]['predicted_pkr']


def test_calibration_does_not_select_method_and_earlier_excluded_rows_do_not_enter():
    values = [100+10*i for i in range(36)]
    original = ci.forecast(months(values))
    changed = values.copy(); changed[-12:-6] = [10000]*6
    calibrated = ci.forecast(months(changed))
    assert calibrated['candidates'] == original['candidates']
    assert calibrated['empirical_radius_pkr'] > original['empirical_radius_pkr']
    changed = values.copy(); changed[:6] = [100000]*6
    assert ci.forecast(months(changed)) == original


def test_split_order_error_measure_and_coverage_are_auditable():
    result = ci.forecast(months([100+(i%7)*20+i for i in range(36)]))
    dev, cal, test = result['development_months'], result['calibration_months'], result['test_months']
    assert len(set(dev + cal + [row['month'] for row in test])) == 18
    assert dev[-1] < cal[0] < cal[-1] < test[0]['month']
    mae = sum(abs(row['observed_pkr']-row['predicted_pkr']) for row in test)/6
    assert result['test_mae_pkr'] == round(mae, 2)
    assert result['test_months_inside_band'] == sum(row['lower_pkr'] <= row['observed_pkr'] <= row['upper_pkr'] for row in test)


def test_small_history_still_gets_descriptive_analysis_without_forecast():
    source = statement([100,200,300])
    result = ci.analyse(parse_statement(source), today=date(2026,10,28))
    assert result.forecast.status == 'insufficient_history'
    assert result.trend_slope_pkr_per_month == 100
    assert result.source_sha256 == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.parametrize('kind', ['unreadable', 'quiet', 'future'])
def test_quality_issues_withhold_forecasts_but_retain_history(kind):
    summary = parse_statement(statement([100]*36))
    if kind == 'unreadable': summary = replace(summary, unreadable_transactions=1)
    if kind == 'quiet': summary = replace(summary, months_without_transactions=['2023-03'])
    today = date(2025,12,26) if kind == 'future' else date(2026,10,28)
    result = ci.analyse(summary, today=today)
    assert result.forecast.status == 'quality_blocked' and len(result.series) == 36


def test_missing_calendar_month_is_included_and_blocks_forecast():
    source = statement([100]*36)
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('2024-03'))
    result = ci.analyse(parse_statement(source), today=date(2026,10,28))
    assert '2024-03' in result.quiet_months
    assert result.forecast.status == 'quality_blocked'


def test_zero_denominator_change_is_unavailable_not_infinite():
    summary = parse_statement(statement([0,0,0,100,200,300]))
    result = ci.analyse(summary, today=date(2026,10,28))
    assert result.recent_three_vs_previous_three_percent is None
    # The zero CR on Jan 2 is not a transaction; Jan's first readable row is
    # Jan 27, so the canonical parser excludes that boundary month.
    assert result.observations == 5 and result.negative_net_months == 2


def test_chart_and_compute_windows_are_bounded():
    summary = parse_statement(statement([100]*48))
    result = ci.analyse(summary, today=date(2027,10,28))
    assert len(result.series) == 36 and result.omitted_chart_months == 12
    assert result.trend_window_months == 12
    summary = replace(summary, months=months([100]*121))
    with pytest.raises(StatementError): ci.analyse(summary)


@pytest.mark.parametrize('amount', [1e13, float('nan'), float('inf'), -1])
def test_unsupported_monthly_totals_are_refused(amount):
    summary = parse_statement(statement([100]*3))
    summary = replace(summary, months=[MonthTotals('2023-01', amount, 0, 1), *summary.months[1:]])
    with pytest.raises(StatementError): ci.analyse(summary)


def test_endpoint_requires_authentication(anonymous_client):
    assert anonymous_client.post('/model/cashflow-intelligence', json={'csv': statement([100]*3)}).status_code == 401


def test_endpoint_does_not_score_register_or_write_tables(client, db_session_factory, monkeypatch):
    def forbidden(*a, **kw): pytest.fail('Statement analysis invoked credit inference or registration')
    monkeypatch.setattr('services.scoring_service.ScoringService.score', forbidden)
    monkeypatch.setattr('services.model_registry.ensure_registered', forbidden)
    statements = []
    engine = db_session_factory.kw['bind']
    def record(_conn, _cursor, sql, *_args): statements.append(sql.strip())
    event.listen(engine, 'before_cursor_execute', record)
    try:
        response = client.post('/model/cashflow-intelligence', json={'csv': statement([100+10*i for i in range(36)])})
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['forecast']['status'] == 'ready'
    assert not {'risk_score','recommendation','application_id'} & response.json().keys()
    assert statements and all(sql.upper().startswith('SELECT') for sql in statements)


@pytest.mark.parametrize('payload', [{}, {'csv':''}, {'csv':'bad'}, {'csv':42}, {'csv':'x', 'application_id':1}, {'csv':'x'*2_000_001}])
def test_invalid_requests_are_actionable_errors(client, payload):
    assert client.post('/model/cashflow-intelligence', json=payload).status_code == 422
