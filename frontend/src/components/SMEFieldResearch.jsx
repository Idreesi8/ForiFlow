import { useEffect, useState } from 'react';
import { apiErrorMessage, fetchSMEFieldResearch } from '../api/client.js';

const sourceNames = { bangladesh: 'Bangladesh SME applications', polish: 'UCI Polish companies bankruptcy', pakistan_metadata: 'Pakistan World Bank Enterprise Survey 2022', sba_dictionary: 'US SBA loan data dictionary' };
const statusNames = { candidate: 'Candidate for research', missing_exact_measure: 'Matching pilot measure needed', definition_mismatch: 'Definitions need alignment', missing_order_history: 'Loan-linked order history needed' };
const formatCount = value => value.toLocaleString('en-PK');

function BenchmarkTable({ models }) {
  return <table className="w-full text-left text-xs">
    <thead className="border-b border-slate-200 text-slate-600"><tr><th scope="col" className="py-2 pr-2">Feature set</th><th scope="col" className="px-1 py-2">ROC AUC</th><th scope="col" className="pl-1 py-2">Average precision</th></tr></thead>
    <tbody>{models.map(model => <tr key={model.label} className="border-b border-slate-100">
      <th scope="row" className="py-2 pr-2 font-medium">{model.label}</th>
      <td className="px-1 py-2 tabular-nums">{model.roc_auc.toFixed(3)}</td>
      <td className="pl-1 py-2 tabular-nums">{model.average_precision.toFixed(3)}</td>
    </tr>)}</tbody>
  </table>;
}

function DatasetBenchmarks({ data }) {
  const { polish, sba_loans: sba, retail_orders: retail, ssbf, sources } = data;
  const link = (id, label) => <a href={sources[id].page} target="_blank" rel="noreferrer" className="text-xs font-semibold text-brand-800 underline underline-offset-2">{label}</a>;
  return <div className="space-y-3 rounded-xl border border-slate-200 p-4">
    <div>
      <h4 className="text-sm font-semibold text-slate-900">What the public data showed</h4>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">These studies use separate populations and outcomes. They describe research evidence for the additional fields.</p>
    </div>
    <details className="border-t border-slate-100 pt-3">
      <summary className="text-sm font-medium text-brand-800">Inventory turnover and debt ratios</summary>
      <div className="mt-2 space-y-2 text-xs leading-relaxed text-slate-600">
        <p>One-year corporate bankruptcy in Poland. The held-out sample had {formatCount(polish.test_rows)} rows and {formatCount(polish.test_events)} bankruptcies.</p>
        <BenchmarkTable models={polish.models} />
        <p>Inventory days use the source’s inventory and cost of products sold. Liabilities divided by assets is a ratio. The source provides neither loan repayment dates nor outstanding debt in PKR.</p>
        {link('polish', 'UCI Polish Companies Bankruptcy')}
      </div>
    </details>
    <details className="border-t border-slate-100 pt-3">
      <summary className="text-sm font-medium text-brand-800">Loan tenure and recorded employees</summary>
      <div className="mt-2 space-y-2 text-xs leading-relaxed text-slate-600">
        <p>SBA teaching cohort for California real estate and rental businesses. Fitted on 1989–2005 disbursements and tested on {formatCount(sba.test_rows)} loans from 2006–2010, including {formatCount(sba.test_events)} eventual charge-offs.</p>
        <BenchmarkTable models={sba.models} />
        <p>The study includes loans with known final outcomes. The term recorded at application time and an equal observation window could not be verified.</p>
        {link('sba_loans', 'Li, Mickel and Taylor’s SBA teaching dataset')}
      </div>
    </details>
    <details className="border-t border-slate-100 pt-3">
      <summary className="text-sm font-medium text-brand-800">Order activity</summary>
      <div className="mt-2 space-y-2 text-xs leading-relaxed text-slate-600">
        <p>{formatCount(retail.eligible_lines)} eligible product lines in a {formatCount(retail.source_rows)}-line sample became {formatCount(retail.unique_invoices)} distinct invoices after counting each invoice ID once.</p>
        <p>The sample covers part of {retail.window_start.slice(0, 10)} for one UK retailer. A consistency measure needs complete monthly order coverage.</p>
        {link('retail_orders', 'UCI Online Retail')}
      </div>
    </details>
    <details className="border-t border-slate-100 pt-3">
      <summary className="text-sm font-medium text-brand-800">Outstanding debt and headcount</summary>
      <div className="mt-2 space-y-2 text-xs leading-relaxed text-slate-600">
        <p>Among {formatCount(ssbf.firms)} surveyed US firms, {formatCount(ssbf.reported_debt_firms)} had a reported or edited principal balance and {formatCount(ssbf.reported_headcount_firms)} had a reported or edited worker count including working owners.</p>
        <p>The unweighted median among positive reported balances was USD {formatCount(ssbf.median_positive_debt_usd)}. The median reported headcount was {formatCount(ssbf.median_reported_headcount)}. The 2003 survey provides historical measurement examples.</p>
        {link('ssbf', 'Federal Reserve Survey of Small Business Finances')}
      </div>
    </details>
  </div>;
}

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
        {data.benchmarks && <DatasetBenchmarks data={data.benchmarks} />}
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
