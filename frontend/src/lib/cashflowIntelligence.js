export const CASHFLOW_METHODS = ['last_month', 'median_6', 'theil_sen_12', 'same_month_last_year'];
export const METHOD_LABELS = { last_month: 'Last-month baseline', median_6: 'Six-month median', theil_sen_12: 'Robust 12-month trend', same_month_last_year: 'Same month last year' };
const finite = (v, min = -Infinity) => typeof v === 'number' && Number.isFinite(v) && v >= min;
const month = v => typeof v === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(v);
const count = v => Number.isInteger(v) && v >= 0;
const textList = v => Array.isArray(v) && v.every(s => typeof s === 'string');
const next = value => { const [y, m] = value.split('-').map(Number); return `${y + (m === 12 ? 1 : 0)}-${String(m % 12 + 1).padStart(2, '0')}`; };
const consecutive = list => list.every((v, i) => month(v) && (!i || v === next(list[i-1])));
const band = row => finite(row.predicted_pkr, 0) && finite(row.lower_pkr, 0) && finite(row.upper_pkr, 0) && row.lower_pkr <= row.predicted_pkr && row.predicted_pkr <= row.upper_pkr;

export async function statementFingerprint(csv) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(csv));
  return Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('');
}

export function matchesCashflowReport(data, sourceHash, dateOrder = 'auto') {
  if (data?.method_version !== 'cashflow-local-v2' || data.source_sha256 !== sourceHash || !/^[a-f0-9]{64}$/.test(sourceHash)
    || data.parser_version !== 'statement-v2' || !count(data.observations) || data.observations < 3 || data.observations > 120
    || !month(data.first_month) || !month(data.last_month) || !count(data.omitted_chart_months)
    || !finite(data.trend_slope_pkr_per_month) || !count(data.trend_window_months) || data.trend_window_months < 3 || data.trend_window_months > 12
    || (data.recent_three_vs_previous_three_percent !== null && !finite(data.recent_three_vs_previous_three_percent))
    || !count(data.negative_net_months) || data.negative_net_months > data.observations || !count(data.unreadable_rows)
    || !textList(data.quiet_months) || !textList(data.warnings) || !textList(data.notes)
    || typeof data.computed_at !== 'string' || !Number.isFinite(Date.parse(data.computed_at))) return false;
  if (!Array.isArray(data.series) || data.series.length !== Math.min(data.observations, 36) || data.series.some(row => !row || !month(row.month) || !finite(row.inflow, 0) || !finite(row.outflow, 0) || !count(row.transactions))
    || !consecutive(data.series.map(row => row.month)) || data.series.at(-1).month !== data.last_month
    || data.series.length + data.omitted_chart_months !== data.observations) return false;
  const quality = data.source_quality;
  if (quality?.method_version !== 'cashflow-import-v1' || quality.date_order_requested !== dateOrder
    || !['day_first', 'month_first', 'iso_or_named', 'identical_day_month'].includes(quality.date_order_resolved)
    || (dateOrder !== 'auto' && quality.date_order_resolved !== dateOrder)
    || !/^[a-f0-9]{64}$/.test(quality.parsed_source_sha256 || '') || !count(quality.source_rows) || !quality.source_rows
    || !['ambiguous_numeric_rows', 'normalised_date_rows', 'repeated_row_candidates'].every(key => count(quality[key]) && quality[key] <= quality.source_rows)
    || quality.repeated_row_candidates >= quality.source_rows || !textList(quality.notes) || !quality.notes.length
    || !Array.isArray(quality.repeated_row_examples) || quality.repeated_row_examples.length !== Math.min(10, quality.repeated_row_candidates)
    || quality.repeated_row_examples.some(row => !row || !Number.isInteger(row.first_line) || row.first_line < 2 || !Number.isInteger(row.repeated_line) || row.repeated_line <= row.first_line)
    || new Set(quality.repeated_row_examples.map(row => row.repeated_line)).size !== quality.repeated_row_examples.length) return false;
  const forecast = data.forecast;
  if (['insufficient_history', 'quality_blocked'].includes(forecast?.status)) return typeof forecast.reason === 'string' && forecast.required_months === 30;
  if (forecast?.status !== 'ready' || data.observations < 30 || data.unreadable_rows || data.quiet_months.length
    || !CASHFLOW_METHODS.includes(forecast.selected_method) || !band(forecast) || forecast.next_month !== next(data.last_month)
    || !finite(forecast.empirical_radius_pkr, 0) || !finite(forecast.test_mae_pkr, 0) || !finite(forecast.baseline_test_mae_pkr, 0)
    || !count(forecast.test_months_inside_band) || forecast.test_months_inside_band > 6) return false;
  if (!Array.isArray(forecast.candidates) || forecast.candidates.length !== 4 || forecast.candidates.some((row, i) => !row || row.method !== CASHFLOW_METHODS[i] || !finite(row.development_mae_pkr, 0))) return false;
  if (!Array.isArray(forecast.development_months) || forecast.development_months.length !== 6 || !Array.isArray(forecast.calibration_months) || forecast.calibration_months.length !== 6
    || !Array.isArray(forecast.test_months) || forecast.test_months.length !== 6 || forecast.test_months.some(row => !row || !month(row.month) || !band(row) || !finite(row.observed_pkr, 0) || !finite(row.baseline_pkr, 0))) return false;
  const allMonths = [...forecast.development_months, ...forecast.calibration_months, ...forecast.test_months.map(row => row.month)];
  const chosen = forecast.candidates.reduce((best, row) => row.development_mae_pkr < best.development_mae_pkr ? row : best);
  const mae = forecast.test_months.reduce((sum, row) => sum + Math.abs(row.observed_pkr-row.predicted_pkr), 0)/6;
  const baselineMae = forecast.test_months.reduce((sum, row) => sum + Math.abs(row.observed_pkr-row.baseline_pkr), 0)/6;
  const inside = forecast.test_months.filter(row => row.observed_pkr >= row.lower_pkr-1e-6 && row.observed_pkr <= row.upper_pkr+1e-6).length;
  return consecutive(allMonths) && allMonths.at(-1) === data.last_month && chosen.method === forecast.selected_method
    && Math.abs(mae-forecast.test_mae_pkr) <= .011 && Math.abs(baselineMae-forecast.baseline_test_mae_pkr) <= .011
    && inside === forecast.test_months_inside_band
    && [forecast, ...forecast.test_months].every(row => Math.abs(row.lower_pkr-Math.max(0,row.predicted_pkr-forecast.empirical_radius_pkr))<=.011 && Math.abs(row.upper_pkr-row.predicted_pkr-forecast.empirical_radius_pkr)<=.011)
    && forecast.test_months.every(row => data.series.some(source => source.month === row.month && source.inflow === row.observed_pkr));
}

/** Fixed synthetic example; it is never a borrower record or training dataset. */
export function syntheticCashflowCSV() {
  const seasonal = [0, 20000, -10000, 80000, -25000, 30000, 90000, 130000, 45000, 150000, 65000, 100000];
  const lines = ['date,type,amount'];
  for (let i = 0; i < 36; i++) {
    const date = new Date(Date.UTC(2023, 9+i, 1));
    const label = `${date.getUTCFullYear()}-${String(date.getUTCMonth()+1).padStart(2, '0')}`;
    const receipts = 350000 + seasonal[i % 12] + i*2000 - Math.max(0, i-29)*15000;
    lines.push(`${label}-02,CR,${(receipts*.7).toFixed(2)}`, `${label}-15,DR,${(receipts*.72).toFixed(2)}`, `${label}-27,CR,${(receipts*.3).toFixed(2)}`);
  }
  return lines.join('\n') + '\n';
}
