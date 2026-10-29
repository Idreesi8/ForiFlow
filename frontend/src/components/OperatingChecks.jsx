import { useEffect, useRef, useState } from 'react';
import { apiErrorMessage, checkOperatingFigures, fetchOperatingFigures } from '../api/client.js';
import { OPERATING_FIELDS, matchesOperatingReport, prepareOperatingInputs } from '../lib/operatingChecks.js';
import { formatPKRExact } from '../lib/format.js';
import { Spinner } from './common/States.jsx';

const initial = { key: null, data: null, busy: false, error: null, stale: false };
const display = row => row.value === null ? 'Unavailable' : row.unit === 'PKR' ? formatPKRExact(row.value) : `${row.value.toLocaleString('en-PK', { maximumFractionDigits: 3 })}${row.unit === 'ratio' ? '×' : row.unit === 'days' ? ' days' : ' points'}`;

export default function OperatingChecks({ values, statement = null, applicationId = null, disabled = false, onFixField }) {
  const prepared = prepareOperatingInputs(values, statement);
  const key = applicationId ? JSON.stringify([applicationId, values.loan_amount_pkr, values.tenure_months]) : prepared.key;
  const latest = useRef(key); latest.current = key;
  const sequence = useRef(0), controller = useRef(null), inFlight = useRef(false);
  const [view, setView] = useState(initial), [attempted, setAttempted] = useState(false);
  const empty = !applicationId && OPERATING_FIELDS.every(name => !String(values[name] ?? '').trim());
  useEffect(() => {
    sequence.current += 1; controller.current?.abort(); inFlight.current = false;
    setView(previous => ({ ...initial, stale: previous.stale || Boolean(previous.data || previous.busy) }));
    return () => { sequence.current += 1; controller.current?.abort(); inFlight.current = false; };
  }, [key, disabled]);
  useEffect(() => {
    if (empty) { setAttempted(false); setView(initial); }
  }, [empty]);
  const current = view.key === key && !disabled;
  const data = current ? view.data : null, busy = current && view.busy;
  const inspect = async () => {
    if (disabled || inFlight.current) return;
    setAttempted(true);
    if (!applicationId && prepared.errors.length) return;
    const request = ++sequence.current, requestKey = key;
    controller.current?.abort(); controller.current = new AbortController();
    const signal = controller.current.signal;
    inFlight.current = true;
    setView({ ...initial, key, busy: true });
    try {
      const result = applicationId ? await fetchOperatingFigures(applicationId, { signal }) : await checkOperatingFigures(prepared.payload, { signal });
      if (signal.aborted || request !== sequence.current || requestKey !== latest.current) return;
      // Case summaries expose amount/term but not all recorded alternative-data
      // fields. The case-specific read provides the rest; verify its case and
      // those two displayed anchors before accepting it.
      const expected = applicationId ? result.inputs : prepared.inputs;
      if ((applicationId && ['loan_amount_pkr', 'tenure_months'].some(name => result.inputs?.[name] !== values[name])) || !matchesOperatingReport(result, expected, applicationId, statement)) throw new Error('MISMATCHED_OPERATING_REPORT');
      setView({ ...initial, key, data: result });
    } catch (error) {
      if (!signal.aborted && request === sequence.current && requestKey === latest.current) setView({ ...initial, key, error: error.message === 'MISMATCHED_OPERATING_REPORT'
        ? applicationId ? 'These checks do not match the displayed case. Refresh the case and try again.' : 'These checks do not match the current figures. Run the check again; your entries are still here.'
        : !error.response ? 'The business check did not finish. Your entries are still here; run the check again when the service is reachable.'
        : apiErrorMessage(error, 'Could not check the business figures.') });
    } finally { if (request === sequence.current) inFlight.current = false; }
  };
  return <section className="min-w-0 space-y-3 rounded-xl border border-brand-200 bg-brand-50/40 p-4" aria-label="Business figures checks" data-testid="operating-checks">
    <div className="flex flex-wrap items-start justify-between gap-3"><div>
      <h3 id={applicationId ? `operating-checks-${applicationId}` : 'operating-checks-title'} tabIndex={-1} className="scroll-mt-28 text-sm font-semibold text-slate-900">Put the business figures to work</h3>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">Tenure, debt, stock turnover, consistency and headcount power separate operating checks. They do not add trained features to the ML score.</p>
    </div><button type="button" disabled={disabled || busy} className="btn-secondary text-xs" onClick={inspect}>{busy ? <><Spinner className="h-4 w-4" />Checking business figures…</> : 'Check business figures'}</button></div>
    <p className="text-xs text-slate-600">{applicationId ? `Uses recorded figures from case #${applicationId}; calculated now, separately from its saved score.` : 'Checks stay unsaved. Identity and contact fields are excluded. An attached statement is reread locally by ForiFlow for the consistency comparison.'}</p>
    {!applicationId && attempted && prepared.errors.length ? <div role="alert" className="text-xs text-amber-950"><p>Complete these figures first:</p><div className="mt-2 flex flex-wrap gap-3">{prepared.errors.map(field => onFixField ? <button type="button" key={field.name} className="underline underline-offset-2" onClick={() => onFixField(field.name)}>{field.label}</button> : <span key={field.name}>{field.label}</span>)}</div></div> : null}
    {!data && !busy && view.stale ? <p role="status" className="text-xs text-amber-950">Figures or evidence changed. Run the business checks again.</p> : null}
    {current && view.error ? <p role="alert" className="text-xs text-rose-800">{view.error}</p> : null}
    {data ? <div className="space-y-3 border-t border-brand-200 pt-3" data-testid="operating-result" aria-live="polite">
      <div className="grid gap-3 sm:grid-cols-2">{data.metrics.filter(row => row.name !== 'order_consistency_gap').map(row => <div key={row.name} className="min-w-0 rounded-lg border border-slate-200 bg-white p-3">
        <p className="text-xs text-slate-600">{row.label}</p><p className="mt-1 break-words text-base font-semibold tabular-nums text-slate-900">{display(row)}</p><p className="mt-1 text-xs leading-relaxed text-slate-500">{row.note}</p>
      </div>)}</div>
      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <h4 className="text-sm font-semibold text-slate-900">Consistency evidence</h4>
        <p className="mt-1 text-xs text-slate-700">Entered order consistency: {data.inputs.order_consistency} / 100.</p>
        {data.order_source === 'statement_receipts_proxy' ? <p className="mt-1 text-xs leading-relaxed text-slate-600">Statement receipts-stability proxy: {data.receipt_consistency_reference} / 100 across {data.statement_full_months} full months. Difference: {display(data.metrics.find(row => row.name === 'order_consistency_gap'))}. Receipts are not orders; this does not verify the order book.</p> : <p className="mt-1 text-xs leading-relaxed text-slate-600">Officer-entered estimate. No verifiable statement summary supports a receipts comparison. Verify order volumes from an order ledger.</p>}
      </div>
      <details><summary className="text-xs font-semibold text-brand-800">How the checks work and what they exclude</summary><dl className="mt-3 space-y-2 text-xs text-slate-600">{data.metrics.map(row => <div key={row.name}><dt className="font-semibold">{row.label}</dt><dd>{row.formula}</dd></div>)}</dl><ul className="mt-3 list-disc space-y-2 pl-4 text-xs text-slate-600">{data.notes.map(note => <li key={note}>{note}</li>)}</ul></details>
    </div> : null}
  </section>;
}
