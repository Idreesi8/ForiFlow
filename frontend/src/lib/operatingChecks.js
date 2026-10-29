import { ALL_FIELDS } from './assessmentIntake.js';

export const OPERATING_FIELDS = ['loan_amount_pkr', 'tenure_months', 'monthly_digital_payments', 'cash_flow_proxy', 'existing_debt_pkr', 'inventory_turnover', 'order_consistency', 'num_employees'];
export const OPERATING_USES = {
  tenure_months: 'Principal per month and cash-flow comparison',
  existing_debt_pkr: 'Debt balance relative to annual typed cash flow',
  inventory_turnover: 'Implied stock cycle in days',
  order_consistency: 'Comparison with statement receipts stability',
  num_employees: 'Digital receipts per person',
};
const metrics = ['principal_per_month', 'cash_after_principal', 'principal_cashflow_ratio', 'debt_annual_cashflow_ratio', 'stock_cycle_days', 'digital_receipts_per_person', 'order_consistency_gap'];

export function prepareOperatingInputs(values, statement = null) {
  const inputs = {}, errors = [];
  for (const name of OPERATING_FIELDS) {
    const field = ALL_FIELDS.find(field => field.name === name);
    const raw = String(values[name] ?? '').trim(), number = Number(raw);
    if (!raw || !Number.isFinite(number) || number < field.min || number > field.max || (field.integer && !Number.isInteger(number))) errors.push({ name, label: field.label });
    else inputs[name] = number;
  }
  const csv = statement?.csv ?? null;
  return { inputs, errors, payload: { ...inputs, ...(csv !== null ? { statement_csv: csv } : {}) }, key: errors.length ? null : JSON.stringify([inputs, csv]) };
}

export function matchesOperatingReport(report, inputs, applicationId = null, statement = null) {
  if (report?.method !== 'operating-arithmetic-v1' || report.application_id !== applicationId) return false;
  if (!report.inputs || Object.keys(report.inputs).length !== OPERATING_FIELDS.length || prepareOperatingInputs(report.inputs).errors.length || OPERATING_FIELDS.some(name => report.inputs[name] !== inputs[name])) return false;
  if (!Array.isArray(report.metrics) || report.metrics.length !== metrics.length || new Set(report.metrics.map(row => row.name)).size !== metrics.length) return false;
  if (!report.metrics.every(row => metrics.includes(row.name) && (row.value === null || Number.isFinite(row.value)) && ['PKR', 'ratio', 'days', 'points'].includes(row.unit) && ['label', 'formula', 'note'].every(key => typeof row[key] === 'string'))) return false;
  if (!Array.isArray(report.notes) || !report.notes.every(note => typeof note === 'string')) return false;
  if (statement && report.statement_sha256 !== statement.summary?.source_sha256) return false;
  if (!statement && applicationId === null && report.order_source !== 'officer_entered') return false;
  return report.order_source === 'officer_entered'
    ? report.receipt_consistency_reference === null && report.statement_sha256 === null
    : report.order_source === 'statement_receipts_proxy' && /^[a-f0-9]{64}$/.test(report.statement_sha256 || '') && Number.isInteger(report.statement_full_months) && report.statement_full_months >= 3 && Number.isFinite(report.receipt_consistency_reference) && report.receipt_consistency_reference >= 0 && report.receipt_consistency_reference <= 100;
}
