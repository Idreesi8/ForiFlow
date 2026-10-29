import { alertActions } from './ews.js';

export function validReviewedAlert(alert, id) {
  return alert?.id === id && Number.isSafeInteger(alert.borrower_id) && alert.borrower_id > 0 &&
    typeof alert.alert_status === 'string' && /^[a-f0-9]{64}$/.test(alert.review_token ?? '') &&
    Number.isFinite(alert.current_score) && Number.isFinite(alert.baseline_score);
}

export function savedAlertMatches(alert, original, step, payload) {
  if (!validReviewedAlert(alert, original.id) || alert.borrower_id !== original.borrower_id) return false;
  const statuses = { acknowledge: 'Acknowledged', 'action-required': 'Action Required', resolve: 'Resolved', dismiss: 'Dismissed' };
  if (statuses[step] && alert.alert_status !== statuses[step]) return false;
  if (payload.assigned_to && alert.assigned_to !== payload.assigned_to) return false;
  if (payload.due_date && alert.action_due_date !== payload.due_date) return false;
  if (step === 'action-required' && alert.action_note !== payload.action_note) return false;
  if (['resolve', 'dismiss'].includes(step) && alert.resolution_note !== payload.note) return false;
  return true;
}

export function alertReviewBlock(alert, step, actor) {
  if (!actor || typeof actor.username !== 'string' || !['manager', 'admin'].includes(actor.role))
    return 'Your current account needs enabled manager or admin access.';
  if (!alertActions(alert, { canManage: true }).includes(step))
    return `This action is no longer available while the alert is ${alert.alert_status}.`;
  return null;
}

export function alertPayload(step, form) {
  const note = form.note.trim(), assigned_to = form.assigned_to.trim();
  const due = form.due_date ? { due_date: form.due_date } : {};
  const notes = note ? { note } : {};
  if (step === 'assign') return { assigned_to, ...due, ...notes };
  if (step === 'due-date') return { ...due, ...notes };
  if (step === 'action-required') return { action_note: note, ...(assigned_to ? { assigned_to } : {}), ...due };
  return notes;
}

export function alertDraftError(step, form, today, officers) {
  if (['assign', 'action-required'].includes(step) &&
      (step === 'assign' || form.assigned_to) && !officers?.some(user => user.username === form.assigned_to))
    return 'Choose an enabled officer from the current list.';
  if (step === 'due-date' && !form.due_date) return 'Choose the follow-up due date.';
  if (['assign', 'due-date', 'action-required'].includes(step) && form.due_date &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(form.due_date) || form.due_date < today))
    return 'The due date must be today or later in Pakistan time.';
  if (['resolve', 'dismiss', 'action-required'].includes(step) && form.note.trim().length < 5)
    return 'Write at least 5 characters explaining the action.';
  if (form.note.trim().length > 1000) return 'Keep the note within 1,000 characters.';
  return null;
}
