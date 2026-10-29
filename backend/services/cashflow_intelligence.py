"""Bounded local time-series analysis. No credit inference, DB, network or files.

Method fixed in advance: rolling 12-month fits; six development months choose
one of four methods, six later months set a maximum-absolute-error band, six
final months evaluate the frozen choice/band with one-step rolling origins.
The band is empirical, with NO nominal future-coverage guarantee.
"""
from __future__ import annotations

import math
import statistics
from datetime import date

from business_time import business_date, utc_now
from cashflow_schemas import CashflowReport
from services.statement_service import StatementError, StatementSummary

METHODS = ('last_month', 'median_6', 'theil_sen_12', 'same_month_last_year')
MIN_FORECAST_MONTHS = 30
MAX_MONTHS = 120
MAX_MONTHLY_AMOUNT = 1_000_000_000_000
NOTES = [
    'Computed locally by ForiFlow. No third-party AI API, credit inference or database save is used.',
    'Receipts are account inflows, not verified revenue. Transfers, loans, cash-only sales and other accounts may change the picture.',
    'The parser keeps boundary months using first/last transaction days (5/25 heuristic). This does not verify a complete bank-statement reporting period.',
    'The chart shows up to 36 retained months; trend uses the latest 12. Forecast comparisons use the latest 30 months only.',
    'One-step backtests refit on earlier observations only. Earlier test observations become available to later origins; the method choice and error-band radius stay fixed.',
    'The range uses the largest absolute error in six separate calibration months. It is not a confidence interval or a guaranteed probability range. A zero-width band only means zero errors in that short past window.',
    'Six evaluation months are a small sample. Structural breaks, seasonal changes and incomplete exports can make future performance much worse.',
    'The estimate is for the month after the last retained source month, which may differ from the current calendar month. This is not an affordability finding or a lending decision.',
]


def analyse_csv(source: str, date_order: str = 'auto', *, today: date | None = None) -> CashflowReport:
    from services.cashflow_import import prepare_source
    summary, quality = prepare_source(source, date_order)
    return analyse(summary, today=today).model_copy(update={'source_quality': quality})


def robust_line(values):
    """Theil–Sen paired-median slope, joint median-residual intercept; <=12 rows."""
    if not 2 <= len(values) <= 12 or not all(math.isfinite(v) for v in values):
        raise ValueError('A robust line requires 2–12 finite observations.')
    slopes = [(values[j] - values[i]) / (j-i) for i in range(len(values)) for j in range(i+1, len(values))]
    slope = statistics.median(slopes)
    intercept = statistics.median(value - slope*i for i, value in enumerate(values))
    return slope, intercept


def predict(method, past):
    if len(past) < 12:
        raise ValueError('Every forecasting origin requires 12 earlier months.')
    if method == 'last_month':
        value = past[-1]
    elif method == 'median_6':
        value = statistics.median(past[-6:])
    elif method == 'theil_sen_12':
        slope, intercept = robust_line(past[-12:])
        value = intercept + 12*slope
    elif method == 'same_month_last_year':
        value = past[-12]
    else:
        raise ValueError('Unknown forecasting method.')
    return round(max(0., value), 2)


def _next_month(month):
    year, number = map(int, month.split('-'))
    return f'{year + (number == 12):04d}-{number % 12 + 1:02d}'


