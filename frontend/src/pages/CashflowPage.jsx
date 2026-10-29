import { useEffect, useRef, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { analyseCashflow, apiErrorMessage } from '../api/client.js';
import { matchesCashflowReport, METHOD_LABELS, statementFingerprint, syntheticCashflowCSV } from '../lib/cashflowIntelligence.js';
// Keep the displayed tables and errors at the server's paisa precision.
import { formatPKRExact as formatPKR, formatDateTime } from '../lib/format.js';
import { useUnsavedWork } from '../components/UnsavedWork.jsx';

const empty = { data: null, error: null, busy: null, message: null };

export default function CashflowPage() {
  const [csv, setCSV] = useState(''), [label, setLabel] = useState(''), [view, setView] = useState(empty);
  const [dateOrder, setDateOrder] = useState('auto');
  const controller = useRef(null), sequence = useRef(0), inFlight = useRef(false), resultHeading = useRef(null), fileInput = useRef(null), editor = useRef(null);
  useUnsavedWork({ label: 'Cash-flow statement analysis', dirty: Boolean(csv), busy: Boolean(view.busy) });
  useEffect(() => () => { sequence.current++; controller.current?.abort(); }, []);
  useEffect(() => { if (view.data) resultHeading.current?.focus(); }, [view.data]);
  const invalidate = () => { sequence.current++; controller.current?.abort(); inFlight.current = false; };
  const change = text => { invalidate(); setCSV(text); setLabel('Pasted or edited CSV'); setView({ ...empty, message: csv ? 'Statement changed. Analyse the current contents again.' : null }); };
  const clear = () => { invalidate(); setCSV(''); setDateOrder('auto'); setLabel(''); setView(empty); if (fileInput.current) fileInput.current.value = ''; editor.current?.focus(); };
  const loadExample = () => { if (csv) return; invalidate(); setCSV(syntheticCashflowCSV()); setDateOrder('auto'); setLabel('Synthetic example · 36 months · not real financial records'); setView(empty); };
  const changeDateOrder = value => { invalidate(); setDateOrder(value); setView({ ...empty, message: csv ? 'Date format changed. Analyse the current source again.' : null }); };
  const pick = async event => {
    const file = event.target.files?.[0]; if (!file) return;
    invalidate(); const request = sequence.current;
    if (file.size > 2_000_000) { setView({ ...empty, error: 'The file exceeds 2 MB. Export a shorter period. Existing contents are retained.' }); return; }
    setView({ ...empty, busy: 'file' });
    try {
      const contents = await file.text();
      if (request !== sequence.current) return;
      setCSV(contents); setDateOrder('auto'); setLabel(file.name); setView(empty);
    } catch { if (request === sequence.current) setView({ ...empty, error: 'Could not read the file. Existing contents are retained.' }); }
    finally { event.target.value = ''; }
  };
  const cancel = () => { invalidate(); setView({ ...empty, message: 'Analysis cancelled. Your statement contents are still here.' }); };
  const analyse = async event => {
    event.preventDefault();
    if (inFlight.current) return;
    if (!csv.trim()) { setView({ ...empty, error: 'Choose or paste a statement CSV first.' }); editor.current?.focus(); return; }
    if (csv.length > 2_000_000) { setView({ ...empty, error: 'The CSV exceeds the supported size. Export a shorter period.' }); return; }
    invalidate(); const request = sequence.current, source = csv;
    inFlight.current = true; controller.current = new AbortController(); const signal = controller.current.signal;
    setView({ ...empty, busy: 'analysis' });
    try {
      const hash = await statementFingerprint(source);
      if (request !== sequence.current || signal.aborted) return;
      const data = await analyseCashflow(source, dateOrder, { signal });
      if (request !== sequence.current || signal.aborted) return;
      if (!matchesCashflowReport(data, hash, dateOrder)) throw new Error('UNVERIFIED_CASHFLOW');
      setView({ ...empty, data });
    } catch (error) {
      if (request === sequence.current && !signal.aborted) setView({ ...empty, error: error.message === 'UNVERIFIED_CASHFLOW'
        ? 'The returned analysis does not match this source or method. Results are withheld. Try analysing again.'
        : apiErrorMessage(error, 'Could not analyse the statement. Your contents are retained; try again.') });
    } finally { if (request === sequence.current) inFlight.current = false; }
  };
  return <div className="min-w-0 space-y-6">
    <header><h2 className="text-xl font-bold text-slate-900">Cash-flow Intelligence</h2><p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">Understand receipts over time, compare forecasting methods and see how the estimate behaved on later months.</p></header>
    <div className="rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm leading-relaxed text-brand-950">Local statistical analysis on this laptop. No third-party AI service, saved assessment, credit score or lending decision. Receipts are not verified sales.</div>
    <form onSubmit={analyse} className="card min-w-0" aria-label="Cash-flow statement input">
      <div className="card-header"><h3 className="card-title">Start with a statement</h3><span className="text-xs text-slate-500">CSV · PKR</span></div>
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm leading-relaxed text-slate-600">Use 3–120 retained calendar months for historical analysis. A forecast needs at least 30, with no unreadable rows or months without readable transactions. Do not convert foreign amounts to PKR by relabelling them.</p>
        <div className="flex flex-wrap gap-3"><label className={`btn-secondary cursor-pointer text-xs ${view.busy === 'file' ? 'opacity-50' : ''}`}>Choose CSV file<input ref={fileInput} type="file" accept=".csv,text/csv" className="sr-only" onChange={pick} disabled={view.busy === 'file'} /></label><button type="button" className="btn-secondary text-xs" onClick={loadExample} disabled={Boolean(csv) || Boolean(view.busy)}>Load synthetic example</button></div>
        {label ? <p className="break-all text-xs font-medium text-slate-700">Source: {label}</p> : null}
        <div className="max-w-xl"><label htmlFor="cashflow-date-order" className="mb-2 block text-sm font-semibold text-slate-800">Numeric date format</label><select id="cashflow-date-order" className="field-input w-full" value={dateOrder} onChange={event => changeDateOrder(event.target.value)} disabled={view.busy === 'file'} aria-describedby="cashflow-date-help"><option value="auto">Automatic — refuse dates that need a guess</option><option value="day_first">Day / Month / Year</option><option value="month_first">Month / Day / Year</option></select><p id="cashflow-date-help" className="mt-2 text-xs leading-relaxed text-slate-500">For 03/04/2026, choose the convention used by the source. Automatic mode requires an unambiguous clue elsewhere in the file. ISO dates (YYYY-MM-DD) and named months are unchanged. A newly chosen file resets this setting.</p></div>
        <div><label htmlFor="cashflow-csv" className="mb-2 block text-sm font-semibold text-slate-800">Statement CSV contents</label><textarea ref={editor} id="cashflow-csv" className="field-input min-h-40 w-full font-mono text-xs" rows={7} value={csv} maxLength={2_000_000} onChange={event => change(event.target.value)} disabled={view.busy === 'file'} spellCheck={false} autoComplete="off" placeholder={'date,type,amount\n2026-01-02,CR,120000\n2026-01-27,DR,70000'} aria-describedby="cashflow-input-help" /><p id="cashflow-input-help" className="mt-2 text-xs leading-relaxed text-slate-500">Typical columns: date, type (CR/DR), amount; or date, credit, debit. Contents stay in this tab and go only to ForiFlow's local backend when analysed. They are not saved to the case database. Clear this draft before loading the example.</p></div>
        {view.error ? <p role="alert" className="text-sm text-rose-800">{view.error}</p> : null}
        {view.message ? <p role="status" className="text-xs text-slate-600">{view.message}</p> : null}
        <div className="flex flex-wrap items-center gap-3"><button type="submit" className="btn-primary" disabled={Boolean(view.busy)}>{view.busy ? 'Analysing…' : 'Analyse cash flow'}</button>{view.busy ? <button type="button" className="btn-secondary" onClick={cancel}>Cancel analysis</button> : <button type="button" className="btn-ghost text-xs" onClick={clear} disabled={!csv}>Clear statement</button>}</div>
      </div>
    </form>
    {view.data ? <CashflowResults data={view.data} headingRef={resultHeading} /> : null}
  </div>;
}

function CashflowResults({ data, headingRef }) {
  const f = data.forecast, ready = f.status === 'ready';
  const chart = data.series.map(row => ({ ...row, tested: ready ? f.test_months.find(point => point.month === row.month)?.predicted_pkr : null }));
  return <section className="card min-w-0" data-testid="cashflow-result" aria-labelledby="cashflow-result-title">
    <div className="card-header"><div><h3 ref={headingRef} tabIndex={-1} id="cashflow-result-title" className="card-title outline-none">Your statement, over time</h3><p className="mt-1 text-xs text-slate-600">{data.first_month} to {data.last_month} · {data.observations} retained months · {formatDateTime(data.computed_at)}</p></div></div>
    <div className="space-y-5 px-5 py-4">
      {data.warnings.length ? <details className="rounded-lg border border-amber-200 bg-amber-50 p-3" open><summary className="text-sm font-semibold text-amber-950">Source checks and dates</summary><ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed text-amber-950">{data.warnings.map((note, i) => <li key={i}>{note}</li>)}</ul></details> : null}
      <SourceQuality data={data.source_quality} />
      <div className="grid gap-3 sm:grid-cols-3"><Metric label={`Robust trend · latest ${data.trend_window_months} months`} value={`${data.trend_slope_pkr_per_month >= 0 ? '+' : ''}${formatPKR(data.trend_slope_pkr_per_month)} / month`} /><Metric label="Recent 3 vs previous 3 · median receipts" value={data.recent_three_vs_previous_three_percent === null ? 'Not available' : `${data.recent_three_vs_previous_three_percent >= 0 ? '+' : ''}${data.recent_three_vs_previous_three_percent.toFixed(2)}%`} /><Metric label="Months with outflows above inflows" value={`${data.negative_net_months} of ${data.observations}`} /></div>
      <div role="img" aria-label="Monthly receipts and later-month backtested estimates; exact values are available in the tables below." className="min-w-0" style={{height:280}}><ResponsiveContainer width="100%" height="100%"><LineChart data={chart} margin={{top:15,right:12,left:0,bottom:12}}><CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" /><XAxis dataKey="month" tick={{fontSize:10}} minTickGap={35} /><YAxis width={66} tick={{fontSize:10}} tickFormatter={v => `${Math.round(v/1000)}k`} /><Tooltip formatter={value => formatPKR(value)} /><Legend wrapperStyle={{fontSize:11}} /><Line dataKey="inflow" name="Recorded receipts (PKR)" stroke="#2d8560" dot={false} isAnimationActive={false} /><Line dataKey="tested" name="One-step backtest (PKR)" stroke="#a16207" strokeDasharray="5 4" connectNulls={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
      {data.omitted_chart_months ? <p className="text-xs text-slate-500">Chart and history table show the latest 36 months; {data.omitted_chart_months} earlier months are omitted from this view.</p> : null}
      {!ready ? <div className="rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="cashflow-withheld"><h4 className="text-sm font-semibold text-slate-900">Forecast withheld</h4><p className="mt-2 text-sm leading-relaxed text-slate-600">{f.reason}</p></div> : <div className="space-y-4" data-testid="cashflow-forecast">
        <div className="rounded-xl border border-brand-200 bg-brand-50 p-4"><h4 className="text-sm font-semibold text-brand-950">Receipt estimate for source month {f.next_month}</h4><p className="mt-1 text-xs text-brand-900">Method selected on six earlier development months: {METHOD_LABELS[f.selected_method]}.</p><div className="mt-4 grid gap-4 sm:grid-cols-2"><Metric label="One-month point estimate" value={formatPKR(f.predicted_pkr)} /><Metric label="Empirical past-error range" value={`${formatPKR(f.lower_pkr)} – ${formatPKR(f.upper_pkr)}`} /></div><p className="mt-3 text-xs leading-relaxed text-brand-950">The range uses the largest error in six separate calibration months. It has no guaranteed future coverage. Zero width means only zero errors in that short past window. This estimates receipts, not profit or repayment capacity.</p></div>
        <div className="grid gap-3 sm:grid-cols-3"><Metric label="Later 6 months · average absolute error" value={formatPKR(f.test_mae_pkr)} /><Metric label="Same test · last-month baseline error" value={formatPKR(f.baseline_test_mae_pkr)} /><Metric label="Later test months inside error band" value={`${f.test_months_inside_band} of 6`} /></div>
        <p className="text-xs leading-relaxed text-slate-600">{f.test_mae_pkr < f.baseline_test_mae_pkr ? 'The selected method had lower average error than the simple baseline on these six later months.' : f.test_mae_pkr > f.baseline_test_mae_pkr ? 'The selected method had higher average error than the simple baseline on these six later months. Treat the estimate with particular caution.' : 'The selected method and simple baseline had the same displayed average error on these six later months.'} Six observations do not establish future accuracy.</p>
        <details><summary className="text-sm font-semibold text-brand-800">Verify the chronological backtest</summary><p className="mt-3 text-xs leading-relaxed text-slate-600">Development: {f.development_months[0]}–{f.development_months.at(-1)}. Separate calibration: {f.calibration_months[0]}–{f.calibration_months.at(-1)}. Method and range frozen before the six evaluation months below; each forecast reads earlier months only.</p><div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">Independent later-month comparison in PKR</caption><thead><tr>{['Month','Observed receipts','Predicted','Last-month baseline','Past-error range'].map(label=><th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{f.test_months.map(row=><tr key={row.month} className="border-t border-slate-200"><th scope="row" className="whitespace-nowrap p-2 font-medium">{row.month}</th><td className="p-2">{formatPKR(row.observed_pkr)}</td><td className="p-2">{formatPKR(row.predicted_pkr)}</td><td className="p-2">{formatPKR(row.baseline_pkr)}</td><td className="p-2">{formatPKR(row.lower_pkr)}–{formatPKR(row.upper_pkr)}</td></tr>)}</tbody></table></div><h5 className="mt-4 text-xs font-semibold text-slate-800">Development comparison · average absolute error</h5><ul className="mt-2 space-y-1 text-xs text-slate-600">{f.candidates.map(row=><li key={row.method}>{METHOD_LABELS[row.method]}: {formatPKR(row.development_mae_pkr)}</li>)}</ul></details>
      </div>}
      <details><summary className="text-sm font-semibold text-brand-800">Retained monthly figures</summary><div className="mt-3 max-h-80 overflow-auto"><table className="w-full text-left text-xs"><caption className="sr-only">Retained statement months</caption><thead><tr>{['Month','Receipts (PKR)','Outflows (PKR)','Transactions'].map(label=><th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{data.series.map(row=><tr key={row.month} className="border-t border-slate-200"><th scope="row" className="whitespace-nowrap p-2 font-medium">{row.month}</th><td className="p-2">{formatPKR(row.inflow)}</td><td className="p-2">{formatPKR(row.outflow)}</td><td className="p-2">{row.transactions}</td></tr>)}</tbody></table></div></details>
      <details><summary className="text-sm font-semibold text-brand-800">How this works and where it can fail</summary><ul className="mt-3 list-disc space-y-2 pl-4 text-xs leading-relaxed text-slate-600">{data.notes.map(note=><li key={note}>{note}</li>)}</ul><p className="mt-3 break-all text-[11px] text-slate-500">Method: {data.method_version} · parser: {data.parser_version}<br />Decoded source SHA-256: {data.source_sha256}</p></details>
    </div>
  </section>;
}

function Metric({label,value}) { return <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-3"><p className="text-xs leading-relaxed text-slate-500">{label}</p><p className="mt-2 break-words text-sm font-semibold text-slate-900 tabular-nums">{value}</p></div>; }

function SourceQuality({data}) {
  const names = {auto:'Automatic',day_first:'Day / Month / Year',month_first:'Month / Day / Year',iso_or_named:'ISO or named-month dates',identical_day_month:'Day and month give the same date'};
  return <section className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-labelledby="source-quality-title" data-testid="cashflow-source-quality"><h4 id="source-quality-title" className="text-sm font-semibold text-slate-900">Source quality & date interpretation</h4><div className="mt-3 grid gap-3 sm:grid-cols-3"><Metric label="Date convention used" value={names[data.date_order_resolved]} /><Metric label="Numeric dates needing a convention" value={`${data.ambiguous_numeric_rows} of ${data.source_rows} source rows`} /><Metric label="Repeated row candidates · retained" value={String(data.repeated_row_candidates)} /></div><p className="mt-3 text-xs leading-relaxed text-slate-600">Requested: {names[data.date_order_requested]}. Repeated rows have identical cell values, which can be legitimate transactions. No rows were deleted and no fraud finding is made.</p><details className="mt-3"><summary className="text-xs font-semibold text-brand-800">Inspect import evidence</summary>{data.repeated_row_examples.length ? <ul className="mt-3 space-y-1 text-xs text-slate-700">{data.repeated_row_examples.map(row=><li key={row.repeated_line}>Record ending at CSV line {row.repeated_line} repeats the cells of the record ending at line {row.first_line}.</li>)}</ul> : <p className="mt-2 text-xs text-slate-600">No identical source-row candidates found.</p>}{data.repeated_row_candidates > 10 ? <p className="mt-2 text-xs text-slate-600">First 10 examples shown; {data.repeated_row_candidates} candidates counted in total.</p> : null}<ul className="mt-3 list-disc space-y-2 pl-4 text-xs leading-relaxed text-slate-600">{data.notes.map(note=><li key={note}>{note}</li>)}</ul><p className="mt-3 break-all text-[11px] text-slate-500">{data.normalised_date_rows} date cells normalised for parsing.<br />Parsed CSV SHA-256: {data.parsed_source_sha256}</p></details></section>;
}
