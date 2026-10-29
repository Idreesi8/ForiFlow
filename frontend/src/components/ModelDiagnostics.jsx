import { useEffect, useRef, useState } from "react";
import { apiErrorMessage, fetchModelDiagnostics } from "../api/client.js";
import { formatDateTime, formatPKRExact, formatPercent, formatSigned } from "../lib/format.js";
import { ErrorState, LoadingState } from "./common/States.jsx";

const FACTORS = [0.8, 0.9, 1, 1.1, 1.2];
const factorLabel = value => value === 1 ? 'Recorded amount' : `${Math.round(Math.abs(value - 1) * 100)}% ${value < 1 ? 'lower' : 'higher'}`;
const inputValue = (name, value) => name === 'loan_to_income' ? formatPercent(value, 3) : `${Number(value.toFixed(4))}${name === 'years_in_operation' ? ' years' : ''}`;

export default function ModelDiagnostics({ applicationId }) {
  const [expanded, setExpanded] = useState(false);
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState({ loading: false, data: null, error: null });
  const [loan, setLoan] = useState(1);
  const [receipts, setReceipts] = useState(1);
  const sequence = useRef(0);
  useEffect(() => {
    if (!expanded) return;
    const request = ++sequence.current;
    const controller = new AbortController();
    setView({ loading: true, data: null, error: null });
    fetchModelDiagnostics(applicationId, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted || request !== sequence.current) return;
      if (data.application_id !== applicationId || (data.status !== 'unavailable' && data.source_verified !== true)) {
        setView({ loading: false, data: null, error: 'The returned ML checks could not be verified for this case. Refresh before using them.' });
      } else setView({ loading: false, data, error: null });
    }).catch(error => {
      if (!controller.signal.aborted && request === sequence.current) setView({ loading: false, data: null, error: apiErrorMessage(error, 'Could not load model checks.') });
    });
    return () => { sequence.current += 1; controller.abort(); };
  }, [expanded, applicationId, revision]);
  const data = view.data;
  const selected = data?.scenarios?.find(row => row.loan_factor === loan && row.receipts_factor === receipts);
  const rows = data?.scenarios?.filter(row => row.loan_factor === loan) || [];
  const clipped = data?.input_checks?.filter(row => row.clipped) || [];
  const novelty = data?.applicability;

  return <section className="border-t border-slate-200" data-testid="model-diagnostics" aria-label="Model checks and what-if">
    <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
      <div><h4 className="text-sm font-semibold text-slate-900">Model checks &amp; what-if</h4><p className="mt-1 text-xs leading-relaxed text-slate-500">Inspect unusual inputs, learner disagreement and hypothetical score changes.</p></div>
      <button type="button" className="btn-secondary text-xs" aria-expanded={expanded} aria-controls={`model-checks-${applicationId}`} onClick={() => setExpanded(value => !value)}>{expanded ? 'Hide model checks' : 'Inspect model behaviour'}</button>
    </div>
    {expanded ? <div id={`model-checks-${applicationId}`} className="space-y-5 px-5 pb-5">
      {view.loading ? <LoadingState label="Checking this case against its model…" /> : view.error ? <ErrorState message={view.error} onRetry={() => setRevision(value => value + 1)} /> : data?.status === 'unavailable' ? <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" role="status">{data.reason}</p> : data ? <>
        <p className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">Credit-model artefacts verified. The recomputed score matches the saved {data.stored_score.toFixed(2)} / 100. These checks support an officer’s review; they do not change this case.</p>
        {data.reason ? <p className="text-sm text-amber-800">{data.reason}</p> : null}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className={`min-w-0 rounded-xl border p-4 ${novelty?.atypical ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'}`} data-testid="input-applicability">
            <h5 className="text-sm font-semibold text-slate-900">Input applicability</h5>
            {novelty?.status === 'ready' ? <>
              <p className="mt-2 text-lg font-bold text-slate-900">{novelty.atypical ? 'Atypical relative to training inputs' : 'Within the reference threshold'}</p>
              <p className="mt-2 text-sm text-slate-700">Training atypicality percentile: <strong>{novelty.training_percentile.toFixed(2)}</strong> / 100</p>
              <p className="mt-2 text-xs leading-relaxed text-slate-600">Isolation Forest compares the input combination with {novelty.train_rows.toLocaleString('en-PK')} original public training rows. Higher percentiles mean more unusual inputs. The flag starts above the training 95th-percentile anomaly score.</p>
              <p className="mt-2 text-xs font-medium leading-relaxed text-slate-700">This is not a default probability or a finding of fraud or error. Being within this reference does not validate the model for Pakistani SMEs.</p>
            </> : <p className="mt-2 text-sm text-slate-600">{novelty?.reason || 'Input-anomaly checks are unavailable.'}</p>}
          </div>
          <div className="min-w-0 rounded-xl border border-slate-200 p-4" data-testid="ensemble-disagreement">
            <h5 className="text-sm font-semibold text-slate-900">Learner disagreement</h5>
            <p className="mt-2 text-sm text-slate-700">Raw default-probability spread: <strong>{data.member_spread_pp.toFixed(2)} percentage points</strong></p>
            <div className="mt-3 space-y-3">{data.members.map(member => <div key={member.name}>
              <div className="flex flex-wrap justify-between gap-2 text-xs"><span className="font-semibold">{member.label} · {formatPercent(member.weight, 0)} weight</span><span>Score {member.score.toFixed(2)} / 100</span></div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-sky-700" style={{ width: `${member.score}%` }} /></div>
            </div>)}</div>
            <p className="mt-3 text-xs leading-relaxed text-slate-500">Both learners use the same training data. Agreement does not prove correctness; the spread is not a confidence interval. These are raw model probabilities, not calibrated SME default rates.</p>
          </div>
        </div>
        {clipped.length ? <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{clipped.length} model input{clipped.length === 1 ? '' : 's'} clipped to training limits. Beyond those limits the credit score loses input detail; verify the source figures.</p> : null}
        <div className="rounded-xl border border-slate-200 p-4" data-testid="ml-scenarios">
          <div className="flex flex-wrap items-end justify-between gap-3"><div><h5 className="text-sm font-semibold text-slate-900">ML sensitivity explorer</h5><p className="mt-1 text-xs text-slate-500">25 actual ensemble predictions around the recorded inputs. No save or new assessment.</p></div>
            <label className="text-xs font-medium text-slate-600">Loan size scenario<select aria-label="Loan size scenario" className="field-input mt-1 py-2 text-sm" value={loan} onChange={event => setLoan(Number(event.target.value))}>{FACTORS.map(factor => <option key={factor} value={factor}>{factorLabel(factor)}</option>)}</select></label>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5" role="group" aria-label="Receipts scenarios">{rows.map(row => <button key={row.receipts_factor} type="button" aria-pressed={receipts === row.receipts_factor} onClick={() => setReceipts(row.receipts_factor)} className={`min-w-0 rounded-xl border p-3 text-left ${receipts === row.receipts_factor ? 'border-brand-600 bg-brand-50 ring-1 ring-brand-600' : 'border-slate-200 hover:bg-slate-50'}`}>
            <span className="block text-xs text-slate-600">Receipts: {factorLabel(row.receipts_factor).toLowerCase()}</span><strong className="mt-2 block text-xl text-slate-900">{row.score.toFixed(2)}</strong><span className="mt-1 block text-xs text-slate-500">{row.recommendation || 'Policy unavailable'}</span>
          </button>)}</div>
          {selected ? <div className="mt-4 rounded-xl bg-slate-50 p-4 text-sm text-slate-700" aria-live="polite">
            <p className="font-semibold text-slate-900">Scenario score {selected.score.toFixed(2)} / 100 · {formatSigned(selected.score_change)} points from recorded</p>
            <dl className="mt-3 grid gap-3 sm:grid-cols-3"><ScenarioFact label="Hypothetical loan">{formatPKRExact(selected.loan_amount_pkr)}</ScenarioFact><ScenarioFact label="Monthly digital receipts">{formatPKRExact(selected.monthly_digital_payments)}</ScenarioFact><ScenarioFact label="Monthly cash-flow proxy">{formatPKRExact(selected.cash_flow_proxy)}</ScenarioFact></dl>
            {selected.recommendation_changed ? <p className="mt-3 font-medium text-amber-900">The recorded policy recommendation changes in this scenario. It is not an officer decision or an offer.</p> : null}
          </div> : null}
          <p className="mt-3 text-xs font-medium leading-relaxed text-slate-700">The officer decision below applies to the recorded loan and assessment. These scenario controls leave that record unchanged.</p>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">{data.scenario_note}</p><p className="mt-2 text-xs leading-relaxed text-slate-500">{data.policy_note} The range across scenarios is not a confidence interval or a forecast.</p>
        </div>
        <details className="rounded-xl border border-slate-200 p-4"><summary className="text-sm font-semibold text-slate-900">Exact model inputs and provenance</summary>
          <div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500"><th className="p-2">Feature</th><th className="p-2">Entered / derived</th><th className="p-2">Model reads</th><th className="p-2">Transformation</th><th className="p-2">Training input limits</th></tr></thead><tbody>{data.input_checks.map(row => <tr key={row.name} className="border-b border-slate-100"><td className="p-2">{row.label}</td><td className="p-2">{inputValue(row.name, row.entered)}</td><td className="p-2">{inputValue(row.name, row.model_value)}</td><td className="p-2">{row.transformation.replaceAll('_', ' ')}</td><td className="p-2">{row.transformation.endsWith('history') ? 'Two encoded levels: ' : ''}{inputValue(row.name, row.training_lower)} / {inputValue(row.name, row.training_upper)}</td></tr>)}</tbody></table></div>
          <p className="mt-3 text-xs leading-relaxed text-slate-500">Repayment history is encoded into the two levels supported by the training data; it is not a continuous bureau measurement. Other model inputs use the recorded training clip limits.</p>
          <p className="mt-3 break-all text-xs text-slate-500">Credit model: {data.recorded_model_version}<br />Credit artefacts: {data.credit_artifact_sha256}<br />Anomaly reference: {novelty?.reference_sha256 || 'Unavailable'}<br />Checked: {formatDateTime(data.computed_at)}</p>
          <ul className="mt-3 list-disc space-y-2 pl-4 text-xs leading-relaxed text-slate-500">{data.limitations.map(note => <li key={note}>{note}</li>)}</ul>
        </details>
        <button type="button" className="btn-secondary text-xs" onClick={() => setRevision(value => value + 1)}>Refresh model checks</button>
      </> : null}
    </div> : null}
  </section>;
}

