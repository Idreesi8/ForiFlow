import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { canDecideCredit } from '../api/auth.js';
import { apiErrorMessage, fetchCaseData, fetchCaseDataHistory, recordCaseData, replaceCaseData, withdrawCaseData } from '../api/client.js';
import { BASES, PURPOSES, SOURCE_KINDS, STATES, blankEvidence, evidenceDraft, evidencePayload, validEvidenceReport, validEvidenceHistory } from '../lib/caseData.js';
import { saveIntent } from '../lib/repaymentCalendar.js';
import { formatDate, formatDateTime } from '../lib/format.js';
import { positiveInteger } from '../lib/actionDesk.js';
import { useBusinessDate } from '../hooks/useBusinessDate.js';
import { useUnsavedWork } from '../components/UnsavedWork.jsx';
import { ErrorState, LoadingState } from '../components/common/States.jsx';

export default function CaseDataPage() {
  const { applicationId } = useParams();
  const id = positiveInteger(applicationId);
  return id ? <EvidenceWorkspace key={id} applicationId={id} /> : <ErrorState message="Choose an application with a valid case number." />;
}

function EvidenceWorkspace({ applicationId }) {
  const [data, setData] = useState(null), [offset, setOffset] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [form, setForm] = useState(blankEvidence), [showForm, setShowForm] = useState(false), [editing, setEditing] = useState(null);
  const [withdrawing, setWithdrawing] = useState(null), [reason, setReason] = useState(''), [busy, setBusy] = useState(false);
  const [writeError, setWriteError] = useState(''), [retryHint, setRetryHint] = useState(false), [message, setMessage] = useState('');
  const [history, setHistory] = useState(null), [historyBusy, setHistoryBusy] = useState(false), [historyError, setHistoryError] = useState('');
  const sequence = useRef(0), historySequence = useRef(0), readController = useRef(null), alive = useRef(true), saving = useRef(false), intent = useRef(null);
  const sourceInput = useRef(null), withdrawalInput = useRef(null), historyStart = useRef(null);
  const today = useBusinessDate(), manager = canDecideCredit();
  const dirty = showForm || withdrawing !== null;
  useUnsavedWork({ label: `Source and permission evidence · App #${applicationId}`, dirty, busy,
    leaveWarning: retryHint ? 'The last save could not be confirmed. Retry unchanged details to recover its result before leaving.' : null });
  useEffect(() => { if (showForm) sourceInput.current?.focus(); }, [showForm]);
  useEffect(() => { if (withdrawing !== null) withdrawalInput.current?.focus(); }, [withdrawing]);
  useEffect(() => { if (history) historyStart.current?.focus(); }, [history]);
  const accept = useCallback(report => {
    if (!validEvidenceReport(report, applicationId)) throw Object.assign(new Error('The evidence response does not match this case or its expected records. Reload before recording anything.'), { code: 'EVIDENCE_MISMATCH' });
    setData(report);
  }, [applicationId]);
  const load = useCallback(async () => {
    if (saving.current) return;
    const request = ++sequence.current;
    readController.current?.abort(); const controller = new AbortController(); readController.current = controller;
    setLoading(true); setError(''); setData(null); setHistoryBusy(false); setHistory(null); setHistoryError('');
    try { const report = await fetchCaseData(applicationId, { offset, signal: controller.signal }); if (request === sequence.current) accept(report); }
    catch (e) { if (request === sequence.current && !controller.signal.aborted) setError(evidenceError(e, 'Could not load case evidence.')); }
    finally { if (request === sequence.current) setLoading(false); }
  }, [applicationId, offset, accept]);
  useEffect(() => { alive.current = true; load(); return () => { alive.current = false; ++sequence.current; ++historySequence.current; readController.current?.abort(); }; }, [load, today]);
  const clear = () => { setForm(blankEvidence()); setShowForm(false); setEditing(null); setWithdrawing(null); setReason(''); intent.current = null; };
  const update = (key, value) => setForm(f => ({ ...f, [key]: value }));
  const toggle = (key, value, checked) => setForm(f => ({ ...f, [key]: checked ? [...f[key], value] : f[key].filter(item => item !== value) }));
  const write = async (operation, payload, targetId) => {
    if (saving.current) return;
    saving.current = true; setBusy(true); setWriteError(''); setRetryHint(false); setMessage('');
    ++sequence.current; readController.current?.abort(); ++historySequence.current; setHistoryBusy(false); setHistoryError('');
    const body = { operation, targetId, payload };
    intent.current = saveIntent(intent.current, body, () => crypto.randomUUID());
    const request = { ...payload, submission_key: intent.current.key };
    try {
      const report = operation === 'withdraw' ? await withdrawCaseData(applicationId, targetId, request) :
        operation === 'replace' ? await replaceCaseData(applicationId, targetId, request) : await recordCaseData(applicationId, request);
      if (!alive.current) return;
      accept(report); clear(); setHistory(null); setOffset(0);
      setMessage(operation === 'withdraw' ? 'Withdrawal recorded as a new history entry. Earlier evidence is retained.' : 'Evidence reference recorded. It does not grant data access or authorise model training.');
    } catch (e) { if (alive.current) { setWriteError(evidenceError(e, 'The save could not be confirmed.')); const status = e.response?.status; setRetryHint(!status || status === 408 || status >= 500); } }
    finally { saving.current = false; if (alive.current) setBusy(false); }
  };
  const openHistory = async (streamKey, page = 0) => {
    const request = ++historySequence.current; setHistoryBusy(true); setHistoryError(''); setHistory(null);
    try {
      const result = await fetchCaseDataHistory(applicationId, streamKey, page);
      if (request !== historySequence.current || !alive.current) return;
      if (!validEvidenceHistory(result, applicationId, streamKey)) throw Object.assign(new Error('The returned history does not match this source.'), { code: 'EVIDENCE_MISMATCH' });
      setHistory(result);
    } catch (e) { if (request === historySequence.current && alive.current) setHistoryError(evidenceError(e, 'Could not load source history.')); }
    finally { if (request === historySequence.current && alive.current) setHistoryBusy(false); }
  };

  if (loading) return <LoadingState label="Loading source and permission evidence…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;
  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><p className="break-words text-xs font-semibold text-brand-700">App #{applicationId} · {data.business_name}</p><h2 className="mt-1 text-xl font-bold text-slate-900">Source &amp; permission evidence</h2><p className="mt-1 text-sm text-slate-600">Records as of {formatDate(data.as_of_date)} (Pakistan). Assessment saved {formatDateTime(data.assessed_at)}.</p></div>
      <Link to={`/shap/${applicationId}`} className="btn-secondary">Back to case review</Link></header>
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">Recording a reference does not give permission. These notes are added after assessment and do not prove what was authorised when the case was scored. Verify the source and lender-approved process before further use.</div>
    {message && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{message}</p>}
    {writeError && <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-900">{writeError}{retryHint ? ' Retry unchanged details to recover the original save if its response was lost.' : ' Review the draft. Discard it before reloading changed records.'}</p>}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Source records" value={data.total} /><Metric label="Records missing permission" value={data.total ? data.counts.missing : 'Unknown'} /><Metric label="Expired or withdrawn records" value={data.total ? data.counts.expired + data.counts.withdrawn : 'Unknown'} /><Metric label="Documented records without expiry" value={data.total ? data.counts.recorded_no_expiry : 'Unknown'} /></div>
    <div className="flex flex-wrap gap-2"><button type="button" className="btn-primary" disabled={busy || dirty} onClick={() => { setShowForm(true); setForm(blankEvidence()); setWriteError(''); setMessage(''); setRetryHint(false); }}>Add source evidence</button><button type="button" className="btn-secondary" disabled={busy || dirty} onClick={load}>Reload evidence</button></div>
    {showForm && <form className="card p-5" onSubmit={e => { e.preventDefault(); write(editing ? 'replace' : 'record', evidencePayload(form), editing?.id ?? null); }}>
      <fieldset disabled={busy}><legend className="text-base font-semibold text-slate-900">{editing ? `Correct source record #${editing.id}` : 'Record a source reference'}</legend>
        {editing?.status === 'withdrawn' && <p className="mt-2 text-sm text-amber-900">Reinstatement requires new permission evidence dated on or after the recorded withdrawal. Earlier evidence cannot silently restore it.</p>}
        <div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Source type"><select ref={sourceInput} className="field-input" required value={form.source_kind} onChange={e => update('source_kind', e.target.value)}><option value="">Choose source…</option>{Object.entries(SOURCE_KINDS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
          <Field label="Source document or declaration reference"><input className="field-input" required minLength={3} maxLength={160} value={form.source_reference} onChange={e => update('source_reference', e.target.value)} /></Field>
          <Field label="Date the source was obtained"><input className="field-input" required type="date" max={data.as_of_date} value={form.captured_on} onChange={e => update('captured_on', e.target.value)} /></Field>
          <Field label="Permission evidence basis"><select className="field-input" value={form.permission_basis} onChange={e => update('permission_basis', e.target.value)}>{Object.entries(BASES).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field></div>
        <details className="mt-3"><summary className="cursor-pointer text-sm font-medium text-slate-700">Source period (optional)</summary><div className="grid gap-3 sm:grid-cols-2"><Field label="Source period from"><input className="field-input" type="date" max={form.captured_on || data.as_of_date} value={form.period_from} onChange={e => update('period_from', e.target.value)} /></Field><Field label="Source period to"><input className="field-input" type="date" min={form.period_from || undefined} max={form.captured_on || data.as_of_date} value={form.period_to} onChange={e => update('period_to', e.target.value)} /></Field></div></details>
        <fieldset className="mt-4"><legend className="text-sm font-semibold text-slate-800">Which saved financial fields does this source support?</legend><p className="mt-1 text-xs text-slate-600">This records an officer assertion and snapshots the existing case values; it does not change them or verify the source.</p><div className="mt-2 grid gap-2 sm:grid-cols-2">{data.field_coverage.map(field => <label key={field.field} className="flex items-start gap-2 text-sm"><input className="mt-1" type="checkbox" checked={form.input_fields.includes(field.field)} onChange={e => toggle('input_fields', field.field, e.target.checked)} /><span>{field.label}</span></label>)}</div></fieldset>
        <fieldset className="mt-4"><legend className="text-sm font-semibold text-slate-800">Purposes covered by this record</legend><p className="mt-1 text-xs text-slate-600">If evidence is missing, these are intended purposes only. Research permission is separate and never inferred from credit assessment.</p><div className="mt-2 flex flex-wrap gap-4">{Object.entries(PURPOSES).map(([key, label]) => <label key={key} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={form.purposes.includes(key)} onChange={e => toggle('purposes', key, e.target.checked)} />{label}</label>)}</div></fieldset>
        {form.permission_basis !== 'not_recorded' && <div className="mt-4 grid gap-3 sm:grid-cols-2"><Field label="Permission document reference"><input className="field-input" required minLength={3} maxLength={160} value={form.permission_reference} onChange={e => update('permission_reference', e.target.value)} /></Field><Field label="Permission evidence date"><input className="field-input" required type="date" max={data.as_of_date} value={form.permission_on} onChange={e => update('permission_on', e.target.value)} /></Field><Field label="Recorded permission expiry (optional)"><input className="field-input" type="date" min={form.permission_on || undefined} value={form.permission_expires_on} onChange={e => update('permission_expires_on', e.target.value)} /></Field><p className="self-end text-xs text-slate-600">A blank expiry is unknown. Referenced documents, signatures and legal authority are not independently verified here.</p></div>}
        <Field label="Recording or correction note"><textarea className="field-input" required minLength={10} maxLength={500} value={form.note} onChange={e => update('note', e.target.value)} /></Field><p className="mt-1 text-xs text-slate-500">Use references and a short review note. Do not paste passwords, account identifiers or the full source document.</p>
        <div className="mt-4 flex flex-wrap gap-2"><button className="btn-primary" disabled={!form.input_fields.length || !form.purposes.length}>{busy ? 'Saving…' : editing ? 'Save correction as a new revision' : 'Save evidence reference'}</button><button type="button" className="btn-secondary" onClick={() => { clear(); setWriteError(''); }}>Discard evidence draft</button></div>
      </fieldset></form>}

    {!data.total && <div className="card p-5"><h3 className="font-semibold text-slate-900">No source evidence recorded</h3><p className="mt-2 text-sm text-slate-600">Missing records are unknown. Existing borrower data, scores and permissions have not been backfilled or inferred.</p></div>}
    {data.rows.map(row => <article className="card p-5" key={row.id}>
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0 flex-1"><h3 className="font-semibold text-slate-900">{SOURCE_KINDS[row.source_kind]} · record #{row.id}</h3><p className="mt-1 break-words text-sm text-slate-700">{row.source_reference}</p></div><span className={`rounded-lg px-3 py-2 text-xs font-semibold ${row.status === 'recorded' ? 'bg-blue-50 text-blue-900' : 'bg-amber-50 text-amber-950'}`}>{STATES[row.status]}</span></div>
      <p className="mt-2 text-xs text-slate-600">Revision {row.revision} · {row.created_by} · {formatDateTime(row.created_at)}</p>
      <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><Fact label="Source obtained">{formatDate(row.captured_on)}</Fact><Fact label="Source period">{row.period_from ? `${formatDate(row.period_from)} to ${formatDate(row.period_to)}` : 'Not recorded'}</Fact><Fact label="Permission evidence">{BASES[row.permission_basis]}{row.permission_reference ? ` · ${row.permission_reference}` : ''}</Fact><Fact label="Evidence date / expiry">{row.permission_on ? formatDate(row.permission_on) : 'Not recorded'} / {row.permission_expires_on ? formatDate(row.permission_expires_on) : 'Not recorded'}</Fact><Fact label="Recorded purposes">{row.purposes.map(p => PURPOSES[p]).join(' · ')}</Fact><Fact label="Officer note">{row.note}</Fact></dl>
      {row.flags.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-amber-900">{row.flags.map(flag => <li key={flag}>{flag}</li>)}</ul>}
      <details className="mt-3 text-sm"><summary className="cursor-pointer font-semibold text-slate-700">Linked saved values (officer assertion)</summary><dl className="mt-2 grid gap-2 sm:grid-cols-2">{row.input_fields.map(field => <Fact key={field} label={data.field_coverage.find(f => f.field === field).label}>{String(row.input_snapshot[field])}</Fact>)}</dl></details>
      <div className="mt-4 flex flex-wrap gap-2"><button type="button" className="btn-secondary" disabled={busy || historyBusy} onClick={() => openHistory(row.stream_key)}>History for source #{row.id}</button>{manager && <button type="button" className="btn-secondary" disabled={busy || dirty} onClick={() => { setEditing(row); setForm(evidenceDraft(row)); setShowForm(true); setWriteError(''); setMessage(''); setRetryHint(false); }}>Correct source #{row.id}</button>}{manager && row.status !== 'withdrawn' && <button type="button" className="btn-secondary" disabled={busy || dirty} onClick={() => { setWithdrawing(row.id); setReason(''); setWriteError(''); setMessage(''); setRetryHint(false); }}>Record withdrawal for source #{row.id}</button>}</div>
      {withdrawing === row.id && <form className="mt-4 border-t border-slate-200 pt-3" onSubmit={e => { e.preventDefault(); write('withdraw', { reason: reason.trim() }, row.id); }}><fieldset disabled={busy}><Field label="Withdrawal reason and evidence reference"><textarea ref={withdrawalInput} className="field-input" required minLength={10} maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></Field><p className="mt-2 text-xs text-slate-600">This appends a restriction record now. It does not delete retained data or enforce withdrawal at an external provider.</p><div className="mt-3 flex flex-wrap gap-2"><button className="btn-primary">Record withdrawal and retain history</button><button type="button" className="btn-secondary" onClick={() => { setWithdrawing(null); setReason(''); }}>Cancel withdrawal</button></div></fieldset></form>}
    </article>)}
    {data.total > 10 && <div className="flex flex-wrap items-center gap-3"><button type="button" className="btn-secondary" disabled={busy || dirty || data.offset === 0} onClick={() => setOffset(Math.max(0, data.offset - 10))}>Newer sources</button><span className="text-sm text-slate-600">{data.offset + 1}–{data.offset + data.rows.length} of {data.total}</span><button type="button" className="btn-secondary" disabled={busy || dirty || data.offset + 10 >= data.total} onClick={() => setOffset(data.offset + 10)}>Older sources</button></div>}
    {historyBusy && <LoadingState label="Loading source history…" />}{historyError && <p role="alert" className="text-sm text-rose-800">{historyError}</p>}
    {history && <section ref={historyStart} tabIndex={-1} className="card p-5" aria-label="Source revision history"><div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold">Source revision history</h3><button type="button" className="btn-secondary" onClick={() => setHistory(null)}>Close history</button></div><p className="mt-2 text-xs text-slate-600">Newest first. Expiry status is evaluated as of today, not reconstructed at each historical date. Earlier records remain unchanged.</p><ol className="mt-3 space-y-3">{history.rows.map(r => <li key={r.id} className="rounded-lg bg-slate-50 p-3 text-sm"><strong>Revision {r.revision} · {r.event_kind === 'withdrawn' ? 'Withdrawal recorded' : 'Evidence recorded'}</strong><p className="mt-1 break-words">{r.source_reference} · {r.purposes.map(p => PURPOSES[p]).join(' · ')}</p><p className="mt-1 text-xs text-slate-600">{r.created_by} · {formatDateTime(r.created_at)} · {r.note}</p><details className="mt-2"><summary className="cursor-pointer font-semibold text-slate-700">Recorded references and saved values</summary><p className="mt-2 break-words">{BASES[r.permission_basis]}{r.permission_reference ? ` · ${r.permission_reference}` : ''}</p><p className="mt-1 text-xs text-slate-600">Evidence date: {r.permission_on ? formatDate(r.permission_on) : 'Not recorded'} · Expiry: {r.permission_expires_on ? formatDate(r.permission_expires_on) : 'Not recorded'} · Source obtained: {formatDate(r.captured_on)}</p><dl className="mt-2 grid gap-2 sm:grid-cols-2">{r.input_fields.map(field => <Fact key={field} label={data.field_coverage.find(f => f.field === field).label}>{String(r.input_snapshot[field])}</Fact>)}</dl></details></li>)}</ol><div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary" disabled={history.offset === 0 || historyBusy} onClick={() => openHistory(history.stream_key, Math.max(0, history.offset - 20))}>Newer revisions</button><button type="button" className="btn-secondary" disabled={history.offset + 20 >= history.total || historyBusy} onClick={() => openHistory(history.stream_key, history.offset + 20)}>Older revisions</button></div></section>}
    <details className="card p-5"><summary className="cursor-pointer font-semibold text-slate-800">Financial field coverage</summary><p className="mt-2 text-xs text-slate-600">Counts are references attached to saved fields, not a data-quality score or permission verdict.</p><ul className="mt-3 space-y-2 text-sm">{data.field_coverage.map(f => <li key={f.field} className="flex flex-wrap justify-between gap-2"><span>{f.label}</span><span>{f.source_records} source record{f.source_records === 1 ? '' : 's'}</span></li>)}</ul></details>
    <details className="card p-5 text-sm text-slate-600"><summary className="cursor-pointer font-semibold">What this register establishes</summary><ul className="mt-3 list-disc space-y-2 pl-4">{data.limits.map(limit => <li key={limit}>{limit}</li>)}</ul></details>
  </div>;
}

function Field({ label, children }) { return <label className="mt-2 block min-w-0 text-xs font-medium text-slate-700"><span className="mb-1 block">{label}</span>{children}</label>; }
function Fact({ label, children }) { return <div className="min-w-0"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words text-slate-800">{children}</dd></div>; }
function Metric({ label, value }) { return <div className="card p-4"><p className="text-xs text-slate-600">{label}</p><p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p></div>; }
function evidenceError(error, fallback) { return error.code === 'EVIDENCE_MISMATCH' ? error.message : apiErrorMessage(error, fallback); }
