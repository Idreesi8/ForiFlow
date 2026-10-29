import { useEffect, useRef, useState } from 'react';
import { apiErrorMessage, fetchMe, fetchUsers, fetchUserAccessHistory, setUserRole, setUserStatus } from '../api/client.js';
import { updateStoredAccount } from '../api/auth.js';
import { containDialogFocus } from '../lib/dialogFocus.js';
import { roleLabel, TEAM_ROLES, teamChangeBlock } from '../lib/teamAccess.js';
import { formatDateTime } from '../lib/format.js';
import { useUnsavedWork } from './UnsavedWork.jsx';
import { ErrorState, LoadingState } from './common/States.jsx';

const eventLabels = { 'user.created':'Account created', 'user.role_changed':'Role changed', 'user.enabled':'Account re-enabled', 'user.disabled':'Account disabled' };

export default function TeamAccessDialog({ candidate, onClose, onSaved }) {
  const dialog = useRef(null), heading = useRef(null), saving = useRef(false);
  const [view, setView] = useState({ loading:true }), [revision, setRevision] = useState(0);
  const [role, setRole] = useState(candidate.user.role), [reason, setReason] = useState('');
  const [review, setReview] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(null);
  const history = candidate.mode === 'history';
  useUnsavedWork({ label:'Account access change', dirty:!history, busy });
  useEffect(() => {
    const previous = document.activeElement, element = dialog.current;
    element.showModal(); heading.current.focus({preventScroll:true});
    return () => { element.close(); if (previous?.isConnected) previous.focus({preventScroll:true}); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setView({loading:true}); setReview(false); setError(null);
    Promise.all([fetchMe({signal:controller.signal}), fetchUsers({signal:controller.signal}),
      history ? fetchUserAccessHistory(candidate.user.id,{signal:controller.signal}) : Promise.resolve([])])
      .then(([actor, users, events]) => {
        if (controller.signal.aborted) return;
        updateStoredAccount(actor);
        const user = users.find(item => item.id === candidate.user.id);
        setView({loading:false,actor,user,events}); if (user) setRole(user.role);
      }).catch(err => {if(!controller.signal.aborted) setView({loading:false,error:apiErrorMessage(err,'Could not verify current account access.')});});
    return () => controller.abort();
  }, [candidate.user.id, history, revision]);
  const user = view.user, block = !view.loading && !view.error ? teamChangeBlock(user,view.actor,candidate.mode) : null;
  const changed = candidate.mode === 'role' ? role !== user?.role : true;
  const ready = Boolean(user && !block && !view.loading && !view.error && changed && reason.trim().length >= 3);
  const submit = async event => {
    event.preventDefault(); if (!ready || saving.current) return;
    if (!review) {setReview(true); heading.current.focus(); return;}
    saving.current = true; setBusy(true); setError(null);
    try {
      const updated = candidate.mode === 'role'
        ? await setUserRole(user.id,role,user.role,reason.trim())
        : await setUserStatus(user.id,!user.is_active,reason.trim(),user.is_active);
      onSaved(updated, candidate.mode);
    } catch (err) {setError(apiErrorMessage(err,'Could not save the access change. Refresh the account before trying again.'));}
    finally {saving.current=false;setBusy(false);}
  };
  const title = history ? 'Access history' : review ? 'Review access change' : candidate.mode === 'role' ? 'Change account role' : user?.is_active === false ? 'Re-enable account' : 'Disable account';
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="team-access-title" onKeyDown={containDialogFocus}
    onCancel={event=>{event.preventDefault();if(!saving.current)onClose();}}>
    <form onSubmit={submit} className="flex max-h-[85dvh] min-h-0 flex-col">
      <header className="border-b border-slate-200 px-5 py-5 sm:px-7"><p className="mb-1 break-all text-xs font-semibold text-slate-500">{candidate.user.username}</p><h2 id="team-access-title" ref={heading} tabIndex={-1} className="text-xl font-bold text-slate-900 outline-none">{title}</h2></header>
      <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5 sm:px-7" aria-busy={view.loading||busy}>
        {view.loading ? <LoadingState label="Checking current account and your authority…"/> : view.error ? <ErrorState message={view.error} onRetry={()=>setRevision(v=>v+1)}/> : block ? <p role="alert" className="text-sm text-amber-900">{block}</p> : user ? <>
          <div className="rounded-lg bg-slate-50 p-3 text-sm"><strong>{roleLabel(user.role)}</strong> · {user.is_active ? 'Enabled':'Disabled'}</div>
          {history ? <><p className="text-xs text-slate-500">Latest 50 recorded creation, role and status changes. Sign-ins are excluded. Older or seeded accounts may have no recorded creation event.</p>{view.events.length ? <ol className="space-y-3">{view.events.map(event=><li key={event.id} className="rounded-lg border border-slate-200 p-3 text-sm"><p className="font-semibold text-slate-900">{eventLabels[event.action] ?? event.action}</p><p className="mt-1 text-xs text-slate-500">{formatDateTime(event.occurred_at)} · by {event.username}</p>{event.action==='user.role_changed' ? <p className="mt-2">{roleLabel(event.previous_state?.role)} → {roleLabel(event.new_state?.role)}</p> : null}{event.details?.reason ? <p className="mt-2 break-words">Reason: {event.details.reason}</p> : null}</li>)}</ol> : <p className="text-sm text-slate-600">No account access changes are recorded.</p>}</> : <>
          {candidate.mode==='role' ? <div>{review ? <p className="text-base font-semibold">{roleLabel(user.role)} → {roleLabel(role)}</p> : <><label className="field-label" htmlFor="team-new-role">New role</label><select id="team-new-role" className="field-input" value={role} onChange={event=>setRole(event.target.value)}>{TEAM_ROLES.map(item=><option key={item.value} value={item.value}>{item.label}</option>)}</select></>}<p className="mt-2 text-sm text-slate-600">{TEAM_ROLES.find(item=>item.value===role)?.can}</p><p className="mt-3 text-sm text-slate-700">The new authority applies on the next API request, including existing sessions. Menus refresh on navigation, return to the tab or the periodic account check.</p>{!user.is_active ? <p className="mt-2 text-sm text-amber-900">This account stays disabled. Changing its role does not re-enable sign-in.</p> : null}</div> : <div><p className="font-semibold">{user.is_active ? 'Enabled → Disabled':'Disabled → Enabled'}</p><p className="mt-2 text-sm text-slate-700">{user.is_active ? 'Sign-in and existing sessions will be refused on the next request. Saved work stays on file.' : `This officer can sign in again with ${roleLabel(user.role)} access. Previously revoked sessions stay revoked.`}</p></div>}
          {review ? <div className="rounded-lg border border-brand-200 bg-brand-50 p-3 text-sm"><p className="font-semibold">Reason recorded in audit history</p><p className="mt-2 whitespace-pre-wrap break-words">{reason.trim()}</p><p className="mt-3 text-xs">Changing account access does not alter past assessments or decisions. The admin, time, previous value and new value are recorded.</p></div> : <div><label className="field-label" htmlFor="team-change-reason">Reason for this change</label><textarea id="team-change-reason" className="field-input" rows={3} value={reason} maxLength={300} onChange={event=>setReason(event.target.value)} required minLength={3}/><p className="mt-1 text-xs text-slate-500">3–300 characters. Do not include passwords or private case details.</p></div>}
          {error ? <div role="alert" className="space-y-2 rounded-lg bg-rose-50 p-3 text-sm text-rose-900"><p>{error}</p><button type="button" className="btn-secondary text-xs" disabled={busy} onClick={()=>setRevision(v=>v+1)}>Refresh account and review again</button></div> : null}
          </>}
        </> : null}
      </div>
      <footer className="flex flex-wrap gap-3 border-t border-slate-200 px-5 py-4 sm:px-7"><button type="button" className="btn-secondary" disabled={busy} onClick={onClose}>{history?'Close':'Cancel'}</button>{!history&&review ? <button type="button" className="btn-secondary" disabled={busy} onClick={()=>{setReview(false);setError(null);}}>Edit change</button> : null}{!history ? <button type="submit" className="btn-primary" disabled={!ready||busy}>{busy?'Saving…':review?'Confirm access change':'Review change'}</button> : null}</footer>
    </form>
  </dialog>;
}
