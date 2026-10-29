import { useEffect, useState } from 'react';
import { apiErrorMessage, fetchFeatureStudy } from '../api/client.js';
import { validFeatureStudy } from '../lib/featureStudy.js';
import { formatDateTime } from '../lib/format.js';

const labels = { loan_to_income: 'Facility / annual income proxy', payment_history_score: 'Repayment history', years_in_operation: 'Duration proxy' };
const number = value => value.toLocaleString('en-PK');

export default function FeatureEngineering() {
  const [view, setView] = useState({ data: null, error: null }), [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    setView({ data: null, error: null });
    fetchFeatureStudy({ signal: controller.signal }).then(data => {
      if (!validFeatureStudy(data)) throw new Error('UNVERIFIED_FEATURE_STUDY');
      if (alive) setView({ data, error: null });
    }).catch(error => {
      if (alive && !controller.signal.aborted) setView({ data: null, error: error.message === 'UNVERIFIED_FEATURE_STUDY'
        ? 'The feature study is incomplete or inconsistent. Results are withheld. Refresh to try again.'
        : apiErrorMessage(error, 'Could not load verified feature research.') });
    });
    return () => { alive = false; controller.abort(); };
  }, [attempt]);
  const data = view.data;
  const engineeredGain = data ? data.candidates[3].auc_roc_mean - data.candidates[2].auc_roc_mean : null;
  return <section className="card min-w-0" aria-labelledby="feature-study-title" data-testid="feature-study">
    <div className="card-header"><div><h3 id="feature-study-title" className="card-title">Feature engineering: measured results</h3><p className="mt-1 text-xs text-slate-600">Test ideas before changing the credit model.</p></div><span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">Research only</span></div>
    <div className="space-y-4 px-5 py-4">
      {view.error ? <div role="alert"><p className="text-sm text-rose-800">{view.error}</p><button type="button" className="btn-secondary mt-2 text-xs" onClick={() => setAttempt(value => value + 1)}>Retry feature research</button></div>
        : !data ? <p role="status" className="text-sm text-slate-500">Loading measured feature research…</p> : <>
        <p className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-relaxed text-slate-800">Serving model retained. These exploratory comparisons use {number(data.training_rows)} public consumer training rows across {data.folds} shared folds. The {number(data.excluded_validation_rows)} validation and {number(data.excluded_final_test_rows)} previously evaluated final-test rows were excluded from this study.</p>
        <div className="grid gap-3 lg:grid-cols-2"><div className="rounded-xl border border-slate-200 p-3"><h4 className="text-sm font-semibold text-slate-900">Five derived terms, three source inputs</h4><p className="mt-2 text-xs leading-relaxed text-slate-600">Log transforms and interactions changed the simple logistic model's mean ROC-AUC by {engineeredGain >= 0 ? '+' : ''}{engineeredGain.toFixed(4)}. They add no new observed evidence. This does not establish a better replacement for the ensemble.</p></div><div className="rounded-xl border border-slate-200 p-3"><h4 className="text-sm font-semibold text-slate-900">Where more evidence matters</h4><p className="mt-2 text-xs leading-relaxed text-slate-600">{number(data.rows_in_conflicting_vectors)} training rows share the same effective inputs with a row having a different outcome. Three inputs cannot distinguish every case. This does not prove any label is wrong.</p></div></div>
        <details><summary className="text-sm font-semibold text-brand-800">Compare the four measured candidates</summary><div className="mt-3 overflow-x-auto rounded-lg border border-slate-200"><table className="w-full text-left text-xs"><caption className="p-3 text-left text-slate-600">Mean of five training folds. Higher ROC-AUC / PR-AUC and lower Brier are better. ROC-AUC measures ranking, not percentage accuracy. Probabilities here are uncalibrated.</caption><thead><tr className="border-y border-slate-200 bg-slate-50 text-slate-600"><th className="p-3">Candidate</th><th className="p-3">ROC-AUC ± fold SD</th><th className="p-3">PR-AUC</th><th className="p-3">Brier</th><th className="p-3">ROC-AUC change vs current recipe</th></tr></thead><tbody>{data.candidates.map(row => <tr key={row.id} className="border-b border-slate-100"><th scope="row" className="p-3 font-medium text-slate-800">{row.label}</th><td className="whitespace-nowrap p-3 tabular-nums">{row.auc_roc_mean.toFixed(4)} ± {row.auc_roc_std.toFixed(4)}</td><td className="p-3 tabular-nums">{row.pr_auc_mean.toFixed(4)}</td><td className="p-3 tabular-nums">{row.brier_mean.toFixed(4)}</td><td className="p-3 tabular-nums">{row.paired_auc_delta >= 0 ? '+' : ''}{row.paired_auc_delta.toFixed(5)}</td></tr>)}</tbody></table></div><p className="mt-2 text-xs leading-relaxed text-slate-500">Fold SD is variation across folds, not a confidence interval. The folds share fit observations; differences are descriptive and have not passed independent validation.</p></details>
        <details><summary className="text-sm font-semibold text-brand-800">Which inputs the ensemble depends on</summary><div className="mt-3 space-y-2">{data.permutation.map(row => <div key={row.name} className="flex flex-wrap justify-between gap-2 rounded-lg bg-slate-50 p-3 text-xs"><span className="font-medium text-slate-800">{labels[row.name]}</span><span className="tabular-nums text-slate-600">Mean ROC-AUC drop: {row.mean_auc_drop.toFixed(4)}</span></div>)}</div><p className="mt-2 text-xs leading-relaxed text-slate-500">Each input was shuffled three times in each fold's score rows, using its fitted pipeline. Drops show model dependence, not causation, percentages of risk or borrower advice.</p></details>
        <details><summary className="text-sm font-semibold text-brand-800">Categorical history and research limits</summary><div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-600">{data.sampling.map(row => <p key={row.id}>{row.id === 'ensemble_smote' ? 'Current SMOTE recipe' : 'Categorical SMOTENC recipe'}: {number(row.non_category_history_rows)} of {number(row.synthetic_rows)} generated fit observations had a history value outside the two categories. Counts sum across overlapping folds; these are not unique borrowers.</p>)}<p>Terms tested: {data.engineered_features.map(name => name.replaceAll('_', ' ')).join('; ')}.</p><ul className="list-disc space-y-2 pl-4">{data.limitations.map(note => <li key={note}>{note}</li>)}</ul><p>Measured {formatDateTime(data.completed_at)}.</p><p className="break-all text-[11px] text-slate-500">Protocol SHA-256: {data.protocol_sha256}<br />Credit artefacts: {data.credit_artifact_sha256}</p></div></details>
      </>}
    </div>
  </section>;
}
