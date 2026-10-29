import { useEffect, useRef, useState } from 'react';
import { canManageTeam } from '../api/auth.js';
import { apiErrorMessage, fetchPolicyVersions } from '../api/client.js';
import PolicyReviewDialog from '../components/PolicyReviewDialog.jsx';
import { useUnsavedWork } from '../components/UnsavedWork.jsx';
import { ErrorState, LoadingState } from '../components/common/States.jsx';
import { checkedPolicyVersions, policyDraftFrom, preparePolicyDraft } from '../lib/policyReview.js';
import { describeBands } from '../lib/policyBands.js';
import { formatCount, formatDateTime, formatPKR } from '../lib/format.js';
import { refreshActivePolicy } from '../lib/useActivePolicy.js';

const TONES={active:'bg-emerald-100 text-emerald-800',draft:'bg-slate-100 text-slate-700',retired:'bg-amber-50 text-amber-900'};

export default function PolicyPage() {
  const isAdmin=canManageTeam(), seed=useRef(null), draftHeading=useRef(null);
  const [view,setView]=useState({loading:true,versions:null,error:null}), [revision,setRevision]=useState(0);
  const [form,setForm]=useState(null), [review,setReview]=useState(null), [error,setError]=useState(null);
  const [saved,setSaved]=useState(null), [resetRequested,setResetRequested]=useState(false);
  const dirty=Boolean(form&&JSON.stringify(form)!==JSON.stringify(seed.current));
  useUnsavedWork({label:'Unsaved credit-policy draft',dirty});
  useEffect(()=>{
    const controller=new AbortController();setView(previous=>({...previous,loading:true,error:null}));
    fetchPolicyVersions({signal:controller.signal}).then(data=>{
      if(!controller.signal.aborted)setView({loading:false,versions:checkedPolicyVersions(data),error:null});
    }).catch(err=>{if(!controller.signal.aborted)setView(previous=>({...previous,loading:false,error:err.code?.startsWith('INVALID_POLICY_')?err.message:apiErrorMessage(err,'Could not load the credit policy.')}));});
    return ()=>controller.abort();
  },[revision]);
  useEffect(()=>{
    if(!view.versions||view.error)return;
    if(!form||JSON.stringify(form)===JSON.stringify(seed.current)) {
      const next=policyDraftFrom(view.versions.find(policy=>policy.is_active));seed.current=next;setForm(next);
    }
  },[view.versions]);
  const active=view.versions?.find(policy=>policy.is_active), available=Boolean(active&&!view.loading&&!view.error);
  const change=(key,value)=>{setForm(previous=>({...previous,[key]:value}));setError(null);setSaved(null);};
  const reset=()=>{const next=policyDraftFrom(active);seed.current=next;setForm(next);setResetRequested(false);setError(null);};
  const prepare=event=>{
    event.preventDefault();setError(null);setSaved(null);
    try {setReview({mode:'create',policy:preparePolicyDraft(form)});}catch(err){setError(err.message);draftHeading.current?.focus();}
  };
  const onSaved=(policy,mode)=>{
    setReview(null);setSaved(mode==='create'?`Draft v${policy.version} saved. It is not active.`:`Policy v${policy.version} is now active for new assessments. Saved cases keep their original policy.`);
    if(mode==='create'){setForm(null);setResetRequested(false);}
    if(mode==='activate')refreshActivePolicy();setRevision(v=>v+1);
  };
  if(!view.versions)return view.error?<ErrorState message={view.error} onRetry={()=>setRevision(v=>v+1)}/>:<LoadingState label="Loading credit policy…"/>;
  return <div className="min-w-0 space-y-6">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-xl font-bold text-slate-900">Credit policy</h2><p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">Compare the score boundaries and approval rules before saving or activating a version. The model assesses risk; policy gives a recommendation; an authorised officer makes the decision.</p></div><button type="button" className="btn-secondary text-xs" disabled={view.loading} onClick={()=>setRevision(v=>v+1)}>{view.loading?'Refreshing…':'Refresh versions'}</button></header>
    {saved?<p role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-950">{saved}</p>:null}
    {view.error?<div role="alert"><ErrorState message={view.error} onRetry={()=>setRevision(v=>v+1)}/><p className="text-sm text-amber-900">Previously loaded versions are shown below. Refresh successfully before making a change.</p></div>:null}
    {active?<section className="card p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="card-title break-words">In force: {active.name} v{active.version}</h3><span className={`badge ${TONES.active}`}>active</span></div><p className="mt-4 text-sm font-semibold text-slate-900">{describeBands(active)}</p><dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2"><Detail label="Manager approval limit">{formatPKR(active.manager_approval_limit_pkr)}</Detail><Detail label="Approve against a Decline recommendation">{active.decline_override_admin_only?'Admin only':'Manager or admin, within the amount limit'}</Detail></dl><p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-950">{active.notice||'Configured lender thresholds. These are not validated Pakistani SME lending boundaries.'}</p></section>:null}
    <section className="space-y-3" aria-labelledby="policy-versions-title"><div className="flex flex-wrap items-center justify-between gap-2"><h3 id="policy-versions-title" className="font-bold text-slate-900">Policy versions</h3><p className="text-xs text-slate-500">Retained history · versions are never edited or deleted</p></div><div className="grid min-w-0 gap-4 xl:grid-cols-2">{view.versions.map(policy=><article key={policy.id} className="card min-w-0 p-5"><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><h4 className="break-words font-bold text-slate-900">v{policy.version} · {policy.name}</h4><p className="mt-2 text-xs leading-relaxed text-slate-500">Created {formatDateTime(policy.created_at)} · {policy.created_by}</p></div><span className={`badge ${TONES[policy.status]}`}>{policy.status}</span></div><p className="mt-4 text-sm text-slate-700">{describeBands(policy)}</p><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><Detail label="Manager limit">{formatPKR(policy.manager_approval_limit_pkr)}</Detail><Detail label="Assessments recorded under this version">{formatCount(policy.applications_assessed)}</Detail><Detail label="Approve against Decline">{policy.decline_override_admin_only?'Admin only':'Manager or admin, within limit'}</Detail>{policy.activated_at?<Detail label="Last activated">{formatDateTime(policy.activated_at)} · {policy.activated_by}</Detail>:null}</dl><div className="mt-5 flex flex-wrap gap-2"><button type="button" className="btn-secondary text-xs" disabled={!available} onClick={()=>setReview({mode:'compare',policy})} aria-label={`Compare policy v${policy.version}`}>Compare with active</button>{isAdmin&&!policy.is_active?<button type="button" className="btn-primary text-xs" disabled={!available} onClick={()=>setReview({mode:'activate',policy})} aria-label={`Review activation of policy v${policy.version}`}>Review activation</button>:null}</div></article>)}</div></section>
    {isAdmin&&form?<section className="card p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 ref={draftHeading} tabIndex={-1} className="card-title outline-none">New policy draft</h3><p className="mt-2 max-w-2xl text-sm text-slate-600">Starts with the active policy's terms. Give this version a new identity and describe the intended change. Figures can be edited until you save; a saved version cannot be edited.</p></div><button type="button" className="btn-secondary text-xs" disabled={!available} onClick={()=>dirty?setResetRequested(true):reset()}>Reset draft to active terms</button></div>
      {resetRequested?<div role="alert" className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm"><p>Replace your unsaved draft with current active terms and clear its name, version and description?</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary text-xs" onClick={()=>setResetRequested(false)}>Keep my entries</button><button type="button" className="btn-primary text-xs" disabled={!available} onClick={reset}>Replace draft entries</button></div></div>:null}
      <form onSubmit={prepare} className="mt-5 space-y-4"><fieldset disabled={!available} className="grid min-w-0 gap-4 border-0 p-0 sm:grid-cols-2"><Input label="Version" value={form.version} required maxLength={32} placeholder="e.g. 1.2" onChange={value=>change('version',value)}/><Input label="Name" value={form.name} required minLength={3} maxLength={120} placeholder="e.g. Pilot Credit Policy" onChange={value=>change('name',value)}/><Input label="Recommend Decline at or below" type="number" min="0" max="100" step="any" value={form.decline_max_score} required onChange={value=>change('decline_max_score',value)}/><Input label="Recommend Manual Review up to" type="number" min="0" max="100" step="any" value={form.manual_review_max_score} required onChange={value=>change('manual_review_max_score',value)}/><Input label="Manager approval limit (PKR)" type="number" min="0" max="500000000" step="any" value={form.manager_approval_limit_pkr} required onChange={value=>change('manager_approval_limit_pkr',value)}/><label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={form.decline_override_admin_only} onChange={event=>change('decline_override_admin_only',event.target.checked)}/>Only an admin may approve against a Decline recommendation</label><label className="block min-w-0 sm:col-span-2"><span className="field-label">Description of the change (optional)</span><textarea className="field-input" rows={3} maxLength={2000} value={form.description} onChange={event=>change('description',event.target.value)}/></label></fieldset>
        {error?<p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{error}</p>:null}<p className="text-xs leading-relaxed text-slate-500">A new draft changes no lending rules. Activation requires a separate comparison, reason and final confirmation. Unsaved entries stay only in this tab.</p><button type="submit" className="btn-primary" disabled={!available}>Review draft</button>
      </form></section>:!isAdmin?<p className="text-sm text-slate-500">Every officer can compare versions. Only an admin can create or activate a version.</p>:null}
    {review?<PolicyReviewDialog candidate={review} onClose={()=>setReview(null)} onSaved={onSaved}/>:null}
  </div>;
}
function Detail({label,children}){return <div className="min-w-0"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words font-semibold text-slate-900">{children}</dd></div>;}
function Input({label,onChange,...props}){return <label className="block min-w-0"><span className="field-label">{label}</span><input className="field-input" onChange={event=>onChange(event.target.value)} {...props}/></label>;}
