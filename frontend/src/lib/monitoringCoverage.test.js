import assert from 'node:assert/strict';
import test from 'node:test';
import { monitoringCoverage, monitoringFormDirty, observationForm } from './monitoringCoverage.js';

const record = (month, changes = {}) => ({ id: month, borrower_id: 7, month_number: month,
  record_status: 'active', amount_paid_pkr: 100, ...changes });

test('empty history proposes month 1 without claiming that any payment is overdue', () => {
  const view = monitoringCoverage([], 84, 7);
  assert.equal(view.nextMonth, 1);
  assert.equal(view.recorded, 0);
  assert.equal(view.gaps, 0);
  assert.equal(view.months.length, 84);
  assert.ok(view.months.every(month => month.state === 'unrecorded'));
});

test('a later observation cannot hide earlier missing months', () => {
  const view = monitoringCoverage([record(3, { amount_paid_pkr: null })], 6, 7);
  assert.deepEqual(view.months.map(month => month.state), ['gap', 'gap', 'unknown', 'unrecorded', 'unrecorded', 'unrecorded']);
  assert.equal(view.nextMonth, 1);
  assert.equal(view.gaps, 2);
  assert.equal(view.unknown, 1);
});

test('a known zero payment is recorded, while an absent amount remains unknown', () => {
  const view = monitoringCoverage([record(1, { amount_paid_pkr: 0 }), record(2, { amount_paid_pkr: null })], 3, 7);
  assert.equal(view.recorded, 2);
  assert.equal(view.unknown, 1);
  assert.equal(view.months[0].state, 'recorded');
  assert.equal(view.nextMonth, 3);
});

test('corrections retain earlier versions but only the active amount determines coverage', () => {
  const original = record(1, { id: 40, record_status: 'superseded', amount_paid_pkr: null });
  const corrected = record(1, { id: 41, amount_paid_pkr: 0 });
  const view = monitoringCoverage([original, corrected], 3, 7);
  assert.equal(view.recorded, 1);
  assert.equal(view.unknown, 0);
  assert.equal(view.months[0].priorVersions, 1);
  assert.strictEqual(view.months[0].record, corrected);
});

test('a complete facility never wraps around or suggests a month outside its term', () => {
  const view = monitoringCoverage(Array.from({ length: 36 }, (_, index) => record(index + 1)), 36, 7);
  assert.equal(view.nextMonth, null);
  assert.equal(view.recorded, 36);
  assert.equal(view.gaps, 0);
});

for (const [label, rows, tenure] of [
  ['wrong case', [record(1, { borrower_id: 8 })], 3],
  ['duplicate active month', [record(1), record(1, { id: 20 })], 3],
  ['duplicate observation ID', [record(1), record(2, { id: 1 })], 3],
  ['month outside term', [record(4)], 3],
  ['noninteger month', [record(1.5)], 3],
  ['unrecognized version status', [record(1, { record_status: 'deleted' })], 3],
  ['negative amount', [record(1, { amount_paid_pkr: -1 })], 3],
  ['nonfinite amount', [record(1, { amount_paid_pkr: Infinity })], 3],
  ['unverified tenure', [], 0],
  ['oversized tenure', [], 85],
]) test(`inconsistent history fails closed: ${label}`, () => assert.throws(() => monitoringCoverage(rows, tenure, 7)));

test('preparing a correction preserves zero values, original sources and an existing score override', () => {
  const form = observationForm(record(2, { amount_paid_pkr: 0, days_late: 0, bureau_balance: 0,
    pos_cash_balance: 20, installment_status: 'On Time', observation_date: '2026-10-01',
    score_source: 'officer_override', monthly_score: 0, override_reason: 'Verified source evidence', data_source_primary: 'Bank Statement' }));
  assert.equal(form.amount_paid_pkr, '0');
  assert.equal(form.bureau_balance, '0');
  assert.equal(form.days_late, '0');
  assert.equal(form.current_score, '0');
  assert.equal(form.override, true);
  assert.equal(form.override_reason, 'Verified source evidence');
  assert.equal(form.observation_date, '2026-10-01');
  assert.equal(form.data_source_primary, 'Bank Statement');
});

test('unknown amounts and dates are not invented when preparing a correction', () => {
  const form = observationForm(record(2, { amount_paid_pkr: null, days_late: null, observation_date: null,
    bureau_balance: 12, pos_cash_balance: 0, score_source: 'ews_rule_adjusted' }));
  assert.equal(form.amount_paid_pkr, '');
  assert.equal(form.observation_date, '');
  assert.equal(form.days_late, '');
  assert.equal(form.override, false);
});

test('safe selection ignores month/case selectors but recognizes edited financial and date fields', () => {
  const initial = { borrower_id: '', month_number: '1', amount_paid_pkr: '', observation_date: '2026-10-24', override: false };
  assert.equal(monitoringFormDirty({ ...initial, borrower_id: '7', month_number: '3' }, initial), false);
  assert.equal(monitoringFormDirty({ ...initial, amount_paid_pkr: '0' }, initial), true);
  assert.equal(monitoringFormDirty({ ...initial, observation_date: '2026-10-23' }, initial), true);
  assert.equal(monitoringFormDirty({ ...initial, override: true }, initial), true);
});