def forecast(months):
    """Only the latest 30 months enter method selection/calibration/testing."""
    if len(months) < MIN_FORECAST_MONTHS:
        raise ValueError('At least 30 retained months are required.')
    window = months[-MIN_FORECAST_MONTHS:]
    values = [month.inflow for month in window]
    candidates = []
    for method in METHODS:
        errors = [abs(values[i] - predict(method, values[:i])) for i in range(12, 18)]
        candidates.append({'method': method, 'development_mae_pkr': round(statistics.fmean(errors), 2)})
    # The displayed paisa-rounded MAEs define ties; fixed order favours the
    # simple last-month baseline. No calibration/test outcome selects a method.
    selected = min(candidates, key=lambda row: row['development_mae_pkr'])['method']
    radius = max(round(abs(values[i] - predict(selected, values[:i])), 2) for i in range(18, 24))

    def band(point):
        return {'lower_pkr': round(max(0., point-radius), 2), 'upper_pkr': round(point+radius, 2)}

    test = []
    for i in range(24, 30):
        point = predict(selected, values[:i])
        test.append({'month': window[i].month, 'observed_pkr': values[i], 'predicted_pkr': point,
                     'baseline_pkr': predict('last_month', values[:i]), **band(point)})
    next_point = predict(selected, values)
    return {'status': 'ready', 'selected_method': selected, 'candidates': candidates,
            'development_months': [m.month for m in window[12:18]],
            'calibration_months': [m.month for m in window[18:24]],
            'test_months': test, 'empirical_radius_pkr': radius,
            'test_mae_pkr': round(statistics.fmean(abs(row['observed_pkr']-row['predicted_pkr']) for row in test), 2),
            'baseline_test_mae_pkr': round(statistics.fmean(abs(row['observed_pkr']-row['baseline_pkr']) for row in test), 2),
            'test_months_inside_band': sum(row['lower_pkr']-1e-6 <= row['observed_pkr'] <= row['upper_pkr']+1e-6 for row in test),
            'next_month': _next_month(window[-1].month), 'predicted_pkr': next_point, **band(next_point)}


def analyse(summary: StatementSummary, *, today: date | None = None) -> CashflowReport:
    months = summary.months
    if not 3 <= len(months) <= MAX_MONTHS:
        raise StatementError('Cash-flow Intelligence supports 3–120 retained months. Export a period within ten years.')
    if any(not math.isfinite(v) or v < 0 or v > MAX_MONTHLY_AMOUNT for m in months for v in (m.inflow, m.outflow)):
        raise StatementError('Monthly amounts must be finite, nonnegative and at most PKR 1 trillion. Check the export.')
    # Independently validate chronological continuity for direct callers too.
    if any(_next_month(a.month) != b.month for a, b in zip(months, months[1:])):
        raise StatementError('Retained months must be consecutive and ordered.')
    today = today or business_date()
    recent = [m.inflow for m in months[-12:]]
    slope, _ = robust_line(recent)
    previous = statistics.median([m.inflow for m in months[-6:-3]]) if len(months) >= 6 else 0
    change = round(100*(statistics.median(recent[-3:])/previous-1), 2) if previous > 0 else None
    warnings = list(summary.warnings)
    if months[-1].month < today.strftime('%Y-%m'):
        warnings.append(f'The source ends in {months[-1].month}. The estimate, if available, is anchored to that source; check its date before using it.')
    quality = []
    if summary.unreadable_transactions:
        quality.append('Some source rows could not be read.')
    if summary.months_without_transactions:
        quality.append('Some retained months have no readable transactions; an incomplete export cannot be distinguished from a quiet month.')
    if date.fromisoformat(summary.period_end) > today:
        quality.append('The source includes a future-dated transaction.')
    if quality:
        result = {'status': 'quality_blocked', 'reason': ' '.join(quality) + ' Forecast withheld; historical figures remain descriptive.'}
    elif len(months) < MIN_FORECAST_MONTHS:
        result = {'status': 'insufficient_history', 'reason': f'{len(months)} retained months available. A forecast needs 30: 12 initial, 6 development, 6 calibration and 6 evaluation months.'}
    else:
        result = forecast(months)
    return CashflowReport(computed_at=utc_now(), as_of_date=today.isoformat(), source_sha256=summary.source_sha256,
        parser_version=summary.parser_version, observations=len(months), first_month=months[0].month,
        last_month=months[-1].month, series=[{'month': m.month, 'inflow': m.inflow, 'outflow': m.outflow, 'transactions': m.transactions} for m in months[-36:]],
        omitted_chart_months=max(0, len(months)-36), trend_window_months=len(recent),
        trend_slope_pkr_per_month=round(slope, 2), recent_three_vs_previous_three_percent=change,
        negative_net_months=sum(m.outflow > m.inflow for m in months), unreadable_rows=summary.unreadable_transactions,
        quiet_months=summary.months_without_transactions, warnings=warnings, forecast=result, notes=NOTES)