function ScenarioFact({ label, children }) {
  return <div className="min-w-0"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words font-semibold">{children}</dd></div>;
}

export function ApplicabilityModelCard({ data }) {
  return <section className="card min-w-0" data-testid="applicability-model-card"><div className="card-header"><h3 className="card-title">Input-anomaly model</h3><span className="text-xs text-slate-500">Additional model · {data?.status === 'ready' ? 'Available' : 'Unavailable'}</span></div><div className="space-y-3 px-5 py-4 text-sm text-slate-700">
    {data?.status === 'ready' ? <>
      <p><strong>{data.n_estimators}-tree Isolation Forest</strong>, linked to the exact credit-model artefacts.</p>
      <p>{data.train_rows.toLocaleString('en-PK')} original training rows · {data.validation_rows.toLocaleString('en-PK')} validation rows · final test not used.</p>
      <p>Descriptive validation flag rate: <strong>{formatPercent(data.validation_flagged / data.validation_rows, 2)}</strong>. The threshold was fixed at the training 95th-percentile anomaly score; this rate is not detection accuracy.</p>
      <p className="text-xs leading-relaxed text-slate-500">Looks for unusual input combinations relative to public consumer credit data. It does not predict default or validate the model for Pakistani SME lending. Open a saved assessment’s Model checks &amp; what-if panel to inspect its result.</p>
      <details><summary className="text-xs font-semibold">Reference provenance</summary><p className="mt-2 break-all text-xs text-slate-500">Trained: {formatDateTime(data.trained_at)}<br />Seed: {data.random_seed}<br />Training rows: {data.train_ids_sha256}<br />Reference: {data.reference_sha256}<br />Credit model: {data.credit_model_version}</p></details>
    </> : <p>{data?.reason || 'The input-anomaly model could not be loaded.'}</p>}
  </div></section>;
}
