import { useEffect, useRef, useState } from "react";
import { updateStoredAccount } from "../api/auth.js";
import { apiErrorMessage, fetchApplication, fetchMe } from "../api/client.js";
import { recommendationLabel } from "../lib/decisions.js";
import { containDialogFocus } from "../lib/dialogFocus.js";
import { formatDateTime, formatPKRExact } from "../lib/format.js";
import { ErrorState, LoadingState, Spinner } from "./common/States.jsx";

const ACTIONS = {
  Approved: { title: "Review approval", confirm: "Confirm approval", result: "Approve this application", style: "bg-emerald-700 text-white hover:bg-emerald-800" },
  Rejected: { title: "Review rejection", confirm: "Confirm rejection", result: "Reject this application", style: "bg-rose-700 text-white hover:bg-rose-800" },
  Escalated: { title: "Review escalation", confirm: "Confirm escalation", result: "Escalate to an admin", style: "bg-violet-700 text-white hover:bg-violet-800" },
};

function blockedReason(record, officer, action) {
  if (!['Pending', 'Escalated'].includes(record.decision_status)) return `This case is now ${record.decision_status || 'unavailable'}. Inspect its current record before taking another action.`;
  if (!officer.is_active || !['admin', 'manager'].includes(officer.role)) return 'Your current account cannot record credit decisions. A manager or admin must review this case.';
  if (record.decision_status === 'Escalated' && officer.role !== 'admin') return 'This case is now escalated. An admin must decide it.';
  if (action === 'Escalated' && officer.role === 'admin') return 'An admin is the final authority and decides the case rather than escalating it.';
  if (action === 'Approved' && !['manager', 'admin'].includes(record.approval_authority)) return 'The current approval authority could not be verified. Refresh the details before approving.';
  if (action === 'Approved' && record.approval_authority === 'admin' && officer.role !== 'admin') return 'Approval now requires an admin. Return to the reason to consider another action.';
  return null;
}

