import test from 'node:test';
import assert from 'node:assert/strict';
import { validOutcomeEvidence } from './outcomeEvidence.js';

const query = { horizon: 3, limit: 10, offset: 0, status_filter: '' };
const fixture = () => ({
  horizon_months: 3, training_ready: false, offset: 0, limit: 10, status_filter: null,
  total: 3, captured_at: '2026-11-07T12:00:00Z', basis: 'Approval-based reporting months', limits: ['Recorded evidence only.'],
  counts: { approved_facilities: 3, needs_approval_record: 0, shorter_term: 0,
    collecting: 0, needs_evidence: 2, covered: 1, covered_with_30_plus: 1,
    distinct_linked_borrowers: 2, additional_repeat_facilities: 1, unlinked_facilities: 0 },
  rows: [1, 2, 3].map(id => ({ application_id: id, business_name: 'Fictional workshop',
    status: id === 1 ? 'covered' : 'needs_evidence', recorded_months: id === 1 ? 3 : 1,
    usable_months: id === 1 ? 3 : 0, reasons: ['Inspect source records.'], recorded_30_plus: id === 1 })),
});

test('coherent evidence counts and empty pages are displayed without inventing outcomes', () => {
  assert.equal(validOutcomeEvidence(fixture(), query), true);
  const empty = fixture();
  empty.total = 0; empty.rows = [];
  Object.keys(empty.counts).forEach(key => { empty.counts[key] = 0; });
  assert.equal(validOutcomeEvidence(empty, query), true);
  const beyond = { ...fixture(), rows: [], offset: 40 };
  assert.equal(validOutcomeEvidence(beyond, { ...query, offset: 40 }), true);
});

test('impossible partitions, false training readiness and missing signal counts are withheld', () => {
  for (const change of [
    data => { data.counts.covered = 2; },
    data => { data.counts.covered_with_30_plus = 2; },
    data => { delete data.counts.covered_with_30_plus; },
    data => { data.counts.additional_repeat_facilities = 0; },
    data => { data.counts.covered = -1; },
    data => { data.counts.covered = '1'; },
    data => { data.training_ready = true; },
  ]) {
    const data = fixture(); change(data);
    assert.equal(validOutcomeEvidence(data, query), false);
  }
});

test('a response belongs to the selected window, filter and page before it can be shown', () => {
  assert.equal(validOutcomeEvidence(fixture(), { ...query, horizon: 6 }), false);
  assert.equal(validOutcomeEvidence(fixture(), { ...query, offset: 10 }), false);
  assert.equal(validOutcomeEvidence(fixture(), { ...query, status_filter: 'covered' }), false);
  const filtered = fixture();
  filtered.status_filter = 'covered'; filtered.total = 1; filtered.rows = filtered.rows.slice(0, 1);
  assert.equal(validOutcomeEvidence(filtered, { ...query, status_filter: 'covered' }), true);
  filtered.total = 3;
  assert.equal(validOutcomeEvidence(filtered, { ...query, status_filter: 'covered' }), false);
});

test('duplicate cases, invented labels and impossible monthly coverage are withheld', () => {
  for (const change of [
    data => { data.rows[1].application_id = 1; },
    data => { data.rows[0].status = 'defaulted'; },
    data => { data.rows[1].usable_months = 3; },
    data => { data.rows[0].recorded_months = 12; },
    data => { data.rows.pop(); },
  ]) {
    const data = fixture(); change(data);
    assert.equal(validOutcomeEvidence(data, query), false);
  }
});
