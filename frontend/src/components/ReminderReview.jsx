import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage, fetchReminders } from '../api/client.js';
import { containDialogFocus } from '../lib/dialogFocus.js';
import { formatDate, formatDateTime, formatPKRExact } from '../lib/format.js';
import { validReminders, whatsappDraftURL } from '../lib/reminderReview.js';
import { ErrorState, LoadingState } from './common/States.jsx';

export default function ReminderReview({candidate,language,onLanguage,onClose,onRefreshed,returnState}) {
  const dialog=useRef(null),heading=useRef(null),copySequence=useRef(0);
  const [revision,setRevision]=useState(0),[view,setView]=useState({loading:true}),[copyState,setCopyState]=useState(null);
  useEffect(()=>{
    const previous=document.activeElement,element=dialog.current;
    element.showModal();heading.current.focus({preventScroll:true});
    return()=>{element.close();if(previous?.isConnected)previous.focus({preventScroll:true});copySequence.current++;};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    copySequence.current++;setCopyState(null);setView({loading:true});
    fetchReminders({signal:controller.signal}).then(rows=>{
      if(controller.signal.aborted)return;
      if(!validReminders(rows))throw Object.assign(new Error('Invalid reminder response'),{code:'INVALID_REMINDERS'});
      const checkedAt=new Date().toISOString();
      onRefreshed(rows,checkedAt);
      setView({loading:false,reminder:rows.find(row=>row.application_id===candidate.application_id)??null,checkedAt});
    }).catch(error=>{if(!controller.signal.aborted)setView({loading:false,error:error.code==='INVALID_REMINDERS'?'The returned reminder details could not be verified. Refresh before using a draft.':apiErrorMessage(error,'Could not refresh the reminder.')});});
    return()=>controller.abort();
  },[candidate.application_id,revision,onRefreshed]);
  useEffect(()=>{copySequence.current++;setCopyState(null);},[language]);
  const row=view.reminder,message=row?(language==='ur'?row.message_ur:row.message_en):null;
  const url=row?whatsappDraftURL(row.contact_phone,message):null;
  const copy=async()=>{
    if(!message)return;
    const request=++copySequence.current;
    setCopyState({busy:true});
    try {await navigator.clipboard.writeText(message);if(request===copySequence.current)setCopyState({message:'Draft copied. Nothing has been sent.'});}
    catch {if(request===copySequence.current)setCopyState({error:'Could not copy the draft. Select the draft text and copy it manually.'});}
  };
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="reminder-review-title" onKeyDown={containDialogFocus} onCancel={event=>{event.preventDefault();onClose();}}>
    <div className="flex max-h-[85dvh] min-h-0 flex-col">
      <header className="shrink-0 border-b border-slate-200 px-5 py-5 sm:px-7"><p className="mb-1 text-xs font-semibold text-slate-500">Case #{candidate.application_id} · Draft only</p><h2 ref={heading} tabIndex={-1} id="reminder-review-title" className="text-xl font-bold text-slate-900 outline-none">Review reminder</h2></header>
      <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5 sm:px-7" aria-busy={view.loading}>
        {view.loading?<LoadingState label="Checking the latest reminder…"/>:view.error?<ErrorState message={view.error} onRetry={()=>setRevision(value=>value+1)}/>:!row?<div className="space-y-3"><h3 className="font-semibold text-slate-900">This reminder is no longer in the current list</h3><p className="text-sm text-slate-600">The record or schedule may have changed. This does not prove payment. Open monitoring to check the case; the previous draft is withheld.</p></div>:<>
          <div><h3 className="break-words text-lg font-bold text-slate-900">{row.business_name}</h3><p className="mt-1 text-sm text-slate-600">{row.applicant_name}</p><p className="mt-2 text-xs text-slate-500">Refreshed from ForiFlow: {formatDateTime(view.checkedAt)}. Payments or records can change after this check.</p></div>
          <dl className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm sm:grid-cols-2"><div><dt className="text-xs text-slate-500">Principal installment</dt><dd className="mt-1 font-semibold">{formatPKRExact(row.installment_pkr)}</dd></div><div><dt className="text-xs text-slate-500">Indicative due date</dt><dd className="mt-1 font-semibold">{row.due_date?formatDate(row.due_date):'Recorded arrears only'}</dd></div><div><dt className="text-xs text-slate-500">Unpaid in months with recorded amounts</dt><dd className="mt-1 font-semibold">{formatPKRExact(row.arrears_pkr)}</dd></div><div><dt className="text-xs text-slate-500">Current contact on file</dt><dd className="mt-1 break-all font-semibold">{row.contact_phone||'Not recorded'}</dd></div></dl>
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-950">Indicative principal-only schedule; interest and fees are excluded. Verify agreed dates, actual amount due and receipts before sending.{row.has_recording_gap?` Month ${row.installment_number} is missing even though later monitoring exists.`:''}{row.recorded_months_without_amount?` ${row.recorded_months_without_amount} recorded month(s) have unknown payment amounts, excluded from arrears.`:''}</div>
          <fieldset><legend className="mb-2 text-xs font-semibold text-slate-600">Draft language</legend><div className="flex gap-2">{[['ur','Roman Urdu'],['en','English']].map(([value,label])=><button type="button" key={value} className={language===value?'btn-primary text-xs':'btn-secondary text-xs'} aria-pressed={language===value} onClick={()=>onLanguage(value)}>{label}</button>)}</div></fieldset>
          <p className="whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-800" data-testid="reviewed-reminder-message">{message}</p>
          <div className="flex flex-wrap items-center gap-3"><button type="button" className="btn-primary" disabled={copyState?.busy} onClick={copy}>{copyState?.busy?'Copying…':'Copy reviewed draft'}</button>{url?<a className="btn-secondary" href={url} target="_blank" rel="noreferrer">Open WhatsApp draft</a>:<p className="text-xs text-slate-500">No usable international phone number is on file.</p>}</div>
          <p className="text-xs text-slate-500">Opening WhatsApp passes this text and recipient to WhatsApp. You decide whether to send. Copying or opening does not record a sent reminder.</p>
          {copyState?.message?<p role="status" className="text-sm text-brand-800">{copyState.message}</p>:null}{copyState?.error?<p role="alert" className="text-sm text-rose-800">{copyState.error}</p>:null}
        </>}
        {!view.loading?<div className="flex flex-wrap gap-3 border-t border-slate-200 pt-3 text-sm"><Link className="font-semibold text-brand-800 underline" to={`/alerts?facility=${candidate.application_id}`} state={returnState}>Open monitoring</Link><Link className="font-semibold text-brand-800 underline" to={`/shap/${candidate.application_id}`} state={returnState}>View case</Link></div>:null}
      </div>
      <footer className="flex shrink-0 flex-wrap gap-3 border-t border-slate-200 px-5 py-4 sm:px-7"><button type="button" className="btn-secondary" onClick={onClose}>Close</button><button type="button" className="btn-secondary" disabled={view.loading} onClick={()=>setRevision(value=>value+1)}>Refresh draft</button></footer>
    </div>
  </dialog>;
}
