import test from 'node:test';
import assert from 'node:assert/strict';
import { STATES, blankEvidence, evidenceDraft, evidencePayload, validEvidenceReport, validEvidenceRow, validEvidenceHistory } from './caseData.js';
import { saveIntent } from './repaymentCalendar.js';

const stream = '01234567-89ab-4cde-8fab-0123456789ab';
const fields = ['loan_amount_pkr', 'tenure_months', 'monthly_digital_payments', 'payment_history_score', 'inventory_turnover', 'order_consistency', 'existing_debt_pkr', 'cash_flow_proxy', 'years_in_operation', 'num_employees'];
const row = () => ({ id: 1, application_id: 7, stream_key: stream, revision: 1, supersedes_id: null,
  event_kind: 'recorded', status: 'missing', source_kind: 'bank_statement', source_reference: 'FICTIONAL-QA-01', captured_on: '2026-10-01',
  period_from: null, period_to: null, input_fields: ['cash_flow_proxy'], permission_basis: 'not_recorded', permission_reference: null,
  permission_on: null, permission_expires_on: null, purposes: ['credit_assessment'], input_snapshot: { cash_flow_proxy: 1000 },
  note: 'Fictional evidence reference only', created_by: 'qa_builder', created_at: '2026-11-08T12:00:00Z', flags: [] });
const report = () => ({ application_id: 7, as_of_date: '2026-11-08', training_authorised: false, data_access_granted: false,
  limits: [], total: 1, offset: 0, rows: [row()], counts: Object.fromEntries(Object.keys(STATES).map(key => [key, key === 'missing' ? 1 : 0])),
  field_coverage: fields.map(field => ({ field, label: field, saved_value: 1000, source_records: field === 'cash_flow_proxy' ? 1 : 0, dated_permission_record_count: 0 })) });

test('research and monitoring permission are never selected by default', () => {
  assert.deepEqual(blankEvidence().purposes, ['credit_assessment']);
  assert.equal(blankEvidence().permission_basis, 'not_recorded');
});
test('unrecorded permission cannot transmit stale hidden documentary details', () => {
  const form = { ...blankEvidence(), permission_reference: 'old reference', permission_on: '2026-10-01', permission_expires_on: '2026-12-01' };
  const payload = evidencePayload(form);
  assert.equal(payload.permission_reference, null); assert.equal(payload.permission_on, null); assert.equal(payload.permission_expires_on, null);
  assert.equal(form.permission_reference, 'old reference');
});
test('correction drafts carry references without treating unknown dates as defaults', () => {
  const draft = evidenceDraft(row());
  assert.equal(draft.permission_on, ''); assert.equal(draft.period_from, '');
  assert.equal(evidencePayload(draft).permission_on, null);
});
test('valid reports stay linked to the selected case and explicitly withhold automatic grants', () => {
  assert.equal(validEvidenceReport(report(), 7), true);
  assert.equal(validEvidenceReport(report(), 8), false);
  assert.equal(validEvidenceReport({ ...report(), training_authorised: true }, 7), false);
  assert.equal(validEvidenceReport({ ...report(), data_access_granted: true }, 7), false);
});
test('invalid source snapshots cannot masquerade as evidence for saved fields', () => {
  for (const change of [{ application_id: 8 }, { input_fields: ['applicant_name'] }, { purposes: ['credit_assessment', 'credit_assessment'] },
    { input_snapshot: { cash_flow_proxy: NaN } }, { status: 'recorded' }, { event_kind: 'withdrawn' }]) {
    assert.equal(validEvidenceRow({ ...row(), ...change }, 7), false);
  }
});
test('counts and reference coverage are not accepted when contradictory', () => {
  const bad = report(); bad.counts.missing = 0; assert.equal(validEvidenceReport(bad, 7), false);
  const coverage = report(); coverage.field_coverage[0].dated_permission_record_count = 1; assert.equal(validEvidenceReport(coverage, 7), false);
});
test('another source or another case cannot appear as the selected history', () => {
  const history = { application_id: 7, stream_key: stream, as_of_date: '2026-11-08', total: 1, offset: 0, rows: [row()] };
  assert.equal(validEvidenceHistory(history, 7, stream), true);
  assert.equal(validEvidenceHistory(history, 8, stream), false);
  assert.equal(validEvidenceHistory({ ...history, rows: [{ ...row(), stream_key: 'another-source' }] }, 7, stream), false);
});
test('reordered selections recover one save intent while an added research scope changes it', () => {
  const form = { ...blankEvidence(), source_reference: ' QA ', note: ' Fictional note ', input_fields: ['cash_flow_proxy', 'loan_amount_pkr'] };
  const first = saveIntent(null, evidencePayload(form), () => 'one');
  assert.equal(saveIntent(first, evidencePayload({ ...form, input_fields: [...form.input_fields].reverse() }), () => 'unused'), first);
  assert.equal(saveIntent(first, evidencePayload({ ...form, purposes: ['credit_assessment', 'model_research'] }), () => 'two').key, 'two');
});
