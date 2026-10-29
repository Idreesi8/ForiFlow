import { useEffect, useRef, useState } from 'react';
import { apiErrorMessage, checkModelInputs } from '../api/client.js';
import { matchesModelInputs, prepareModelInputs } from '../lib/modelInputs.js';
import { formatDateTime, formatPercent } from '../lib/format.js';
import { Spinner } from './common/States.jsx';

const display = (name, value) => name === 'loan_to_income' ? formatPercent(value, 3) : String(Number(value.toFixed(4)));
const initial = { key: null, data: null, error: null, busy: false, stale: false, message: null };

export default function ModelInputCheck({ values, disabled, onFixField }) {
  const prepared = prepareModelInputs(values), key = prepared.key;
  const latestKey = useRef(key); latestKey.current = key;
  const sequence = useRef(0), controller = useRef(null), inFlight = useRef(false);
  const [view, setView] = useState(initial), [attempted, setAttempted] = useState(false);
  useEffect(() => {
    sequence.current += 1; controller.current?.abort(); inFlight.current = false;
    setView(previous => ({ ...previous, data: null, error: null, busy: false, message: null,
      stale: previous.stale || Boolean(previous.data || previous.busy) }));
    return () => { sequence.current += 1; controller.current?.abort(); inFlight.current = false; };
  }, [key, disabled]);
  const current = view.key === key && !disabled;
  const data = current ? view.data : null, busy = current && view.busy;
  const cancel = () => {
    sequence.current += 1; controller.current?.abort(); inFlight.current = false;
    setView({ ...initial, message: 'Input check cancelled. No assessment was saved.' });
  };
  const inspect = async () => {
    if (disabled || inFlight.current) return;
    setAttempted(true);
    if (prepared.errors.length) return;
    const request = ++sequence.current, requestKey = key;
    controller.current?.abort(); controller.current = new AbortController();
    const signal = controller.current.signal;
    inFlight.current = true;
    setView({ ...initial, key: requestKey, busy: true });
    try {
      const result = await checkModelInputs(prepared.inputs, { signal });
      if (signal.aborted || request !== sequence.current || requestKey !== latestKey.current) return;
      if (!matchesModelInputs(result, prepared.inputs)) throw new Error('UNVERIFIED_INPUT_CHECK');
      setView({ ...initial, key: requestKey, data: result });
    } catch (error) {
      if (!signal.aborted && request === sequence.current && requestKey === latestKey.current) {
        setView({ ...initial, key: requestKey, error: error.message === 'UNVERIFIED_INPUT_CHECK'
          ? 'The returned check does not match these figures. Run the check again before using it.'
          : apiErrorMessage(error, 'Could not check the inputs. Your form entries are still here.') });
      }
    } finally { if (request === sequence.current) inFlight.current = false; }
  };
  const anomaly = data?.applicability;
  const clipped = data?.input_checks?.filter(row => row.clipped) || [];
  return <section className="min-w-0 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4" aria-label="Unsaved model input checks" data-testid="model-input-check">
    <div className="flex flex-wrap items-center justify-between gap-3"><div>
      <h3 className="text-sm font-semibold text-slate-900">Check model inputs before saving</h3>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">Inspect unusual inputs and training limits. No score, borrower or assessment is saved.</p>
    </div><button type="button" className="btn-secondary text-xs" onClick={inspect} disabled={disabled || busy}>{busy ? <><Spinner className="h-4 w-4" />Checking inputs…</> : 'Check inputs without saving'}</button></div>
    <p className="text-xs leading-relaxed text-slate-500">Uses loan amount, digital payments, cash flow, repayment history and years trading. Names, CNIC, contact details and statement contents are excluded.</p>
    {attempted && prepared.errors.length ? <div role="alert" className="text-xs text-amber-900"><p>Enter valid figures for these fields, then run the check:</p><div className="mt-2 flex flex-wrap gap-x-4 gap-y-2">{prepared.errors.map(field => <button key={field.name} type="button" className="text-left underline underline-offset-2" onClick={() => onFixField(field.name)}>{field.label}</button>)}</div></div> : null}
    {busy ? <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-slate-600" role="status">Checking only the five financial figures…</p><button type="button" className="btn-secondary text-xs" onClick={cancel}>Cancel input check</button></div> : null}
    {!data && !busy && (view.stale || (view.data && !current)) ? <p role="status" className="text-xs font-medium text-amber-900">Figures changed. Run the input check again for the current entries.</p> : null}
    {view.message ? <p role="status" className="text-xs text-slate-600">{view.message}</p> : null}
    {current && view.error ? <p role="alert" className="text-xs text-rose-800">{view.error}</p> : null}
    {data ? <div className="space-y-3 border-t border-slate-200 pt-3" data-testid="model-input-result" aria-live="polite">
      {data.status === 'unavailable' ? <p className="text-sm text-amber-900">{data.reason}</p> : <>
        <p className="text-xs font-semibold text-slate-700">Unsaved input analysis · {formatDateTime(data.computed_at)}</p>
        {data.reason ? <p className="text-xs text-amber-900">{data.reason}</p> : null}
        {anomaly?.status === 'ready' ? <div className={`rounded-lg border p-3 ${anomaly.atypical ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
          <p className="text-sm font-semibold text-slate-900">{anomaly.atypical ? 'Atypical relative to training inputs' : 'Within the reference threshold'}</p>
          <p className="mt-1 text-xs text-slate-600">Training atypicality percentile: {anomaly.training_percentile.toFixed(2)} / 100 · reference of {anomaly.train_rows.toLocaleString('en-PK')} public consumer training rows.</p>
          <p className="mt-2 text-xs leading-relaxed text-slate-600">Higher percentiles mean more unusual combinations. A flag starts above the training 95th-percentile anomaly score. It is not a default probability, fraud finding or proof of error.</p>
        </div> : <p className="text-xs text-slate-600">{anomaly?.reason}</p>}
        {clipped.length ? <p className="text-xs font-medium text-amber-900">{clipped.length} input{clipped.length === 1 ? '' : 's'} clipped to credit-training limits. Check the source figures; the credit model loses detail beyond those limits.</p> : null}
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white"><table className="w-full text-left text-xs"><caption className="p-3 text-left font-semibold text-slate-800">What the current credit model reads</caption><thead><tr className="border-b border-slate-200 text-slate-500"><th className="p-2">Input</th><th className="p-2">Entered / derived</th><th className="p-2">Model reads</th><th className="p-2">Transformation</th></tr></thead><tbody>{data.input_checks.map(row => <tr key={row.name} className="border-b border-slate-100"><td className="p-2">{row.label}</td><td className="p-2">{display(row.name, row.entered)}</td><td className="p-2">{display(row.name, row.model_value)}</td><td className="p-2">{row.transformation.replaceAll('_', ' ')}</td></tr>)}</tbody></table></div>
        <p className="text-xs leading-relaxed text-slate-600">The turnover proxy is 12 × max(digital payments, cash flow). Repayment history is read as two encoded levels, not a continuous bureau measurement.</p>
        <p className="text-xs leading-relaxed text-slate-600">Training used personal income and employment duration. Their use as business turnover and years trading is an unvalidated SME analogy.</p>
        {data.inputs.monthly_digital_payments === 0 && data.inputs.cash_flow_proxy === 0 ? <p className="text-xs font-medium text-amber-900">Both monthly cash figures are zero. The model substitutes 999 for the ratio before clipping; this is not an observed facility-to-turnover ratio.</p> : null}
        <p className="text-xs leading-relaxed text-slate-600">These checks do not verify financial evidence or validate lending to Pakistani SMEs. Scoring and saving the full assessment is a separate action.</p>
        <details><summary className="text-xs font-semibold text-slate-700">Model reference and limits</summary><p className="mt-2 break-all text-xs text-slate-500">Model: {data.model_version}<br />Credit artefacts: {data.credit_artifact_sha256}<br />Anomaly reference: {anomaly?.reference_sha256 || 'Unavailable'}</p><ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-slate-500">{data.notes.map(note => <li key={note}>{note}</li>)}</ul></details>
      </>}
    </div> : null}
  </section>;
}
