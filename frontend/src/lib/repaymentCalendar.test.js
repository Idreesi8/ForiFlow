import test from 'node:test';
import assert from 'node:assert/strict';
import { isoDate, monthlyItems, paisa, saveIntent, validCalendar } from './repaymentCalendar.js';

test('paisa calculations never introduce binary decimal residue', () => {
  assert.equal(paisa('0.01') + paisa('0.09'), 10n);
  for (const value of ['NaN', 'Infinity', '-1', '1.001', '', 1.2]) assert.throws(() => paisa(value));
});
test('monthly dates retain the original month-end anchor including leap years', () => {
  assert.deepEqual(monthlyItems('2028-01-31', 3, '20.01').map(i => i.due_on), ['2028-01-31', '2028-02-29', '2028-03-31']);
  assert.deepEqual(monthlyItems('2026-12-30', 3, '20.01').map(i => i.due_on), ['2026-12-30', '2027-01-30', '2027-02-28']);
});
test('invalid dates counts and unagreed money cannot generate a contract draft', () => {
  for (const args of [['2026-02-30', 2, '10'], ['2026-01-01', 0, '10'], ['2026-01-01', 121, '10'],
    ['2026-01-01', 1.5, '10'], ['2026-01-01', 1, '0'], ['2026-01-01', 1, '1000000001'], ['9999-12-31', 2, '1']]) assert.throws(() => monthlyItems(...args));
  assert.equal(isoDate('2026-02-29'), false);
});
const report = () => ({ application_id: 7, as_of_date: '2026-11-08', limits: [], recent_receipts: [],
  schedule: { id: 5, is_current: true }, current_schedule_id: 5, schedule_versions: [{ id: 5 }], receipt_count: 0, receipt_offset: 0,
  installments: [{ installment: 1, due_on: '2026-11-01', amount_pkr: '100.01',
    paid_pkr: '20.01', outstanding_pkr: '80.00', days_past_due: 7, status: 'overdue' }],
  total_scheduled_pkr: '100.01', total_paid_pkr: '20.01', total_outstanding_pkr: '80.00', overdue_pkr: '80.00', maximum_days_past_due: 7 });
test('only the selected facility with consistent financial totals can render', () => {
  assert.equal(validCalendar(report(), 7), true);
  assert.equal(validCalendar(report(), 8), false);
  for (const field of ['total_paid_pkr', 'total_outstanding_pkr', 'overdue_pkr', 'total_scheduled_pkr']) assert.equal(validCalendar({ ...report(), [field]: '0.00' }, 7), false);
  const bad = report(); bad.installments[0].paid_pkr = '90.00'; assert.equal(validCalendar(bad, 7), false);
});
test('an empty calendar remains missing evidence', () => {
  assert.equal(validCalendar({ application_id: 7, as_of_date: '2026-11-08', schedule: null, installments: [], limits: [], recent_receipts: [] }, 7), true);
});
test('inconsistent dates, status and receipt allocations cannot render as trustworthy figures', () => {
  const bad = report(); bad.installments[0].days_past_due = 5; assert.equal(validCalendar(bad, 7), false);
  bad.installments[0].days_past_due = 7; bad.installments[0].status = 'upcoming'; assert.equal(validCalendar(bad, 7), false);
  const receipt = report(); receipt.receipt_count = 1;
  receipt.recent_receipts = [{ id: 1, reference: 'QA-REF', paid_on: '2026-11-02', total_pkr: '2.00', allocations: [{ installment: 1, amount_pkr: '1.00' }] }];
  assert.equal(validCalendar(receipt, 7), false);
});
test('save intent retains the UUID on retry and changes it after edits', () => {
  const first = saveIntent(null, { amount: '10.01' }, () => 'first');
  assert.equal(saveIntent(first, { amount: '10.01' }, () => 'unused'), first);
  assert.equal(saveIntent(first, { amount: '10.02' }, () => 'changed').key, 'changed');
});
