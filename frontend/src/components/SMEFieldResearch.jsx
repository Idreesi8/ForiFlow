import { useEffect, useState } from 'react';
import { apiErrorMessage, fetchSMEFieldResearch } from '../api/client.js';

const sourceNames = { bangladesh: 'Bangladesh SME applications', polish: 'UCI Polish companies bankruptcy', pakistan_metadata: 'Pakistan World Bank Enterprise Survey 2022', sba_dictionary: 'US SBA loan data dictionary' };
const statusNames = { candidate: 'Candidate for research', missing_exact_measure: 'Exact measure missing', definition_mismatch: 'Definitions need alignment', missing_order_history: 'Order history needed' };

export default function SMEFieldResearch() {
  const [view, setView] = useState({ data: null, error: null }), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    setView({ data: null, error: null });
    fetchSMEFieldResearch({ signal: controller.signal }).then(data => {
      if (alive) setView({ data, error: null });
    }).catch(error => { if (alive && !controller.signal.aborted) setView({ data: null, error: apiErrorMessage(error, 'Could not read the SME dataset research.') }); });
    return () => { alive = false; controller.abort(); };
  }, [attempt]);
  const data = view.data;
  return <section className="card min-w-0" aria-labelledby="sme-field-research-title" data-testid="sme-field-research">
    <div className="card-header"><div><h3 id="sme-field-research-title" className="card-title">Data for the additional fields</h3><p className="mt-1 text-xs text-slate-600">Operating checks are active. New trained credit effects need compatible evidence and validation.</p></div></div>
    <div className="space-y-4 px-5 py-4">
      {view.error ? <div role="alert"><p className="text-sm text-rose-800">{view.error}</p><button type="button" className="btn-secondary mt-2 text-xs" onClick={() => setAttempt(value => value + 1)}>Retry dataset research</button></div> : !data ? <p role="status" className="text-sm text-slate-500">Loading dataset research…</p> : <>
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-relaxed text-amber-950">{data.gate} These sources have not replaced the serving credit model.</p>
        <div className="grid gap-3 lg:grid-cols-2">{data.field_coverage.map(field => <div key={field.field} className="rounded-xl border border-slate-200 p-3"><h4 className="text-sm font-semibold text-slate-900">{field.label}</h4><p className="mt-1 text-xs font-medium text-amber-900">{statusNames[field.research_status]}</p><p className="mt-2 text-xs leading-relaxed text-slate-600">{field.gap}</p></div>)}</div>
        <details><summary className="text-sm font-semibold text-brand-800">Acquired data, licences and limitations</summary><div className="mt-3 space-y-3">{data.sources.map(source => <div key={source.id} className="min-w-0 rounded-lg bg-slate-50 p-3">
          <a href={source.page} target="_blank" rel="noreferrer" className="text-sm font-semibold text-brand-800 underline underline-offset-2">{sourceNames[source.id]}</a>
          <p className="mt-1 text-xs text-slate-600">{source.rows_downloaded ? `${source.rows_downloaded.toLocaleString('en-PK')} rows downloaded.` : source.cohorts ? `${source.cohorts.length} separate horizon files downloaded; not pooled.` : source.metadata_downloaded ? 'Survey metadata downloaded; firm-level data not acquired.' : 'Dictionary downloaded; loan records not acquired.'}</p>
          <p className="mt-1 text-xs text-slate-600">Licence: {source.license}</p><p className="mt-2 text-xs leading-relaxed text-slate-600">{source.use}</p><ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-500">{source.limitations.map(note => <li key={note}>{note}</li>)}</ul><p className="mt-2 break-all text-[11px] text-slate-500">Research archive SHA-256: {source.sha256}</p>
        </div>)}</div></details>
        <details><summary className="text-sm font-semibold text-brand-800">Evidence needed for a future SME model</summary><ul className="mt-3 list-disc space-y-2 pl-4 text-xs text-slate-600">{data.next_data.map(note => <li key={note}>{note}</li>)}</ul></details>
      </>}
    </div>
  </section>;
}
