import { useEffect, useRef, useState } from 'react';
import { activatePolicyVersion, apiErrorMessage, createPolicyVersion, fetchMe, fetchPolicyVersions } from '../api/client.js';
import { updateStoredAccount } from '../api/auth.js';
import { checkedPolicyVersions, illustratedRecommendation, policyReviewBlock, POLICY_TERMS, validPolicyTerms } from '../lib/policyReview.js';
import { containDialogFocus } from '../lib/dialogFocus.js';
import { formatDateTime, formatPKR } from '../lib/format.js';
import { useUnsavedWork } from './UnsavedWork.jsx';
import { ErrorState, LoadingState } from './common/States.jsx';

const LABELS = { decline_max_score:'Recommend Decline at or below', manual_review_max_score:'Recommend Manual Review up to',
  manager_approval_limit_pkr:'Manager approval limit', decline_override_admin_only:'Approve against Decline recommendation' };
const termValue = (policy, key) => key === 'manager_approval_limit_pkr' ? formatPKR(policy[key]) :
  key === 'decline_override_admin_only' ? policy[key] ? 'Admin only' : 'Manager or admin, within the amount limit' : String(policy[key]);

export default function PolicyReviewDialog({ candidate, onClose, onSaved }) {
  const dialog=useRef(null), heading=useRef(null), saving=useRef(false);
  const [view,setView]=useState({loading:true}), [revision,setRevision]=useState(0);
  const [reason,setReason]=useState(''), [confirm,setConfirm]=useState(false), [score,setScore]=useState('72');
  const [busy,setBusy]=useState(false), [error,setError]=useState(null), [stale,setStale]=useState(false);
  const compare=candidate.mode==='compare', create=candidate.mode==='create';
  useUnsavedWork({label:create?'Policy draft review':'Policy activation review',dirty:!compare,busy});
  useEffect(()=>{
    const previous=document.activeElement, element=dialog.current;
    element.showModal(); heading.current.focus({preventScroll:true});
    return ()=>{element.close();if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[]);
  useEffect(()=>{
    const controller=new AbortController(); setView({loading:true});setConfirm(false);setStale(false);setError(null);
    Promise.all([fetchPolicyVersions({signal:controller.signal}),fetchMe({signal:controller.signal})]).then(([data,actor])=>{
      if(controller.signal.aborted)return;
      const versions=checkedPolicyVersions(data);
      if(!actor || typeof actor.username!=='string' || !['admin','manager','analyst'].includes(actor.role)) throw Object.assign(new Error('Your current officer account could not be verified.'),{code:'INVALID_POLICY_ACCOUNT'});
      updateStoredAccount(actor);setView({loading:false,versions,actor,checkedAt:new Date().toISOString()});
    }).catch(err=>{if(!controller.signal.aborted)setView({loading:false,error:err.code?.startsWith('INVALID_POLICY_')?err.message:apiErrorMessage(err,'Could not verify current policy and account.')});});
    return ()=>controller.abort();
  },[revision]);
  const active=view.versions?.find(policy=>policy.is_active);
  const target=create?candidate.policy:view.versions?.find(policy=>policy.id===candidate.policy.id);
  const block=view.versions?policyReviewBlock(candidate,view.versions,view.actor):null;
  const ready=Boolean(active&&target&&!view.loading&&!view.error&&!block&&!stale&&!busy);
  const changed=active&&target?POLICY_TERMS.filter(key=>active[key]!==target[key]):[];
  const submit=async event=>{
    event.preventDefault();if(!ready||compare||saving.current)return;
    if(!create&&!confirm){if(reason.trim().length<3)return;setConfirm(true);heading.current.focus();return;}
    saving.current=true;setBusy(true);setError(null);
    try {
      const result=create?await createPolicyVersion(candidate.policy):await activatePolicyVersion(target.id,{expected_active_id:active.id,reason:reason.trim()});
      if(!validPolicyTerms(result)||!Number.isSafeInteger(result.id)||result.version!==target.version||
        POLICY_TERMS.some(key=>result[key]!==target[key])||(create?result.status!=='draft':result.id!==target.id||!result.is_active)) {
        throw Object.assign(new Error('The save response could not be verified. Refresh and inspect the versions before doing anything else.'),{code:'INVALID_POLICY_SAVE'});
      }
      onSaved(result,candidate.mode);
    } catch(err) {setError(err.code?.startsWith('INVALID_POLICY_')?err.message:apiErrorMessage(err,'Could not verify the policy change.'));setStale(true);}
    finally {saving.current=false;setBusy(false);}
  };
  const title=compare?'Compare policy versions':create?'Review policy draft':confirm?'Confirm policy activation':'Review policy activation';
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="policy-review-title" aria-describedby="policy-review-description" onKeyDown={containDialogFocus}
    onCancel={event=>{event.preventDefault();if(!saving.current)onClose();}}>
    <form noValidate onSubmit={submit} className="flex max-h-[85dvh] min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-200 px-5 py-5 sm:px-7"><h2 ref={heading} tabIndex={-1} id="policy-review-title" className="text-xl font-bold text-slate-900 outline-none">{title}</h2><p id="policy-review-description" className="mt-2 text-sm text-slate-600">{compare?'A read-only comparison. No saved case is rescored.':create?'Check the immutable draft before saving. Saving a draft does not activate it.':'Check the replacement policy, the approval rules and your reason before activation.'}</p></header>
      <div className="min-h-0 space-y-4 overflow-y-auto overscroll-contain px-5 py-5 sm:px-7" aria-busy={view.loading||busy}>
        {view.loading?<LoadingState label="Checking current versions and your authority…"/>:view.error?<ErrorState message={view.error} onRetry={()=>setRevision(v=>v+1)}/>:active&&target?<>
          <div className="grid min-w-0 gap-3 sm:grid-cols-2"><Identity title="Currently active" policy={active}/><Identity title={create?'Proposed draft':'Selected version'} policy={target}/></div>
          <p className="text-sm font-semibold text-slate-800">{changed.length?`${changed.length} policy ${changed.length===1?'term differs':'terms differ'} from the active version.`:'The four policy terms match the active version.'}</p>
          <dl className="space-y-3">{POLICY_TERMS.map(key=><div key={key} className={`rounded-xl border p-3 ${changed.includes(key)?'border-amber-200 bg-amber-50':'border-slate-200'}`}><dt className="text-sm font-semibold text-slate-900">{LABELS[key]}{changed.includes(key)?<span className="ml-2 text-xs font-normal text-amber-900">Changed</span>:null}</dt><dd className="mt-2 grid gap-2 text-sm sm:grid-cols-2"><div><span className="block text-xs text-slate-500">Active</span>{termValue(active,key)}</div><div><span className="block text-xs text-slate-500">Selected</span>{termValue(target,key)}</div></dd></div>)}</dl>
          {target.description?<div className="text-sm"><h3 className="font-semibold">Description</h3><p className="mt-1 whitespace-pre-wrap break-words text-slate-600">{target.description}</p></div>:null}
          <section className="rounded-xl border border-slate-200 p-4" aria-label="Illustrate score boundaries"><label className="field-label" htmlFor="policy-example-score">Illustrative score (0–100)</label><input id="policy-example-score" className="field-input" type="number" min="0" max="100" step="any" value={score} onChange={event=>setScore(event.target.value)} disabled={busy}/><div role="status" className="mt-3 space-y-1 text-sm"><p>Active: <strong>{illustratedRecommendation(score,active)||'Enter a valid score'}</strong></p><p>Selected: <strong>{illustratedRecommendation(score,target)||'Enter a valid score'}</strong></p></div><p className="mt-3 text-xs leading-relaxed text-slate-500">Illustration of configured boundaries only. It does not call the model, assess a borrower, estimate future defaults or validate lending thresholds.</p></section>
          <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">{create?'This saves an inactive draft. A separate reviewed activation is required.':'Activation changes the policy used for new assessments only. Saved assessments retain their original policy and approval rules; they are not recalculated.'}</p>
          {candidate.mode==='activate'&&!block?<div>{confirm?<><h3 className="text-sm font-semibold">Reason recorded in audit history</h3><p className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-sm">{reason.trim()}</p></>:<><label className="field-label" htmlFor="policy-activation-reason">Reason for activation</label><textarea id="policy-activation-reason" className="field-input" rows={3} minLength={3} maxLength={300} required value={reason} onChange={event=>setReason(event.target.value)} disabled={busy}/><p className="mt-1 text-xs text-slate-500">3–300 characters. Do not include customer details, passwords or private case evidence.</p></>}</div>:null}
          {block?<p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-950">{block}</p>:null}
          <p className="text-xs text-slate-500">Checked {formatDateTime(view.checkedAt)} · {view.actor.username} · {view.actor.role}. The server checks current admin authority again when activating and refuses if the active policy differs from this review.</p>
          {error?<p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{error} Refresh the comparison and inspect current records before another attempt.</p>:null}
          <button type="button" className="btn-secondary text-xs" disabled={busy} onClick={()=>setRevision(v=>v+1)}>Refresh comparison</button>
        </>:block?<p role="alert">{block}</p>:<p role="alert">The selected version could not be verified. Close and refresh the versions.</p>}
      </div>
      <footer className="flex shrink-0 flex-wrap gap-3 border-t border-slate-200 bg-slate-50 px-5 py-4 sm:px-7"><button type="button" className="btn-secondary" disabled={busy} onClick={onClose}>{compare?'Close':'Back without saving'}</button>{confirm?<button type="button" className="btn-secondary" disabled={busy} onClick={()=>setConfirm(false)}>Edit reason</button>:null}{!compare?<button type="submit" className="btn-primary" disabled={!ready||(!create&&reason.trim().length<3)}>{busy?'Saving…':create?'Save reviewed draft':confirm?'Confirm activation':'Review activation'}</button>:null}{busy?<p role="status" className="w-full text-xs text-slate-600">Wait for the result. This request is not retried automatically.</p>:null}</footer>
    </form>
  </dialog>;
}
function Identity({title,policy}) {return <div className="min-w-0 rounded-xl bg-slate-50 p-3"><p className="text-xs text-slate-500">{title}</p><p className="mt-1 break-words font-semibold">{policy.name} v{policy.version}</p><p className="mt-1 text-xs text-slate-500">{policy.status||'Unsaved draft'}</p></div>;}
