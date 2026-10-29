import test from 'node:test';
import assert from 'node:assert/strict';
import { OPERATING_FIELDS, prepareOperatingInputs, matchesOperatingReport } from './operatingChecks.js';

const values = { loan_amount_pkr: '2400000.25', tenure_months: '36', monthly_digital_payments: '3200000', cash_flow_proxy: '850000', existing_debt_pkr: '400000', inventory_turnover: '9.5', order_consistency: '90', num_employees: '45' };
const prepared = prepareOperatingInputs(values);
const metricNames = ['principal_per_month', 'cash_after_principal', 'principal_cashflow_ratio', 'debt_annual_cashflow_ratio', 'stock_cycle_days', 'digital_receipts_per_person', 'order_consistency_gap'];
const report = { method: 'operating-arithmetic-v1', application_id: null, inputs: prepared.inputs, order_source: 'officer_entered', receipt_consistency_reference: null, statement_sha256: null,
  metrics: metricNames.map(name => ({ name, label: name, value: name === 'order_consistency_gap' ? null : 1, unit: 'ratio', formula: 'Described calculation', note: 'No trained credit effect' })), notes: ['Not an approval'] };

test('operating requests whitelist all eight figures and only the explicitly attached CSV', () => {
  const draft = prepareOperatingInputs({ ...values, applicant_name: 'Private', borrower_identifier: 'private', payment_history_score: '90' });
  assert.deepEqual(Object.keys(draft.payload), OPERATING_FIELDS);
  assert.equal(draft.payload.loan_amount_pkr, 2400000.25);
  assert.equal(prepareOperatingInputs(values, { csv: 'source CSV' }).payload.statement_csv, 'source CSV');
});
test('each operating figure and the exact evidence text invalidate the previous reference', () => {
  for (const name of OPERATING_FIELDS) assert.notEqual(prepareOperatingInputs({ ...values, [name]: String(Number(values[name]) / 2) }).key, prepared.key);
  assert.notEqual(prepareOperatingInputs(values, { csv: 'one' }).key, prepareOperatingInputs(values, { csv: 'two' }).key);
  assert.equal(prepareOperatingInputs({ ...values, applicant_name: 'Changed' }).key, prepared.key);
});
test('blank values, unsupported ranges, nonfinite and fractional counts cannot make a request', () => {
  for (const name of OPERATING_FIELDS) assert.equal(prepareOperatingInputs({ ...values, [name]: ' ' }).key, null);
  for (const [name, value] of [['loan_amount_pkr', 'Infinity'], ['tenure_months', '2'], ['tenure_months', '24.5'], ['num_employees', '4.5'], ['inventory_turnover', '51'], ['existing_debt_pkr', '-1'], ['order_consistency', '101']]) assert.equal(prepareOperatingInputs({ ...values, [name]: value }).key, null);
  assert.equal(prepareOperatingInputs({ ...values, existing_debt_pkr: '0', inventory_turnover: '0', num_employees: '0', cash_flow_proxy: '0' }).errors.length, 0);
});
test('only finite known calculations matching the exact figures and case are accepted', () => {
  assert.equal(matchesOperatingReport(report, prepared.inputs), true);
  assert.equal(matchesOperatingReport({ ...report, application_id: 2 }, prepared.inputs), false);
  assert.equal(matchesOperatingReport({ ...report, application_id: 2 }, prepared.inputs, 2), true);
  assert.equal(matchesOperatingReport({ ...report, inputs: { ...prepared.inputs, num_employees: 2 } }, prepared.inputs), false);
  assert.equal(matchesOperatingReport({ ...report, inputs: { ...prepared.inputs, applicant_name: 'Unexpected' } }, prepared.inputs), false);
  assert.equal(matchesOperatingReport({ ...report, metrics: [...report.metrics.slice(1), report.metrics[1]] }, prepared.inputs), false);
  assert.equal(matchesOperatingReport({ ...report, metrics: report.metrics.map(row => ({ ...row, value: Infinity })) }, prepared.inputs), false);
});
test('evidence comparison requires matching source fingerprint and a valid receipts reference', () => {
  const statement = { csv: 'test source', summary: { source_sha256: 'a'.repeat(64) } };
  const evidenceReport = { ...report, order_source: 'statement_receipts_proxy', statement_sha256: 'a'.repeat(64), statement_full_months: 3, receipt_consistency_reference: 90 };
  assert.equal(matchesOperatingReport(evidenceReport, prepared.inputs, null, statement), true);
  assert.equal(matchesOperatingReport(evidenceReport, prepared.inputs), false);
  assert.equal(matchesOperatingReport({ ...evidenceReport, statement_sha256: 'b'.repeat(64) }, prepared.inputs, null, statement), false);
  assert.equal(matchesOperatingReport({ ...evidenceReport, receipt_consistency_reference: 101 }, prepared.inputs, null, statement), false);
  assert.equal(matchesOperatingReport({ ...evidenceReport, statement_full_months: 2 }, prepared.inputs, null, statement), false);
});
