import test from 'node:test';
import assert from 'node:assert/strict';
import { MODEL_INPUT_FIELDS, prepareModelInputs, matchesModelInputs } from './modelInputs.js';

const values = { loan_amount_pkr: '2400000', monthly_digital_payments: '3200000', cash_flow_proxy: '850000', payment_history_score: '92', years_in_operation: '12' };
const draft = prepareModelInputs(values);
const report = { status: 'ready', inputs: draft.inputs, model_version: 'real-reference', credit_artifact_sha256: 'a'.repeat(64),
  input_checks: ['loan_to_income', 'payment_history_score', 'years_in_operation'].map(name => ({ name, entered: 1, model_value: 1, training_lower: 0, training_upper: 10, clipped: false })),
  applicability: { status: 'ready', atypical: false, training_percentile: 71.48, train_rows: 19449 } };

test('only the five intended numeric fields leave the form', () => {
  const result = prepareModelInputs({ ...values, applicant_name: 'Private name', borrower_identifier: 'private ID', statement_csv: 'private CSV', tenure_months: '36' });
  assert.deepEqual(Object.keys(result.inputs), MODEL_INPUT_FIELDS.map(field => field.name));
  assert.deepEqual(result.errors, []);
  assert.equal(result.inputs.loan_amount_pkr, 2400000);
});
test('equivalent number formatting and identity edits keep the same numeric reference', () => {
  assert.equal(prepareModelInputs({ ...values, loan_amount_pkr: ' 2400000.00 ', business_name: 'Changed' }).key, draft.key);
});
test('each model-relevant figure changes the numeric reference', () => {
  for (const field of MODEL_INPUT_FIELDS) assert.notEqual(prepareModelInputs({ ...values, [field.name]: String(Number(values[field.name]) / 2) }).key, draft.key);
});
test('missing, blank, nonfinite and invalid boundaries never become zero or a request', () => {
  for (const value of ['', '  ', undefined, null, 'NaN', 'Infinity', '-Infinity', '-1', '500000001']) {
    const result = prepareModelInputs({ ...values, loan_amount_pkr: value });
    assert.equal(result.key, null); assert.equal(result.errors[0].name, 'loan_amount_pkr');
  }
});
test('zero cash and history remain explicit valid values while a zero loan fails', () => {
  assert.equal(prepareModelInputs({ ...values, monthly_digital_payments: '0', cash_flow_proxy: '0', payment_history_score: '0', years_in_operation: '0' }).errors.length, 0);
  assert.equal(prepareModelInputs({ ...values, loan_amount_pkr: '0' }).key, null);
});
test('fractional repayment history is preserved across the exact encoding boundary', () => {
  assert.equal(prepareModelInputs({ ...values, payment_history_score: '52.5001' }).inputs.payment_history_score, 52.5001);
});
test('matching numerical echoes and finite model facts are accepted', () => {
  assert.equal(matchesModelInputs(report, draft.inputs), true);
  assert.equal(matchesModelInputs({ ...report, status: 'partial', applicability: { status: 'unavailable' } }, draft.inputs), true);
  assert.equal(matchesModelInputs({ status: 'unavailable', inputs: draft.inputs, reason: 'Unsupported contract' }, draft.inputs), true);
});
test('wrong figures, missing figures and extra echoed identity are rejected', () => {
  for (const inputs of [{ ...draft.inputs, loan_amount_pkr: 1 }, {}, { ...draft.inputs, applicant_name: 'Private' }]) assert.equal(matchesModelInputs({ ...report, inputs }, draft.inputs), false);
});
test('invalid reference, feature duplication or invented percentile is rejected', () => {
  assert.equal(matchesModelInputs({ ...report, credit_artifact_sha256: null }, draft.inputs), false);
  assert.equal(matchesModelInputs({ ...report, input_checks: [report.input_checks[0], report.input_checks[0], report.input_checks[1]] }, draft.inputs), false);
  for (const training_percentile of [NaN, Infinity, -1, 101, '71.48']) assert.equal(matchesModelInputs({ ...report, applicability: { ...report.applicability, training_percentile } }, draft.inputs), false);
});
