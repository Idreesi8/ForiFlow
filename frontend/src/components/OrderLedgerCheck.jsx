import { useEffect, useRef, useState } from 'react';
import { useBusinessDate } from '../hooks/useBusinessDate.js';
import { formatDate, formatCount } from '../lib/format.js';
import { MAX_LEDGER_BYTES, parseOrderLedger, summariseOrderLedger } from '../lib/orderLedger.js';

const emptyPeriod = { start: '', end: '', complete: false };

export default function OrderLedgerCheck() {
  const today = useBusinessDate();
  const [ledger, setLedger] = useState(null);
  const [fileName, setFileName] = useState('');
  const [period, setPeriod] = useState(emptyPeriod);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  const readVersion = useRef(0);
  const resultHeading = useRef(null);

  useEffect(() => () => { readVersion.current += 1; }, []);
  useEffect(() => { if (report) resultHeading.current?.focus(); }, [report]);

  function clear() {
    readVersion.current += 1;
    setLedger(null);
    setFileName('');
    setPeriod(emptyPeriod);
    setReport(null);
    setError(null);
    setReading(false);
  }

  async function pickFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const version = ++readVersion.current;
    setLedger(null);
    setFileName('');
    setReport(null);
    setError(null);
    setPeriod(current => ({ ...current, complete: false }));
    setReading(false);
    if (!/\.csv$/i.test(file.name) || !file.size || file.size > MAX_LEDGER_BYTES) {
      setError('Choose a non-empty CSV file of 1 MB or less.');
      return;
    }
    setReading(true);
    try {
      const bytes = await file.arrayBuffer();
      if (version !== readVersion.current) return;
      let text;
      try {
        text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      } catch {
        setError('Save the ledger as a UTF-8 CSV and choose it again.');
        return;
      }
      setLedger(parseOrderLedger(text));
      setFileName(file.name);
    } catch (cause) {
      if (version === readVersion.current) {
        setError(cause instanceof Error && cause.name === 'Error' ? cause.message : 'The file could not be read. Choose it again.');
      }
    } finally {
      if (version === readVersion.current) setReading(false);
    }
  }

  function setMonth(key, value) {
    setPeriod(current => ({ ...current, [key]: value, complete: false }));
    setReport(null);
    if (ledger) setError(null);
  }

  function check(event) {
    event.preventDefault();
    if (!ledger || reading) return;
    setError(null);
    try {
      setReport(summariseOrderLedger(ledger, period.start, period.end, today, period.complete));
    } catch (cause) {
      setReport(null);
      setError(cause.message);
    }
  }

  return (
    <details className="card min-w-0" data-testid="order-ledger-check">
      <summary className="cursor-pointer rounded-xl px-5 py-4 text-sm font-semibold text-brand-800">
        Check order consistency from a CSV
      </summary>
      <div className="space-y-4 border-t border-slate-200 px-5 py-4">
        <p className="text-sm leading-relaxed text-slate-700">
          Count unique orders for complete months. The CSV stays in this tab and the result is a temporary business check.
        </p>
        <details className="text-xs text-slate-600">
          <summary className="cursor-pointer font-semibold text-brand-800">CSV format and example</summary>
          <p className="mt-2 leading-relaxed">
            Use a UTF-8 CSV up to 1 MB. Give each order one ID, its original order date and its final status.
            Product lines for an order must agree on its date and whether it was cancelled. Placed and completed orders count once.
          </p>
          <pre className="mt-2 max-w-full overflow-x-auto rounded-lg bg-slate-50 p-3">{`order_id,order_date,status
EX-001,2025-01-03,completed
EX-001,2025-01-03,completed
EX-002,2025-01-05,cancelled`}</pre>
        </details>
        <form onSubmit={check} className="space-y-3">
          <div>
            <label htmlFor="ledger-file" className="block text-sm font-medium text-slate-800">Order ledger CSV</label>
            <input id="ledger-file" type="file" accept=".csv,text/csv"
              className="mt-1 block w-full min-w-0 text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-200 file:bg-slate-50 file:px-3 file:py-2 file:text-sm file:font-medium"
              onChange={pickFile} />
            {reading ? <p role="status" className="mt-2 text-xs text-slate-600">Reading the ledger…</p> : null}
            {ledger ? <p className="mt-2 break-all text-xs text-slate-700" role="status">
              {fileName} · {formatCount(ledger.rows)} data rows
              {ledger.firstDate ? ` · Dated ${formatDate(ledger.firstDate)} to ${formatDate(ledger.lastDate)}` : ' · Header only'}
            </p> : null}
          </div>
          <fieldset className="min-w-0 space-y-2">
            <legend className="text-sm font-medium text-slate-800">Months covered by the ledger</legend>
            <p className="text-xs text-slate-600">Choose up to 12 completed months in Pakistan. Stability needs at least three.</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block min-w-0 text-xs text-slate-700">First full month
                <input type="month" placeholder="YYYY-MM" value={period.start} onChange={event => setMonth('start', event.target.value)}
                  className="mt-1 block w-full min-w-0 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
              </label>
              <label className="block min-w-0 text-xs text-slate-700">Last full month
                <input type="month" placeholder="YYYY-MM" value={period.end} onChange={event => setMonth('end', event.target.value)}
                  className="mt-1 block w-full min-w-0 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900" />
              </label>
            </div>
            <label className="flex items-start gap-2 text-xs leading-relaxed text-slate-700">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0" checked={period.complete} onChange={event => {
                const complete = event.target.checked;
                setPeriod(current => ({ ...current, complete }));
                setReport(null);
                if (ledger) setError(null);
              }} />
              I checked that the export covers every selected month in full, including any month with zero orders.
            </label>
          </fieldset>
          <div className="flex flex-wrap gap-2">
            <button type="submit" className="btn-primary text-xs" disabled={!ledger || reading}>Calculate order activity</button>
            <button type="button" className="btn-secondary text-xs" onClick={clear}>Clear ledger check</button>
          </div>
          {error ? <p role="alert" className="text-sm text-rose-800">{error}</p> : null}
        </form>
        {report ? <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4" data-testid="order-ledger-result">
          <h3 ref={resultHeading} tabIndex={-1} className="scroll-mt-24 text-sm font-semibold text-slate-900">Order activity results</h3>
          <p className="text-sm text-slate-800">{formatCount(report.totalOrders)} counted orders · {formatCount(report.totalCancelled)} cancelled · {formatCount(report.excludedOrders)} outside the selected months</p>
          <table className="w-full text-left text-xs">
            <thead className="text-slate-600"><tr><th scope="col" className="py-2">Month</th><th scope="col" className="px-1 py-2">Orders</th><th scope="col" className="py-2">Cancelled</th></tr></thead>
            <tbody>{report.months.map(month => <tr key={month.month} className="border-t border-slate-200 tabular-nums">
              <th scope="row" className="py-2 font-medium">{month.month}</th>
              <td className="px-1 py-2">{formatCount(month.orders)}</td>
              <td className="py-2">{formatCount(month.cancelled)}</td>
            </tr>)}</tbody>
          </table>
          {report.stability === null
            ? <p className="text-xs text-slate-700">Stability is unavailable. It needs at least three complete months and at least one counted order.</p>
            : <p className="text-sm font-semibold text-slate-900">Order count stability · {report.stability} / 100</p>}
          <p className="text-xs leading-relaxed text-slate-600">
            Counts use the coverage you confirmed. Stability measures how similar the monthly counts are and can be affected by seasonality.
          </p>
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer font-semibold text-brand-800">How stability is calculated</summary>
            <p className="mt-1">Divide the population standard deviation of monthly counts by their mean. Subtract that ratio from 1, floor at 0, then multiply by 100 and round.</p>
          </details>
        </div> : null}
      </div>
    </details>
  );
}
