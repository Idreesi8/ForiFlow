import { useEffect, useRef, useState } from 'react';
import { alertLifecycle, apiErrorMessage, fetchAlert, fetchAlertAssignees, fetchMe } from '../api/client.js';
import { updateStoredAccount } from '../api/auth.js';
import { alertDraftError, alertPayload, alertReviewBlock, savedAlertMatches, validReviewedAlert } from '../lib/alertReview.js';
import { ACTION_LABELS, alertEvidence } from '../lib/ews.js';
import { containDialogFocus } from '../lib/dialogFocus.js';
import { formatDate, formatDateTime } from '../lib/format.js';
import { useBusinessDate } from '../hooks/useBusinessDate.js';
import { useUnsavedWork } from './UnsavedWork.jsx';
import { ErrorState, LoadingState } from './common/States.jsx';

export default function AlertActionDialog({ candidate, onClose, onSaved }) {
  const { alert: original, step } = candidate;
  const dialog = useRef(null), heading = useRef(null), saving = useRef(false);
  const [form, setForm] = useState({ note: '', assigned_to: original.assigned_to ?? '', due_date: original.action_due_date ?? '' });
  const [view, setView] = useState({ loading: true }), [revision, setRevision] = useState(0);
  const [review, setReview] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState(null), [uncertain, setUncertain] = useState(false), [discard, setDiscard] = useState(false);
  const [acceptChanged, setAcceptChanged] = useState(false);
  const today = useBusinessDate();
  useUnsavedWork({ label: `Alert #${original.id} ${ACTION_LABELS[step].toLowerCase()} draft`, dirty: true, busy });
  useEffect(() => {
    const element = dialog.current, previous = document.activeElement;
    element.showModal(); heading.current.focus();
    return () => { element.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setView({ loading: true }); setAcceptChanged(false); setError(null); setUncertain(false);
    Promise.all([fetchAlert(original.id, { signal: controller.signal }), fetchMe({ signal: controller.signal }), fetchAlertAssignees({ signal: controller.signal })])
      .then(([alert, actor, officers]) => {
        if (controller.signal.aborted) return;
        if (!validReviewedAlert(alert, original.id) || alert.borrower_id !== original.borrower_id ||
            !actor || typeof actor.username !== 'string' || !['admin','manager','analyst'].includes(actor.role) ||
            !Array.isArray(officers) || officers.some(user => typeof user.username !== 'string' || !['admin', 'manager', 'analyst'].includes(user.role)))
          throw Object.assign(new Error('The current alert or officer list could not be verified.'), { code: 'INVALID_ALERT_REVIEW' });
        updateStoredAccount(actor);
        setView({ loading: false, alert, actor, officers, checkedAt: new Date().toISOString() });
      }).catch(err => {
        if (!controller.signal.aborted) setView({ loading: false, error: err.code === 'INVALID_ALERT_REVIEW' ? err.message : apiErrorMessage(err, 'Could not check the current alert and your account.') });
      });
    return () => controller.abort();
  }, [original.id, revision]);
  const block = view.alert ? alertReviewBlock(view.alert, step, view.actor) : null;
  const invalid = view.alert ? alertDraftError(step, form, today, view.officers) : null;
  const changed = view.alert && original.review_token !== view.alert.review_token;
  const ready = Boolean(view.alert && !view.loading && !view.error && !block && !invalid && !busy && !uncertain);
  const refresh = () => { setRevision(v => v + 1); };
  const submit = async event => {
    event.preventDefault(); if (!ready || saving.current) return;
    if (!review) { setReview(true); refresh(); heading.current.focus(); return; }
    if (changed && !acceptChanged) return;
    saving.current = true; setBusy(true); setError(null);
    try {
      const payload = alertPayload(step, form);
      const saved = await alertLifecycle(original.id, step, { ...payload, expected_review_token: view.alert.review_token });
      if (!savedAlertMatches(saved, original, step, payload))
        throw Object.assign(new Error('The save response could not be verified. Refresh and inspect the alert before trying again.'), { code: 'INVALID_ALERT_SAVE' });
      onSaved(saved);
    } catch (err) {
      setError(err.code === 'INVALID_ALERT_SAVE' ? err.message : apiErrorMessage(err, 'Could not verify the alert change.'));
      setUncertain(true);
    } finally { saving.current = false; setBusy(false); }
  };
  const close = () => { if (!saving.current) setDiscard(true); };
  const set = key => event => setForm(previous => ({ ...previous, [key]: event.target.value }));
  const assigns = ['assign', 'action-required'].includes(step), dates = assigns || step === 'due-date';
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="alert-action-title" onKeyDown={containDialogFocus}
    onCancel={event => { event.preventDefault(); close(); }}>
    <form onSubmit={submit} className="flex max-h-[85dvh] min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-200 px-5 py-4"><h2 id="alert-action-title" ref={heading} tabIndex={-1} className="text-xl font-bold outline-none">{discard ? 'Discard this alert draft?' : `${review ? 'Review' : 'Prepare'} ${ACTION_LABELS[step].toLowerCase()}`}</h2><p className="mt-2 break-words text-sm text-slate-600">Alert #{original.id} · {original.business_name || `Facility #${original.borrower_id}`}</p></header>
      <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 py-4" aria-busy={view.loading || busy}>
        {discard ? <p className="text-sm">Your unsaved note and proposed follow-up will be lost. Keep editing to preserve them.</p> : <>
          <p className="text-sm text-slate-600">{review ? 'Check the current evidence and proposed change before saving.' : 'Prepare the follow-up, then review it before saving.'} This records alert follow-up only; it does not change a credit decision.</p>
          {view.loading ? <LoadingState label="Checking the alert and enabled officers…" /> : view.error ? <ErrorState message={view.error} onRetry={refresh} /> : view.alert ? <>
            <section className="rounded-xl bg-slate-50 p-3 text-sm" aria-label="Current alert"><h3 className="font-semibold">Current alert</h3><p className="mt-2">{view.alert.alert_status} · {view.alert.severity || 'Legacy severity not recorded'}</p><p>Owner: {view.alert.assigned_to || 'Unassigned'}</p><p>Due: {view.alert.action_due_date ? formatDate(view.alert.action_due_date) : 'Not set'}</p><p>Baseline {view.alert.baseline_score.toFixed(1)} · Current {view.alert.current_score.toFixed(1)}</p>{view.alert.action_note ? <p className="mt-2 whitespace-pre-wrap break-words">Current action: {view.alert.action_note}</p> : null}{review ? <ul className="mt-2 space-y-2">{alertEvidence(view.alert).map((item, index) => <li key={index} className="break-words"><strong>{item.label}.</strong> {item.text}</li>)}</ul> : null}</section>
            {block ? <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950">{block}</p> : null}
            {changed ? <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950"><p>The alert changed since you opened it. Check the current details above.</p>{review ? <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={acceptChanged} onChange={event => setAcceptChanged(event.target.checked)} disabled={busy} /><span>I reviewed the latest alert and still want this change.</span></label> : null}</div> : null}
            {review ? <section aria-label="Proposed change" className="space-y-2 rounded-xl border border-brand-200 p-3 text-sm"><h3 className="font-semibold">Proposed change: {ACTION_LABELS[step]}</h3>{assigns ? <p>Owner: {form.assigned_to || 'Keep current owner'}</p> : null}{dates ? <p>Due: {form.due_date ? formatDate(form.due_date) : 'Keep current due date'}</p> : null}<p className="whitespace-pre-wrap break-words">{step === 'action-required' ? 'Required action' : 'Note'}: {form.note.trim() || 'No note added'}</p>{['resolve', 'dismiss'].includes(step) ? <p className="font-semibold text-amber-900">This closes the alert. Closed alerts remain on file and cannot be reopened.</p> : null}</section> : <div className="space-y-3">
              {assigns ? <label className="block text-sm">Follow-up officer{step === 'action-required' ? ' (optional)' : ''}<select value={form.assigned_to} onChange={set('assigned_to')} className="field-input mt-1" required={step === 'assign'}><option value="">{step === 'assign' ? 'Choose an enabled officer' : 'Keep current owner'}</option>{form.assigned_to && !view.officers.some(user => user.username === form.assigned_to) ? <option disabled value={form.assigned_to}>{form.assigned_to} — unavailable</option> : null}{view.officers.map(user => <option key={user.username} value={user.username}>{user.username} · {user.role}</option>)}</select></label> : null}
              {dates ? <label className="block text-sm">Due date{step === 'due-date' ? '' : ' (optional)'} · PKT<input type="date" value={form.due_date} min={today} required={step === 'due-date'} onChange={set('due_date')} className="field-input mt-1" /></label> : null}
              <label className="block text-sm">{step === 'action-required' ? 'Required action' : 'Follow-up note'}{['resolve', 'dismiss', 'action-required'].includes(step) ? ' (at least 5 characters)' : ' (optional)'}<textarea className="field-input mt-1" rows={3} maxLength={1000} value={form.note} onChange={set('note')} /></label>
              <p className="text-xs text-slate-500">Unsaved entries stay only in this tab. Closing the draft requires a discard confirmation.</p>
            </div>}
            {invalid ? <p role="status" className="text-sm text-amber-900">{invalid}</p> : null}
            <p className="text-xs text-slate-500">Checked {formatDateTime(view.checkedAt)} · {view.actor.username} · {view.actor.role}. The server checks current authority and refuses changed alerts when saving.</p>
          </> : null}
          {error ? <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{error} Your draft is preserved. Refresh and inspect current records before another attempt.</p> : null}
          <button type="button" className="btn-secondary text-xs" disabled={busy || view.loading} onClick={refresh}>{review ? 'Refresh review' : 'Refresh current details'}</button>
        </>}
      </div>
      <footer className="flex shrink-0 flex-wrap gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4">
        {discard ? <><button type="button" className="btn-primary" onClick={() => setDiscard(false)}>Keep editing</button><button type="button" className="btn-secondary" onClick={onClose}>Discard draft</button></> : <>
          <button type="button" className="btn-secondary" disabled={busy} onClick={close}>Cancel draft</button>
          {review ? <button type="button" className="btn-secondary" disabled={busy} onClick={() => { setReview(false); refresh(); }}>Edit draft</button> : null}
          <button type="submit" className="btn-primary" disabled={!ready || (review && changed && !acceptChanged)}>{busy ? 'Saving…' : review ? `Confirm ${ACTION_LABELS[step].toLowerCase()}` : 'Review change'}</button>
          {busy ? <p role="status" className="w-full text-xs">Wait for the result. This request is not retried automatically.</p> : null}
        </>}
      </footer>
    </form>
  </dialog>;
}
