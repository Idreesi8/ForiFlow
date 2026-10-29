import { formatDate, formatPKRExact } from "../lib/format.js";
import { scoreSourceLabel } from "../lib/ews.js";

const STATES = {
  recorded: { label: "Recorded", short: "Recorded", style: "border-emerald-200 bg-emerald-50 text-emerald-900" },
  unknown: { label: "Recorded · amount unknown", short: "Unknown", style: "border-amber-200 bg-amber-50 text-amber-950" },
  gap: { label: "Earlier record missing", short: "Gap", style: "border-rose-200 bg-rose-50 text-rose-900" },
  unrecorded: { label: "Not recorded", short: "No record", style: "border-slate-200 bg-slate-50 text-slate-600" },
};

export default function MonitoringCalendar({ coverage, selectedMonth, onSelect, disabled, onRefresh }) {
  return <section className="border-b border-slate-200 px-5 py-5" aria-label="Monitoring calendar">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="font-bold text-slate-900">Monitoring calendar</h3><p className="mt-1 text-xs text-slate-500">Reporting months since disbursement. Choose a month to inspect its record or enter verified figures.</p></div>
      <button type="button" className="btn-secondary text-xs" onClick={onRefresh} disabled={disabled}>Refresh history</button>
    </div>
    <div className="my-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-700">
      <span><strong>{coverage.recorded}/{coverage.months.length}</strong> recorded</span>
      <span><strong>{coverage.gaps}</strong> earlier gaps</span>
      <span><strong>{coverage.unknown}</strong> unknown payment amounts</span>
    </div>
    <div className="grid grid-cols-4 gap-2 sm:grid-cols-8 xl:grid-cols-12" role="group" aria-label="Facility reporting months">
      {coverage.months.map(month => <button key={month.number} type="button" disabled={disabled}
        aria-pressed={month.number === Number(selectedMonth)}
        aria-label={`Month ${month.number}: ${STATES[month.state].label}${month.priorVersions ? `; ${month.priorVersions} earlier versions` : ""}`}
        onClick={() => onSelect(month.number)}
        className={`relative min-w-0 rounded-lg border px-1 py-2 text-center transition hover:brightness-95 ${STATES[month.state].style} ${month.number === Number(selectedMonth) ? "ring-2 ring-brand-700 ring-offset-2" : ""}`}>
        <span className="block text-sm font-bold tabular-nums">{String(month.number).padStart(2, "0")}</span>
        <span className="mt-1 block text-[10px] leading-tight">{STATES[month.state].short}</span>
        {month.priorVersions ? <span className="mt-1 block text-[9px]">History +{month.priorVersions}</span> : null}
      </button>)}
    </div>
    <p className="mt-4 text-xs leading-relaxed text-slate-600">Grey months are unrecorded, not assumed due or unpaid. A gap is an earlier month without an active observation. Unknown amounts are not zero payments.</p>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs font-semibold text-brand-800">{coverage.nextMonth ? `First unrecorded month: ${coverage.nextMonth}` : "All facility months have active observations."}</p>
      {coverage.nextMonth ? <button type="button" disabled={disabled} className="text-xs font-semibold text-brand-700 underline" onClick={() => onSelect(coverage.nextMonth)}>Choose first unrecorded month</button> : null}
    </div>
  </section>;
}

export function RecordedMonth({ month, canManage, editing, disabled, onPrepare }) {
  const row = month.record;
  return <section className="border-b border-slate-200 bg-slate-50 px-5 py-4" data-testid="recorded-month">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h3 className="font-semibold text-slate-900">Month {month.number} is already recorded</h3><p className="mt-1 text-xs text-slate-500">Active observation #{row.id}{month.priorVersions ? ` · ${month.priorVersions} earlier versions retained` : ""}. The original is never overwritten.</p></div>
      {canManage && !editing ? <button type="button" className="btn-secondary" disabled={disabled} onClick={onPrepare}>Prepare correction</button> : null}
    </div>
    <dl className="mt-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
      <Fact label="Recorded status" value={row.installment_status} />
      <Fact label="Recorded payment" value={row.amount_paid_pkr == null ? "Unknown" : formatPKRExact(row.amount_paid_pkr)} />
      <Fact label="Bureau balance" value={formatPKRExact(row.bureau_balance)} />
      <Fact label="POS cash inflow" value={formatPKRExact(row.pos_cash_balance)} />
    </dl>
    <p className="mt-3 text-xs text-slate-600">{row.observation_date ? `Observation date: ${formatDate(row.observation_date)}. ` : "Observation date not recorded. "}{scoreSourceLabel(row.score_source)}.</p>
    <p className="mt-2 text-xs text-slate-600">{canManage ? "Prepare correction loads the stored figures into an editable form. Check each figure and provide a reason before saving." : "A manager or admin can prepare a correction; you can inspect the stored evidence."}</p>
  </section>;
}

function Fact({ label, value }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 break-words font-semibold text-slate-800">{value}</dd></div>;
}
