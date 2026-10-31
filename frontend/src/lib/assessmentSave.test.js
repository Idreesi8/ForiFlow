import test from 'node:test';
import assert from 'node:assert/strict';
import { assessmentIntent, assessmentReceiptMatches, assessmentSaveUncertain } from './assessmentSave.js';

const values = { applicant_name: ' Fictional Owner ', business_name: 'Fictional Workshop', loan_amount_pkr: '100000', tenure_months: '12' };
const payload = { applicant_name: 'Fictional Owner', business_name: 'Fictional Workshop', loan_amount_pkr: 100000, tenure_months: 12 };
const receipt = { ...payload, application_id: 12, risk_score: 70, monthly_installment_pkr: 8333.33,
  decision: 'Manual Review', risk_band: 'Medium Risk', explanation: { application_id: 12, base_value: 50,
    narrative: 'Fictional explanation', feature_contributions: [{ feature: 'age', label: 'Business age', contribution: 20 }] } };

test('cosmetic numeric and whitespace edits retain the saved intent; changed figures and evidence do not', () => {
  assert.equal(assessmentIntent(values), assessmentIntent({ ...values, applicant_name: 'Fictional Owner', loan_amount_pkr: '1e5', tenure_months: '12.0' }));
  assert.notEqual(assessmentIntent(values), assessmentIntent({ ...values, loan_amount_pkr: '100001' }));
  assert.notEqual(assessmentIntent(values, { csv: 'one' }), assessmentIntent(values, { csv: 'two' }));
});

test('a receipt must identify the same case figures and have usable finite model output', () => {
  assert.equal(assessmentReceiptMatches(receipt, payload), true);
  for (const change of [{ application_id: 0 }, { application_id: '12' }, { business_name: 'Wrong business' },
    { applicant_name: 'Other owner' }, { loan_amount_pkr: 100001 }, { tenure_months: 13 }, { risk_score: NaN },
    { risk_score: 101 }, { monthly_installment_pkr: Infinity }, { decision: 'unknown' }, { risk_band: 'unknown' },
    { explanation: null }, { explanation: { ...receipt.explanation, application_id: 13 } }])
    assert.equal(assessmentReceiptMatches({ ...receipt, ...change }, payload), false);
});

test('timeouts, server errors and unverifiable responses retain recovery; definite rejections allow editing', () => {
  for (const error of [new Error('Unverified'), {}, { response: { status: 408 } }, { response: { status: 500 } }, { response: { status: 503 } }])
    assert.equal(assessmentSaveUncertain(error), true);
  for (const status of [400, 401, 403, 404, 409, 422, 429])
    assert.equal(assessmentSaveUncertain({ response: { status } }), false);
});
