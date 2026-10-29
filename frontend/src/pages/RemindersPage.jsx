import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from 'react-router-dom';

import { apiErrorMessage, fetchReminders } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States.jsx";
import { formatDate, formatDateTime, formatPKRExact } from "../lib/format.js";
import ReminderReview from '../components/ReminderReview.jsx';
import { filterReminders, readReminderFilters, reminderFilterQuery, validReminders, REMINDER_KINDS as KIND } from '../lib/reminderReview.js';

/**
 * Payment reminders for approved facilities: installments past due, due within
 * a week, or unpaid from earlier months. ForiFlow drafts the message; the
 * officer copies it or opens it in WhatsApp and sends it themselves.
 */
export default function RemindersPage() {
  const [reminders, setReminders] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [language, setLanguage] = useState("ur");
  const [params,setParams]=useSearchParams(),filters=readReminderFilters(params);
  const [candidate,setCandidate]=useState(null),[checkedAt,setCheckedAt]=useState(null);
  const [revision,setRevision]=useState(0);
  const requestSequence=useRef(0);
  const update=changes=>setParams(current=>{
    const next=new URLSearchParams(current);
    for(const [key,value] of Object.entries(changes)){if(!value||value==='all')next.delete(key);else next.set(key,value);}
    return next;
  },{replace:true});

  useEffect(() => {
    const controller=new AbortController(),request=++requestSequence.current;
    setIsLoading(true);
    setError(null);
    fetchReminders({signal:controller.signal}).then(rows=>{
      if(controller.signal.aborted||request!==requestSequence.current)return;
      if(!validReminders(rows))throw Object.assign(new Error('Invalid reminders'),{code:'INVALID_REMINDERS'});
      setReminders(rows);setCheckedAt(new Date().toISOString());
    }).catch(failure=>{if(!controller.signal.aborted&&request===requestSequence.current)setError(failure.code==='INVALID_REMINDERS'?'The returned reminders could not be verified. Refresh the list.':apiErrorMessage(failure,'Could not load the reminders.'));})
      .finally(()=>{if(!controller.signal.aborted&&request===requestSequence.current)setIsLoading(false);});
    return()=>controller.abort();
  },[revision]);
  const reconciled=useCallback((rows,time)=>{setReminders(rows);setCheckedAt(time);setError(null);},[]);
  const visible=filterReminders(reminders,filters);
  const returnState={reminderSearch:reminderFilterQuery(filters)};

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Payment reminders</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Principal-only installments that are overdue, due within 7 days, or unpaid
            in recorded months. The first month without an EWS record is checked;
            later records do not clear earlier missing months. ForiFlow drafts the message. You send it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Message in</span>
          {[
            ["ur", "Roman Urdu"],
            ["en", "English"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setLanguage(value)}
              aria-pressed={language === value}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
                language === value
                  ? "border-brand-600 bg-brand-600 text-white"
                  : "border-slate-300 text-slate-600 hover:border-brand-400"
              }`}
            >
              {label}
            </button>
          ))}
          <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={()=>setRevision(value=>value+1)}>
            Refresh
          </button>
        </div>
      </header>

      <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        Indicative schedule: monthly from the recorded approval date in Pakistan time (PKT), with interest
        and fees excluded. Verify the agreed dates, actual amount due and payment
        receipts before sending. An EWS record alone does not prove payment.
      </p>

      <section className="card space-y-4 p-5" aria-label="Find a reminder">
        <div className="grid gap-3 md:grid-cols-3"><div><label htmlFor="reminder-search" className="field-label">Find a case</label><input id="reminder-search" type="search" className="field-input" value={filters.search} maxLength={100} placeholder="Business, applicant or exact case #" onChange={event=>update({search:event.target.value})}/></div><div><label htmlFor="reminder-kind" className="field-label">Reminder type</label><select id="reminder-kind" className="field-input" value={filters.kind} onChange={event=>update({kind:event.target.value})}><option value="all">All types</option>{Object.entries(KIND).map(([value,item])=><option key={value} value={value}>{item.label}</option>)}</select></div><div><label htmlFor="reminder-coverage" className="field-label">Record checks</label><select id="reminder-coverage" className="field-input" value={filters.coverage} onChange={event=>update({coverage:event.target.value})}><option value="all">All records</option><option value="gap">Missing monitoring months</option><option value="unknown">Unknown payment amounts</option><option value="no_contact">No usable contact number</option></select></div></div>
        <div className="flex flex-wrap items-center justify-between gap-3"><p role="status" className="text-xs text-slate-600">{isLoading?'Refreshing reminders…':error?'Reminder list unavailable':`${visible.length} of ${reminders.length} reminders`}{!isLoading&&!error&&checkedAt?` · Checked ${formatDateTime(checkedAt)}`:''}</p>{filters.search||filters.kind!=='all'||filters.coverage!=='all'?<button type="button" className="btn-ghost text-xs" onClick={()=>setParams({})}>Clear filters</button>:null}</div>
        <p className="text-xs text-slate-500">Review a draft to recheck the latest record before copying or opening WhatsApp. Filters stay in the URL when you return.</p>
      </section>

      {isLoading ? (
        <LoadingState label="Loading reminders…" />
      ) : error ? (
        <ErrorState message={error} onRetry={()=>setRevision(value=>value+1)} />
      ) : visible.length === 0 ? (
        <div className="card">
          <EmptyState
            title={reminders.length?'No reminders match these filters':'No reminders in the current list'}
            description={reminders.length?'Try another case, type or record check, or clear the filters.':'No approved facility currently meets the reminder rules. This does not prove every payment has been received.'}
          />
        </div>
      ) : (
        <ul className="space-y-4">
          {visible.map((reminder) => {
            const kind = KIND[reminder.kind];
            return (
              <li key={reminder.application_id} className="card px-5 py-4" data-testid={`reminder-${reminder.application_id}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {reminder.business_name}
                      <span className="ml-2 font-normal text-slate-500">
                        {reminder.applicant_name} · App #{reminder.application_id}
                      </span>
                    </p>
                    <p className="tabular mt-0.5 text-xs text-slate-500">
                      {reminder.installment_number
                        ? `Principal installment ${reminder.installment_number} of ${formatPKRExact(
                            reminder.installment_pkr,
                          )}, due ${formatDate(reminder.due_date)}`
                        : `Principal installment ${formatPKRExact(reminder.installment_pkr)}`}
                      {reminder.days_until_due !== null
                        ? reminder.days_until_due < 0
                          ? ` · ${-reminder.days_until_due} days late`
                          : ` · in ${reminder.days_until_due} days`
                        : ""}
                      {reminder.arrears_pkr > 0
                        ? ` · ${formatPKRExact(reminder.arrears_pkr)} unpaid in recorded months`
                        : ""}
                    </p>
                  </div>
                  <span className={`badge ${kind.className}`}>{kind.label}</span>
                </div>

                {reminder.has_recording_gap ? (
                  <p className="mt-3 text-sm font-medium text-amber-800">
                    Missing month {reminder.installment_number}: later EWS records exist
                    up to month {reminder.latest_recorded_month}. Check the gap and
                    payment receipts before sending.
                  </p>
                ) : null}
                {reminder.recorded_months_without_amount > 0 ? (
                  <p className="mt-2 text-xs text-slate-600">
                    {reminder.recorded_months_without_amount} recorded month(s) have no
                    payment amount. Those amounts are unknown and excluded from arrears.
                  </p>
                ) : null}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="btn-secondary px-3 py-1.5 text-xs"
                    onClick={() => setCandidate(reminder)}
                    aria-label={`Review draft for case ${reminder.application_id}`}
                  >
                    Review draft
                  </button>
                  <Link className="btn-secondary text-xs" to={`/alerts?facility=${reminder.application_id}`} state={returnState}>Open monitoring</Link>
                  <Link className="btn-ghost text-xs" to={`/shap/${reminder.application_id}`} state={returnState}>View case</Link>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {candidate?<ReminderReview candidate={candidate} language={language} onLanguage={setLanguage} onClose={()=>setCandidate(null)} onRefreshed={reconciled} returnState={returnState}/>:null}
    </div>
  );
}
