import { useCallback, useEffect, useRef, useState } from 'react';
import { canDecideCredit } from '../api/auth.js';
import { apiErrorMessage, fetchRepaymentCalendar, recordRepaymentSchedule, recordRepaymentReceipt, voidRepaymentReceipt } from '../api/client.js';
import { formatDate } from '../lib/format.js';
import { monthlyItems, saveIntent, validCalendar } from '../lib/repaymentCalendar.js';
import { useBusinessDate } from '../hooks/useBusinessDate.js';
import { useUnsavedWork } from './UnsavedWork.jsx';
import { ErrorState, LoadingState } from './common/States.jsx';

const amount = value => `PKR ${Number(value).toLocaleString('en-PK', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const STATES = { overdue: 'Overdue', due_today: 'Due today', upcoming: 'Upcoming', paid: 'Paid' };
const blankAllocation = () => ({ installment: '', amount_pkr: '' });

export default function RepaymentCalendar({ applicationId, onDirtyChange, onBusyChange }) {
  const [data, setData] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [writeError, setWriteError] = useState('');
  const [editing, setEditing] = useState(false), [disbursed, setDisbursed] = useState(''), [firstDue, setFirstDue] = useState('');
  const [count, setCount] = useState('12'), [agreed, setAgreed] = useState(''), [items, setItems] = useState([]), [source, setSource] = useState('');
  const [paidOn, setPaidOn] = useState(''), [reference, setReference] = useState(''), [allocations, setAllocations] = useState([blankAllocation()]);
  const [voiding, setVoiding] = useState(null), [reason, setReason] = useState('');
  const [scheduleId, setScheduleId] = useState(null), [receiptOffset, setReceiptOffset] = useState(0);
  const sequence = useRef(0), controller = useRef(null), mounted = useRef(true), scheduleIntent = useRef(null), receiptIntent = useRef(null), saving = useRef(false);
  const today = useBusinessDate();
  const manager = canDecideCredit();
  const dirty = Boolean(disbursed || firstDue || agreed || items.length || source || paidOn || reference || allocations.some(a => a.installment || a.amount_pkr) || reason);
  useUnsavedWork({ dirty, busy, label: `Repayment calendar · App #${applicationId}` });
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange?.(busy); }, [busy, onBusyChange]);
  useEffect(() => () => { onDirtyChange?.(false); onBusyChange?.(false); }, [onDirtyChange, onBusyChange]);

  const accept = useCallback(report => {
    if (!validCalendar(report, applicationId)) throw new Error('The repayment response does not match this facility or its amounts. Reload before recording anything.');
    setData(report);
  }, [applicationId]);
  const load = useCallback(async () => {
    const request = ++sequence.current;
    controller.current?.abort(); controller.current = new AbortController();
    setLoading(true); setError(''); setData(null);
    try {
      const report = await fetchRepaymentCalendar(applicationId, { signal: controller.current.signal, scheduleId, receiptOffset });
      if (request === sequence.current) accept(report);
    } catch (e) { if (request === sequence.current && e.code !== 'ERR_CANCELED') setError(apiErrorMessage(e, e.message || 'Could not load repayment dates.')); }
    finally { if (request === sequence.current) setLoading(false); }
  }, [applicationId, accept, scheduleId, receiptOffset]);
  useEffect(() => {
    mounted.current = true; load();
    return () => { mounted.current = false; sequence.current += 1; controller.current?.abort(); };
  }, [load, today]);

  const write = async (operation, success, clear) => {
    if (saving.current) return;
    saving.current = true; setBusy(true); setWriteError(''); setMessage('');
    ++sequence.current; controller.current?.abort();
    try {
      const report = await operation();
      if (!mounted.current) return;
      accept(report); clear(); setMessage(success); setReceiptOffset(0); setScheduleId(null);
    } catch (e) {
      if (mounted.current) setWriteError(apiErrorMessage(e, e.message || 'Save could not be confirmed. Retry the same details to recover the original save.'));
    } finally { saving.current = false; if (mounted.current) setBusy(false); }
  };
  const saveSchedule = event => {
    event.preventDefault();
    const payload = { expected_schedule_id: data.schedule?.id ?? null, disbursed_on: disbursed, items, source_note: source };
    scheduleIntent.current = saveIntent(scheduleIntent.current, payload, () => crypto.randomUUID());
    write(() => recordRepaymentSchedule(applicationId, { ...payload, submission_key: scheduleIntent.current.key }),
      'Contract schedule recorded. Payment balances use these dates and agreed amounts.', () => {
        setEditing(false); setDisbursed(''); setFirstDue(''); setAgreed(''); setItems([]); setSource(''); scheduleIntent.current = null;
      });
  };
  const saveReceipt = event => {
    event.preventDefault();
    const payload = { expected_schedule_id: data.schedule.id, paid_on: paidOn, reference,
      allocations: allocations.map(a => ({ ...a, installment: Number(a.installment) })) };
    receiptIntent.current = saveIntent(receiptIntent.current, payload, () => crypto.randomUUID());
    write(() => recordRepaymentReceipt(applicationId, { ...payload, submission_key: receiptIntent.current.key }),
      'Payment receipt recorded with the selected allocations.', () => {
        setPaidOn(''); setReference(''); setAllocations([blankAllocation()]); receiptIntent.current = null;
      });
  };

  if (loading) return <LoadingState label="Loading repayment calendar…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data || data.application_id !== Number(applicationId)) return null;
  const scheduleForm = editing || !data.schedule;
  const updateAllocation = (index, field, value) => setAllocations(rows => rows.map((row, i) => i === index ? { ...row, [field]: value } : row));

  return <div className="border-t border-slate-200 px-5 py-5" aria-label="Repayment calendar">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="text-base font-semibold text-slate-900">Repayment calendar · App #{applicationId}</h3>
        <p className="mt-1 text-sm text-slate-600">Exact due dates and allocated payments · as of {formatDate(data.as_of_date)} (Pakistan)</p></div>
      <button type="button" className="btn-secondary" disabled={busy || dirty} onClick={load}>Reload calendar</button>
    </div>
    <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Officer-recorded evidence. Payments are not verified against a bank feed. Overdue amounts do not change the credit score, EWS alerts or regulatory loan classification.</p>
    {message && <p role="status" className="mt-3 text-sm text-emerald-800">{message}</p>}
    {writeError && <p role="alert" className="mt-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{writeError} If the response was lost, retry unchanged details before starting another entry.</p>}
    {data.schedule ? <>
      <Field label="Contract schedule version"><select className="field-input sm:max-w-sm" disabled={busy || dirty} value={data.schedule.id} onChange={e => { setScheduleId(Number(e.target.value)); setReceiptOffset(0); setWriteError(''); setMessage(''); }}>
        {data.schedule_versions.map(v => <option value={v.id} key={v.id}>Version {v.version}{v.id === data.current_schedule_id ? ' · current' : ' · superseded'} · {v.created_by}</option>)}
      </select></Field>
      {!data.schedule.is_current && <p role="status" className="mt-3 rounded-lg bg-slate-100 p-3 text-sm text-slate-700">Superseded schedule shown for reference. These figures are not the current payment demand. Select the current version to record payments.</p>}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Metric label="Scheduled amount still unpaid" value={amount(data.total_outstanding_pkr)} />
        <Metric label="Currently overdue" value={amount(data.overdue_pkr)} alert={data.maximum_days_past_due > 0} />
        <Metric label="Oldest unpaid due date" value={`${data.maximum_days_past_due} days overdue`} alert={data.maximum_days_past_due > 0} />
      </div>
      <p className="mt-3 text-xs text-slate-600 break-words">Schedule v{data.schedule.version} · disbursed {formatDate(data.schedule.disbursed_on)} · recorded by {data.schedule.created_by}. Source: {data.schedule.source_note}</p>
      <div className="mt-3 max-h-96 overflow-auto rounded-lg border border-slate-200" tabIndex={0} aria-label="Scheduled instalments">
        <table className="min-w-full text-left text-sm"><thead className="table-head"><tr>{['Instalment', 'Due', 'Scheduled', 'Paid', 'Unpaid', 'Status'].map(h => <th key={h} className="px-3 py-2">{h}</th>)}</tr></thead>
          <tbody>{data.installments.map(row => <tr key={row.installment} className="border-t border-slate-100"><td className="px-3 py-3">#{row.installment}</td><td className="whitespace-nowrap px-3">{formatDate(row.due_on)}</td>
            <td className="whitespace-nowrap px-3">{amount(row.amount_pkr)}</td><td className="whitespace-nowrap px-3">{amount(row.paid_pkr)}</td><td className="whitespace-nowrap px-3">{amount(row.outstanding_pkr)}</td>
            <td className={`whitespace-nowrap px-3 ${row.status === 'overdue' ? 'font-semibold text-rose-800' : 'text-slate-700'}`}>{STATES[row.status]}{row.days_past_due > 0 ? ` · ${row.days_past_due} days` : ''}{row.status === 'paid' && row.settled_late_days > 0 ? ` · settled ${row.settled_late_days} days late` : ''}</td></tr>)}</tbody></table>
      </div>
      {manager && !editing && data.schedule.is_current && <button className="btn-secondary mt-3" type="button" disabled={busy || !data.schedule.can_replace || dirty} onClick={() => {
        setEditing(true); setDisbursed(data.schedule.disbursed_on); setItems(data.installments.map(r => ({ due_on: r.due_on, amount_pkr: r.amount_pkr }))); setSource(data.schedule.source_note);
      }}>Replace schedule with a new version</button>}
      {data.schedule.is_current && !data.schedule.can_replace && <p className="mt-2 text-xs text-slate-600">Schedule replacement is blocked while receipts are active. A manager can void an incorrect receipt below; the history is retained.</p>}
    </> : <p className="mt-4 text-sm text-slate-700">No agreed repayment dates are recorded. Approval date and principal-only estimates are not used as a repayment contract.</p>}

    {scheduleForm && manager && <form onSubmit={saveSchedule} className="mt-5 rounded-lg border border-slate-200 p-4">
      <fieldset disabled={busy}><legend className="font-semibold text-slate-900">{data.schedule ? 'Record replacement contract schedule' : 'Record agreed contract schedule'}</legend>
        <p className="mt-1 text-xs text-slate-600">Copy dates and amounts from the agreement. Monthly rows are a draft you review; interest is not calculated here.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Actual disbursement date"><input className="field-input" type="date" required max={data.as_of_date} value={disbursed} onChange={e => setDisbursed(e.target.value)} /></Field>
          <Field label="First agreed due date"><input className="field-input" type="date" value={firstDue} onChange={e => setFirstDue(e.target.value)} /></Field>
          <Field label="Number of monthly instalments"><input className="field-input" type="number" min="1" max="120" step="1" value={count} onChange={e => setCount(e.target.value)} /></Field>
          <Field label="Agreed instalment amount (PKR)"><input className="field-input" inputMode="decimal" value={agreed} onChange={e => setAgreed(e.target.value)} /></Field>
        </div>
        <button type="button" className="btn-secondary mt-3" onClick={() => {
          try { setItems(monthlyItems(firstDue, Number(count), agreed)); setWriteError(''); }
          catch (e) { setWriteError(e.message); }
        }}>Prepare monthly dates</button>
        <div className="mt-3 max-h-72 space-y-2 overflow-auto" aria-label="Review draft instalments">{items.map((item, index) => <div className="grid grid-cols-[2rem_1fr_1fr] items-end gap-2" key={index}>
          <span className="pb-2 text-xs">#{index + 1}</span><Field label={`Due date ${index + 1}`}><input className="field-input min-w-0" type="date" required min={disbursed || undefined} value={item.due_on} onChange={e => setItems(rows => rows.map((r, i) => i === index ? { ...r, due_on: e.target.value } : r))} /></Field>
          <Field label={`Amount ${index + 1} (PKR)`}><input className="field-input min-w-0" required inputMode="decimal" value={item.amount_pkr} onChange={e => setItems(rows => rows.map((r, i) => i === index ? { ...r, amount_pkr: e.target.value } : r))} /></Field></div>)}</div>
        <button type="button" className="mt-3 text-sm font-semibold text-indigo-700" disabled={items.length >= 120} onClick={() => setItems(rows => [...rows, { due_on: '', amount_pkr: '' }])}>+ Add a custom instalment</button>
        <Field label="Agreement reference and recording reason"><textarea className="field-input mt-1" required minLength={10} maxLength={500} value={source} onChange={e => setSource(e.target.value)} /></Field>
        <div className="mt-3 flex flex-wrap gap-2"><button className="btn-primary" disabled={!items.length}>{busy ? 'Saving…' : 'Save reviewed schedule'}</button>
          <button className="btn-secondary" type="button" onClick={() => { setEditing(false); setDisbursed(''); setFirstDue(''); setAgreed(''); setItems([]); setSource(''); setWriteError(''); }}>Discard schedule draft</button></div>
      </fieldset></form>}
    {!data.schedule && !manager && <p className="mt-3 text-sm text-slate-600">Ask a manager to record the agreement before allocating payments.</p>}

    {data.schedule?.is_current && !editing && <form className="mt-5 rounded-lg border border-slate-200 p-4" onSubmit={saveReceipt}>
      <fieldset disabled={busy}><legend className="font-semibold text-slate-900">Record a payment receipt</legend>
        <p className="mt-1 text-xs text-slate-600">Use one payment reference per receipt. Split its amount explicitly across instalments if needed; no allocation is inferred.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Actual payment date"><input className="field-input" required type="date" min={data.schedule.disbursed_on} max={data.as_of_date} value={paidOn} onChange={e => setPaidOn(e.target.value)} /></Field>
          <Field label="Payment evidence reference"><input className="field-input" required minLength={3} maxLength={80} value={reference} onChange={e => setReference(e.target.value)} /></Field></div>
        {allocations.map((row, index) => <div className="mt-3 grid grid-cols-[1fr_1fr_auto] items-end gap-2" key={index}>
          <Field label={`Allocate to instalment ${index + 1}`}><select className="field-input" required value={row.installment} onChange={e => updateAllocation(index, 'installment', e.target.value)}><option value="">Choose…</option>
            {data.installments.filter(i => i.outstanding_pkr !== '0.00').map(i => <option key={i.installment} value={i.installment}>#{i.installment} · {formatDate(i.due_on)}</option>)}</select></Field>
          <Field label={`Allocated amount ${index + 1} (PKR)`}><input className="field-input" required inputMode="decimal" value={row.amount_pkr} onChange={e => updateAllocation(index, 'amount_pkr', e.target.value)} /></Field>
          <button type="button" className="btn-secondary" aria-label={`Remove allocation ${index + 1}`} disabled={allocations.length === 1} onClick={() => setAllocations(rows => rows.filter((_, i) => i !== index))}>×</button></div>)}
        <button type="button" className="mt-3 text-sm font-semibold text-indigo-700" disabled={allocations.length >= data.installments.length} onClick={() => setAllocations(rows => [...rows, blankAllocation()])}>+ Split across another instalment</button>
        <div className="mt-3 flex flex-wrap gap-2"><button className="btn-primary" disabled={data.total_outstanding_pkr === '0.00'}>{busy ? 'Saving…' : 'Save allocated receipt'}</button>
          <button className="btn-secondary" type="button" onClick={() => { setPaidOn(''); setReference(''); setAllocations([blankAllocation()]); setWriteError(''); }}>Discard receipt draft</button></div>
      </fieldset></form>}
    {data.receipt_count > 0 && <div className="mt-5"><h4 className="text-sm font-semibold text-slate-900">Receipt history</h4><p className="text-xs text-slate-500">{data.recent_receipts.length ? data.receipt_offset + 1 : 0}–{data.receipt_offset + data.recent_receipts.length} of {data.receipt_count}; newest first. Voided entries remain in history.</p>
      <ul className="mt-2 space-y-3">{data.recent_receipts.map(r => <li key={r.id} className="rounded-lg border border-slate-200 p-3 text-sm">
        <div className="flex flex-wrap justify-between gap-2"><strong className="break-all">{r.reference}</strong><span>{amount(r.total_pkr)} · {formatDate(r.paid_on)}</span></div>
        <p className="mt-1 text-xs text-slate-600">Recorded by {r.created_by} · {r.allocations.map(a => `#${a.installment}: ${amount(a.amount_pkr)}`).join(' · ')}</p>
        {r.voided_at ? <p className="mt-1 text-xs text-rose-800">Voided by {r.voided_by}: {r.void_reason}</p> : manager && data.schedule.is_current && <button type="button" className="mt-2 text-xs font-semibold text-rose-800" disabled={busy || dirty} onClick={() => { setVoiding(r.id); setReason(''); }}>Correct by voiding this receipt</button>}
        {voiding === r.id && <form className="mt-3" onSubmit={event => {
          event.preventDefault(); write(() => voidRepaymentReceipt(applicationId, r.id, reason), 'Receipt voided. Balances recalculated; the original entry remains in history.', () => { setVoiding(null); setReason(''); });
        }}><fieldset disabled={busy}><Field label="Reason for voiding"><textarea className="field-input" required minLength={10} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></Field>
          <p className="mt-1 text-xs text-slate-600">This restores the allocated balance and can make instalments overdue again.</p><button className="btn-secondary mt-2">Void receipt and retain history</button>
          <button className="btn-secondary ml-2 mt-2" type="button" onClick={() => { setVoiding(null); setReason(''); }}>Cancel</button></fieldset></form>}
      </li>)}</ul><div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary" disabled={busy || dirty || data.receipt_offset === 0} onClick={() => setReceiptOffset(Math.max(0, data.receipt_offset - 20))}>Newer receipts</button><button type="button" className="btn-secondary" disabled={busy || dirty || data.receipt_offset + 20 >= data.receipt_count} onClick={() => setReceiptOffset(data.receipt_offset + 20)}>Older receipts</button></div></div>}
    <details className="mt-4 text-xs text-slate-600"><summary className="cursor-pointer font-semibold">How these figures are calculated</summary><ul className="mt-2 list-disc space-y-1 pl-4">{data.limits.map(limit => <li key={limit}>{limit}</li>)}</ul></details>
  </div>;
}

function Field({ label, children }) { return <label className="mt-2 block min-w-0 text-xs font-medium text-slate-700"><span className="mb-1 block">{label}</span>{children}</label>; }
function Metric({ label, value, alert }) { return <div className={`rounded-lg border p-3 ${alert ? 'border-rose-200 bg-rose-50' : 'border-slate-200 bg-slate-50'}`}><p className="text-xs text-slate-600">{label}</p><p className={`mt-1 break-words text-lg font-semibold ${alert ? 'text-rose-800' : 'text-slate-900'}`}>{value}</p></div>; }
