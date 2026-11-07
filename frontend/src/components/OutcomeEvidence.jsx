import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage, fetchOutcomeEvidence } from '../api/client.js';
import { EVIDENCE_STATUSES, validOutcomeEvidence } from '../lib/outcomeEvidence.js';
import { formatCount, formatDate, formatDateTime } from '../lib/format.js';

const PAGE_SIZE = 10;

export default function OutcomeEvidence() {
  const [query, setQuery] = useState({ horizon: 3, limit: PAGE_SIZE, offset: 0, status_filter: '' });
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState({ loading: true, data: null, error: null });
  const heading = useRef(null);
  const paging = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setView({ loading: true, data: null, error: null, query });
    fetchOutcomeEvidence({ ...query, status_filter: query.status_filter || undefined }, { signal: controller.signal })
      .then(data => {
        if (!validOutcomeEvidence(data, query)) throw new Error('The evidence totals could not be verified.');
        if (alive) setView({ loading: false, data, error: null, query });
      }).catch(error => {
        if (alive && !controller.signal.aborted) setView({ loading: false, data: null, query,
          error: apiErrorMessage(error, 'Repayment evidence could not be verified. Please retry.') });
      });
    return () => { alive = false; controller.abort(); };
  }, [query, attempt]);
  useEffect(() => {
    if (!view.loading && paging.current) {
      heading.current?.scrollIntoView({ block: 'start' });
      heading.current?.focus({ preventScroll: true });
      paging.current = false;
    }
  }, [view.loading]);
  const current = view.query === query;
  const data = current ? view.data : null;
  const error = current ? view.error : null;
  const loading = !current || view.loading;
  const change = update => { paging.current = false; setQuery(previous => ({ ...previous, ...update, offset: 0 })); };
  const page = offset => { paging.current = true; setQuery(previous => ({ ...previous, offset })); };
  return <section className="card min-w-0" aria-labelledby="outcome-evidence-title" id="repayment-evidence">
    <div className="card-header">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-brand-700">From monitoring to better evidence</p>
        <h3 id="outcome-evidence-title" className="mt-1 text-lg font-bold text-slate-900">Repayment evidence for learning</h3>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">See which approved facilities have complete records for a selected reporting window, and where to collect missing evidence. This does not measure model accuracy.</p></div>
      <span className="badge bg-amber-50 text-amber-900">Evidence collection only</span>
    </div>
    <div className="space-y-5 px-5 py-5">
      <div className="grid grid-cols-1 gap-3 sm:flex sm:flex-wrap sm:items-end">
        <label className="min-w-0 flex-1 text-xs font-semibold text-slate-700">Reporting window
          <select className="field-input mt-1" aria-label="Evidence reporting window" value={query.horizon} onChange={e => change({ horizon: Number(e.target.value) })}>
            {[3, 6, 12].map(months => <option key={months} value={months}>First {months} months</option>)}
          </select></label>
        <label className="min-w-0 flex-1 text-xs font-semibold text-slate-700">Show facilities
          <select className="field-input mt-1" aria-label="Evidence facility status" value={query.status_filter} onChange={e => change({ status_filter: e.target.value })}>
            <option value="">All approved facilities</option>
            {Object.entries(EVIDENCE_STATUSES).map(([id, text]) => <option key={id} value={id}>{text}</option>)}
          </select></label>
        <button className="btn-secondary text-xs" disabled={loading} onClick={() => setAttempt(n => n + 1)}>Refresh evidence</button>
      </div>
      {loading ? <p role="status" className="text-sm text-slate-600">Checking recorded evidence…</p> : error ?
        <div role="alert" className="rounded-xl bg-rose-50 p-4 text-sm text-rose-900"><p>{error}</p><button className="btn-secondary mt-3" onClick={() => setAttempt(n => n + 1)}>Retry evidence check</button></div> : <>
        <p className="text-xs leading-relaxed text-slate-600">{data.basis}</p>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            ['Approved facilities', data.counts.approved_facilities, 'Complete portfolio; counts do not change with the list filter.'],
            ['Windows covered', data.counts.covered, 'All selected months have dated provenance, amounts and consistent exact days late.'],
            ['Records need attention', data.counts.needs_evidence, 'Window has elapsed, but earlier months or required evidence are missing.'],
          ].map(([label, value, note]) => <div key={label} className="rounded-xl bg-slate-50 p-4"><dt className="text-xs font-medium text-slate-600">{label}</dt><dd className="mt-2 text-2xl font-bold text-slate-900">{formatCount(value)}</dd><p className="mt-2 text-xs leading-relaxed text-slate-500">{note}</p></div>)}
        </dl>
        <p className="text-xs leading-relaxed text-slate-600">Windows still open: {formatCount(data.counts.collecting)} · Dated approval needed: {formatCount(data.counts.needs_approval_record)} · Shorter than this window: {formatCount(data.counts.shorter_term)}.</p>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <p>Covered windows with a recorded delay of 30 or more days: <strong>{formatCount(data.counts.covered_with_30_plus)}</strong>. This is a monitoring signal, not a measured default rate.</p>
          <p className="mt-2 text-xs leading-relaxed">Linked borrowers: {formatCount(data.counts.distinct_linked_borrowers)} · Additional repeat facilities: {formatCount(data.counts.additional_repeat_facilities)} · Without a borrower link: {formatCount(data.counts.unlinked_facilities)}. Repeat facilities must stay together when future models are validated.</p>
        </div>
        <div>
          <h4 ref={heading} tabIndex={-1} className="scroll-mt-28 text-sm font-semibold text-slate-900">Facility evidence</h4>
          <p className="mt-1 text-xs text-slate-500">{data.total ? `${formatCount(query.offset + 1)}–${formatCount(Math.min(query.offset + PAGE_SIZE, data.total))} of ${formatCount(data.total)}` : 'No facilities match this view.'}</p>
          <ul className="mt-3 space-y-3" aria-label="Facility evidence list">
            {data.rows.map(row => <li key={row.application_id} className="min-w-0 rounded-xl border border-slate-200 p-4">
              <div className="flex flex-wrap justify-between gap-2"><p className="min-w-0 break-words text-sm font-semibold text-slate-900">#{row.application_id} · {row.business_name}</p><span className={`text-xs font-semibold ${row.status === 'covered' ? 'text-brand-800' : 'text-slate-600'}`}>{EVIDENCE_STATUSES[row.status]}</span></div>
              <p className="mt-2 text-xs text-slate-600">Usable months: {row.usable_months}/{query.horizon} · Active records: {row.recorded_months}{row.window_end ? ` · Window anniversary: ${formatDate(row.window_end)}` : ''}</p>
              <details className="mt-3"><summary className="text-xs font-semibold text-brand-800">Evidence and model details</summary><ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-slate-600">{row.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul><p className="mt-2 break-words text-xs text-slate-500">Borrower: {row.borrower_public_id || 'Public reference not recorded'} · Model: {row.model_version || 'Not recorded'} · Engine: {row.scoring_engine || 'Not recorded'}</p></details>
              <Link className="mt-3 inline-block text-xs font-semibold text-brand-800 underline underline-offset-2" to={`/alerts?facility=${row.application_id}#monitoring`}>Review monitoring records →</Link>
            </li>)}
          </ul>
          {data.total > PAGE_SIZE ? <div className="mt-4 flex flex-wrap gap-2" aria-label="Evidence pages"><button className="btn-secondary text-xs" disabled={query.offset === 0} onClick={() => page(Math.max(0, query.offset - PAGE_SIZE))}>Previous facilities</button><button className="btn-secondary text-xs" disabled={query.offset + PAGE_SIZE >= data.total} onClick={() => page(query.offset + PAGE_SIZE)}>Next facilities</button></div> : null}
        </div>
        <details><summary className="text-sm font-semibold text-slate-700">What this evidence can and cannot establish</summary><ul className="mt-3 list-disc space-y-2 pl-4 text-xs leading-relaxed text-slate-600">{data.limits.map(note => <li key={note}>{note}</li>)}</ul><p className="mt-3 text-xs text-slate-500">Snapshot: {formatDateTime(data.captured_at)}. No model, case or decision was changed.</p></details>
      </>}
    </div>
  </section>;
}
