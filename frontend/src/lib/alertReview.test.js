import test from 'node:test';
import assert from 'node:assert/strict';
import { alertDraftError, alertPayload, alertReviewBlock, savedAlertMatches, validReviewedAlert } from './alertReview.js';

const alert = { id: 7, borrower_id: 3, alert_status: 'Open', current_score: 35, baseline_score: 70, review_token: 'a'.repeat(64) };
const actor = { username: 'officer', role: 'manager' };
const form = { assigned_to: 'enabled', note: '  Verified follow-up  ', due_date: '2026-10-30' };
const officers = [{ username: 'enabled', role: 'analyst' }];

test('a current reviewed alert must have the right identity, scores and server token', () => {
  assert.equal(validReviewedAlert(alert, 7), true);
  for (const patch of [{ id: 8 }, { review_token: undefined }, { review_token: 'bad' }, { current_score: NaN }])
    assert.equal(validReviewedAlert({ ...alert, ...patch }, 7), false);
});
test('review respects current authority and actual lifecycle availability', () => {
  assert.equal(alertReviewBlock(alert, 'acknowledge', actor), null);
  assert.match(alertReviewBlock(alert, 'resolve', { ...actor, role: 'analyst' }), /manager/);
  assert.match(alertReviewBlock({ ...alert, alert_status: 'Resolved', is_open: false }, 'resolve', actor), /no longer/);
  assert.match(alertReviewBlock(alert, 'action-required', actor), /no longer/);
});
test('only enabled directory members can receive new assignments', () => {
  assert.equal(alertDraftError('assign', form, '2026-10-29', officers), null);
  assert.match(alertDraftError('assign', { ...form, assigned_to: 'disabled' }, '2026-10-29', officers), /enabled/);
  assert.match(alertDraftError('action-required', { ...form, assigned_to: 'disabled' }, '2026-10-29', officers), /enabled/);
  assert.equal(alertDraftError('action-required', { ...form, assigned_to: '' }, '2026-10-29', officers), null);
});
test('past deadlines cannot be proposed but do not block closing an overdue alert', () => {
  const old = { ...form, due_date: '2026-10-28' };
  assert.match(alertDraftError('assign', old, '2026-10-29', officers), /today or later/);
  assert.equal(alertDraftError('resolve', old, '2026-10-29', officers), null);
  assert.match(alertDraftError('due-date', { ...form, due_date: '' }, '2026-10-29', officers), /Choose/);
  assert.match(alertDraftError('dismiss', { ...form, note: '  x  ' }, '2026-10-29', officers), /5 characters/);
});
test('closing and acknowledging send no unrelated owner or deadline changes', () => {
  assert.deepEqual(alertPayload('resolve', form), { note: 'Verified follow-up' });
  assert.deepEqual(alertPayload('acknowledge', { ...form, note: '' }), {});
  assert.deepEqual(alertPayload('assign', { ...form, due_date: '' }), { assigned_to: 'enabled', note: 'Verified follow-up' });
  assert.deepEqual(alertPayload('action-required', { ...form, assigned_to: '', due_date: '' }), { action_note: 'Verified follow-up' });
});

test('an unrelated or incomplete save response cannot be shown as success', () => {
  const saved = { ...alert, alert_status: 'Resolved', resolution_note: 'Verified recovery.' };
  assert.equal(savedAlertMatches(saved, alert, 'resolve', { note: 'Verified recovery.' }), true);
  assert.equal(savedAlertMatches(alert, alert, 'resolve', { note: 'Verified recovery.' }), false);
  assert.equal(savedAlertMatches({ ...saved, borrower_id: 9 }, alert, 'resolve', { note: 'Verified recovery.' }), false);
  assert.equal(savedAlertMatches({ ...alert, assigned_to: 'other' }, alert, 'assign', { assigned_to: 'enabled' }), false);
});
