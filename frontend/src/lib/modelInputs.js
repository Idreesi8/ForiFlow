/** The five figures accepted by the unsaved three-feature model check. */
export const MODEL_INPUT_FIELDS = [
  { name: 'loan_amount_pkr', label: 'Loan amount', min: 0, max: 500000000, exclusiveMin: true },
  { name: 'monthly_digital_payments', label: 'Monthly digital payments', min: 0, max: 1000000000 },
  { name: 'cash_flow_proxy', label: 'Monthly cash flow proxy', min: 0, max: 1000000000 },
  { name: 'payment_history_score', label: 'Payment history score', min: 0, max: 100 },
  { name: 'years_in_operation', label: 'Years in operation', min: 0, max: 100 },
];

export function prepareModelInputs(values) {
  const inputs = {}, errors = [];
  for (const field of MODEL_INPUT_FIELDS) {
    const raw = String(values[field.name] ?? '').trim(), number = Number(raw);
    if (!raw || !Number.isFinite(number) || number > field.max || (field.exclusiveMin ? number <= field.min : number < field.min)) {
      errors.push({ name: field.name, label: field.label });
    } else inputs[field.name] = number;
  }
  return { inputs, errors, key: errors.length ? null : JSON.stringify(inputs) };
}

export function matchesModelInputs(report, inputs) {
  if (!['ready', 'partial', 'unavailable'].includes(report?.status) || !report.inputs) return false;
  if (Object.keys(report.inputs).length !== MODEL_INPUT_FIELDS.length || MODEL_INPUT_FIELDS.some(({ name }) => report.inputs[name] !== inputs[name])) return false;
  if (report.status === 'unavailable') return typeof report.reason === 'string';
  if (!/^[a-f0-9]{64}$/.test(report.credit_artifact_sha256 || '') || typeof report.model_version !== 'string') return false;
  const names = ['loan_to_income', 'payment_history_score', 'years_in_operation'];
  if (!Array.isArray(report.input_checks) || report.input_checks.length !== 3 || new Set(report.input_checks.map(row => row.name)).size !== 3) return false;
  if (!report.input_checks.every(row => names.includes(row.name) && ['entered', 'model_value', 'training_lower', 'training_upper'].every(key => Number.isFinite(row[key])) && typeof row.clipped === 'boolean')) return false;
  const anomaly = report.applicability;
  return anomaly?.status === 'unavailable' || (anomaly?.status === 'ready' && typeof anomaly.atypical === 'boolean' && Number.isFinite(anomaly.training_percentile) && anomaly.training_percentile >= 0 && anomaly.training_percentile <= 100 && Number.isInteger(anomaly.train_rows) && anomaly.train_rows > 0);
}
