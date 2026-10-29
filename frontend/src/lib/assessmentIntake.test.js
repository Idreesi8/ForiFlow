import test from 'node:test';
import assert from 'node:assert/strict';
import { ALL_FIELDS, validateAssessment, assessmentPayload, assessmentKey, assessmentDisplay, statementReview } from './assessmentIntake.js';

const values = { applicant_name: '  Example Owner  ', business_name: 'Example business', loan_amount_pkr: '2400000.25', tenure_months: '36', monthly_digital_payments: '3200000', payment_history_score: '52.5001', inventory_turnover: '9.5', order_consistency: '90', existing_debt_pkr: '0', cash_flow_proxy: '850000', years_in_operation: '12', num_employees: '45' };
const statement = { csv: 'synthetic CSV', summary: { suggested_monthly_digital_payments: 3200000, suggested_cash_flow_proxy: 850000 } };

test('valid intake retains fractional figures and explicit zero without optional fields', () => {
  assert.deepEqual(validateAssessment(values), {});
  const payload = assessmentPayload({ ...values, unrelated: 'never submit' });
  assert.equal(payload.applicant_name, 'Example Owner');
  assert.equal(payload.loan_amount_pkr, 2400000.25);
  assert.equal(payload.payment_history_score, 52.5001);
  assert.equal(payload.existing_debt_pkr, 0);
  assert.equal(Object.hasOwn(payload, 'borrower_identifier'), false);
  assert.equal(Object.hasOwn(payload, 'unrelated'), false);
});
test('missing required figures are not accepted as zero', () => {
  for (const field of ALL_FIELDS.filter(field => !field.optional)) {
    for (const value of ['', '  ', undefined, null]) assert.equal(validateAssessment({ ...values, [field.name]: value })[field.name], 'Required.');
  }
});
test('nonfinite figures, out of range and fractional integer fields fail validation', () => {
  for (const value of ['Infinity', '-Infinity', 'NaN', '1e999', '-1', '500000001']) assert.ok(validateAssessment({ ...values, loan_amount_pkr: value }).loan_amount_pkr);
  assert.ok(validateAssessment({ ...values, tenure_months: '24.5' }).tenure_months);
  assert.ok(validateAssessment({ ...values, num_employees: '2.5' }).num_employees);
  assert.ok(validateAssessment({ ...values, business_name: 'x' }).business_name);
});
test('CNIC and NTN must have the digit counts enforced by the API', () => {
  for (const [kind, valid, invalid] of [['CNIC', ['12345-1234567-1', '1234512345671'], ['1234567', '12345678901234']], ['NTN', ['1234567', '1234567-8'], ['123456', '123456789']]]) {
    for (const value of valid) assert.deepEqual(validateAssessment({ ...values, borrower_identifier_type: kind, borrower_identifier: value }), {});
    for (const value of invalid) assert.ok(validateAssessment({ ...values, borrower_identifier_type: kind, borrower_identifier: value }).borrower_identifier);
  }
});
test('identifier pairing, listed options and contact formatting are checked before review', () => {
  assert.ok(validateAssessment({ ...values, borrower_identifier_type: 'CNIC' }).borrower_identifier);
  assert.ok(validateAssessment({ ...values, borrower_identifier: '1234567' }).borrower_identifier_type);
  assert.ok(validateAssessment({ ...values, borrower_identifier_type: 'Other', borrower_identifier: '1234567' }).borrower_identifier_type);
  assert.ok(validateAssessment({ ...values, business_sector: 'Invented' }).business_sector);
  assert.ok(validateAssessment({ ...values, contact_phone: '0300 1234567' }).contact_phone);
  assert.deepEqual(validateAssessment({ ...values, contact_phone: '+923001234567', borrower_public_id: 'brw-000012' }), {});
  assert.equal(assessmentPayload({ ...values, borrower_public_id: 'brw-000012' }).borrower_public_id, 'BRW-000012');
});
test('the review reference covers all fields and exact evidence text', () => {
  const key = assessmentKey(values, statement);
  for (const field of ALL_FIELDS) assert.notEqual(assessmentKey({ ...values, [field.name]: String(values[field.name] ?? '') + '1' }, statement), key);
  assert.notEqual(assessmentKey(values, { ...statement, csv: statement.csv + '\n' }), key);
  assert.notEqual(assessmentKey(values), key);
  assert.equal(assessmentKey({ ...values, unrelated: 'ignored' }, statement), key);
});
test('review distinguishes manual, statement matched and edited turnover without claiming verification', () => {
  assert.deepEqual(statementReview(null, values), { status: 'manual', changed: [] });
  assert.deepEqual(statementReview(statement, values), { status: 'attached', changed: [] });
  assert.deepEqual(statementReview(statement, { ...values, cash_flow_proxy: '849999.99' }), { status: 'edited', changed: ['cash_flow_proxy'] });
  assert.equal(statementReview(statement, { ...values, order_consistency: '0' }).status, 'attached');
});
test('review amounts preserve full digits instead of lakh/crore or whole-rupee rounding', () => {
  const money = ALL_FIELDS.find(field => field.name === 'loan_amount_pkr');
  assert.match(assessmentDisplay(money, 2400000.25), /2,400,000\.25/);
  assert.match(assessmentDisplay(money, 0.0000001), /0\.0000001/);
  assert.equal(assessmentDisplay(money, undefined), 'Not recorded');
  assert.equal(assessmentDisplay(ALL_FIELDS.find(field => field.name === 'tenure_months'), 36), '36 months');
});