/** Read-only preflight; the parent performs the single, explicit decision write. */
export default function DecisionConfirmation({ candidate, submitting, onCancel, onConfirm, onRefreshed }) {
  const dialog = useRef(null);
  const heading = useRef(null);
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState({ loading: true, error: null, record: null, officer: null, checkedAt: null });
  const action = ACTIONS[candidate.decision];

  useEffect(() => {
    const previous = document.activeElement;
    const element = dialog.current;
    element.showModal();
    heading.current.focus({ preventScroll: true });
    return () => { element.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setView({ loading: true, error: null, record: null, officer: null, checkedAt: null });
    Promise.all([fetchApplication(candidate.applicationId, { signal: controller.signal }), fetchMe({ signal: controller.signal })])
      .then(([record, officer]) => {
        if (controller.signal.aborted) return;
        if (record.id !== candidate.applicationId || !officer.username || !Number.isFinite(record.loan_amount_pkr) || record.loan_amount_pkr <= 0 || !Number.isInteger(record.tenure_months) || record.tenure_months < 1 || !['Approved', 'Rejected', 'Manual Review'].includes(record.decision)) {
          throw Object.assign(new Error('Invalid review details'), { code: 'INVALID_REVIEW_DETAILS' });
        }
        updateStoredAccount(officer);
        onRefreshed(record);
        setView({ loading: false, error: null, record, officer, checkedAt: new Date().toISOString() });
      })
      .catch(error => {
        if (!controller.signal.aborted) setView({ loading: false, error: error.code === 'INVALID_REVIEW_DETAILS' ? 'The returned case details could not be verified. Refresh before recording an action.' : apiErrorMessage(error, 'Could not verify the current case and account.'), record: null, officer: null, checkedAt: null });
      });
    return () => controller.abort();
  }, [candidate.applicationId, revision, onRefreshed]);

  const { record, officer } = view;
  const block = record && officer ? blockedReason(record, officer, candidate.decision) : null;
  const ready = Boolean(record && officer && !view.loading && !view.error && !block);
  const againstRecommendation = record && candidate.decision !== 'Escalated' && ['Approved', 'Rejected'].includes(record.decision) && record.decision !== candidate.decision;

  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="decision-confirmation-title" aria-describedby="decision-confirmation-description"
    onCancel={event => { event.preventDefault(); if (!submitting) onCancel(); }} onKeyDown={containDialogFocus}>
    <div className="flex max-h-[85dvh] min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-200 px-5 py-5 sm:px-7">
        <p className="mb-1 text-xs font-semibold tracking-wide text-slate-500 uppercase">Case #{candidate.applicationId} · Final check</p>
        <h2 ref={heading} tabIndex={-1} id="decision-confirmation-title" className="text-xl font-bold text-slate-900 outline-none">{action.title}</h2>
        <p id="decision-confirmation-description" className="mt-2 text-sm text-slate-600">Check the saved case and your reason before recording this action.</p>
      </header>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-5 py-5 sm:px-7" aria-busy={view.loading || submitting}>
        {view.loading ? <LoadingState label="Checking current case and your authority…" /> : view.error ? <ErrorState message={view.error} onRetry={() => setRevision(value => value + 1)} /> : record ? <div className="space-y-4">
          <div><p className="break-words text-lg font-bold text-slate-900">{record.business_name}</p><p className="mt-1 break-words text-sm text-slate-600">{record.applicant_name}</p></div>
          <dl className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm sm:grid-cols-2">
            <Detail label="Requested amount">{formatPKRExact(record.loan_amount_pkr)}</Detail>
            <Detail label="Term">{record.tenure_months} months</Detail>
            <Detail label="Borrower reference">{record.borrower_public_id || 'Not recorded'}</Detail>
            <Detail label="Current status">{record.decision_status}</Detail>
            <Detail label="Policy recommendation">{recommendationLabel(record.decision)}</Detail>
            <Detail label="Recorded policy">{record.policy?.policy_name || 'Not recorded'}{record.policy?.policy_version ? ` v${record.policy.policy_version}` : ''}</Detail>
            <Detail label="Signed-in officer">{officer.username} · {officer.role}</Detail>
            <Detail label="Your intended action">{action.result}</Detail>
          </dl>
          {block ? <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{block}</p> : <p className="rounded-xl border border-slate-200 p-4 text-sm text-slate-700">{candidate.decision === 'Escalated' ? 'This records an escalation for an admin to decide. It does not approve or reject the application.' : 'This records your final credit decision with your name and time. A recorded decision cannot be changed afterwards.'}</p>}
          {againstRecommendation ? <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-medium text-amber-900">Your decision is against the policy recommendation. Make sure the reason below explains your judgement.</p> : null}
          <div><h3 className="text-sm font-semibold text-slate-900">Reason that will be recorded</h3><p className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-slate-200 p-4 text-sm text-slate-700" data-testid="decision-reason-preview">{candidate.note}</p></div>
          <p className="text-xs leading-relaxed text-slate-500">Checked {formatDateTime(view.checkedAt)}. The server checks the case and your authority again when saving. Another officer may act in the meantime.</p>
          <button type="button" className="btn-ghost text-xs" disabled={submitting} onClick={() => setRevision(value => value + 1)}>Refresh details</button>
        </div> : null}
      </div>
      <footer className="flex shrink-0 flex-wrap gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-7">
        <button type="button" className="btn-secondary" disabled={submitting} onClick={onCancel}>{block ? 'Close and inspect current record' : 'Back to reason'}</button>
        <button type="button" className={`btn ${action.style}`} disabled={!ready || submitting} onClick={() => { if (ready && !submitting) onConfirm(candidate); }}>{submitting ? <Spinner className="h-4 w-4 text-white" /> : null}{submitting ? 'Recording action…' : action.confirm}</button>
        {submitting ? <p role="status" className="w-full text-xs text-slate-600">Wait for the result. This action will not be retried automatically.</p> : null}
      </footer>
    </div>
  </dialog>;
}

function Detail({ label, children }) {
  return <div className="min-w-0"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words font-semibold text-slate-900">{children}</dd></div>;
}
