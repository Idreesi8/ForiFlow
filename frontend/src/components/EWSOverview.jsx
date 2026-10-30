import {
  formatDeterioration,
  scoreSourceLabel,
  stateCounts,
  trendStyle,
} from "../lib/ews.js";
import { formatDate, formatNumber } from "../lib/format.js";
import { AlertStatusBadge, EwsStateBadge } from "./common/Badges.jsx";
import { EmptyState } from "./common/States.jsx";

/**
 * Portfolio EWS position from `GET /ews/overview`: tiles, then one row per
 * monitored facility, worst first. Every figure is the API's.
 */
export default function EWSOverview({ overview, selectedId, onSelect, onRecord, disabled = false }) {
  const tiles = [
    { label: "Monitored facilities", value: overview.monitored_facilities },
    ...stateCounts(overview).map((item) => ({
      label: item.label,
      value: item.count,
      color: item.count ? item.color : undefined,
    })),
    { label: "Open alerts", value: overview.open_alerts, color: overview.open_alerts ? "#e11d48" : undefined },
    {
      label: "Overdue actions",
      value: overview.overdue_actions,
      color: overview.overdue_actions ? "#e11d48" : undefined,
    },
  ];

  return (
    <section className="card" data-testid="ews-overview">
      <div className="card-header">
        <div>
          <h2 className="card-title">Portfolio monitoring</h2>
          <p className="mt-1 text-sm text-slate-500">
            Choose a facility to review its history or record a month. Monitoring states are
            separate from credit risk bands.
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-px border-b border-slate-200 bg-slate-200 sm:grid-cols-4 xl:grid-cols-7">
        {tiles.map((tile) => (
          <div key={tile.label} className="bg-white px-4 py-3">
            <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{tile.label}</p>
            <p className="tabular mt-0.5 text-2xl font-bold" style={{ color: tile.color ?? "#0f172a" }}>
              {tile.value}
            </p>
          </div>
        ))}
      </div>

      {overview.rows.length === 0 ? (
        <EmptyState
          title="No facility is being monitored"
          description="Record a month for an approved facility to start its history."
        />
      ) : (
        <>
        <ul aria-label="Monitored facilities" className="divide-y divide-slate-200 md:hidden">
          {overview.rows.map(row => {
            const selected = row.facility_id === selectedId;
            const trend = trendStyle(row.trend_direction);
            return <li key={row.facility_id} data-facility-id={row.facility_id} className={`p-4 ${selected ? 'bg-brand-50/70' : ''}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1"><h3 className="break-words text-sm font-semibold text-slate-900">{row.business_name}</h3>
                  <p className="mt-1 text-xs text-slate-500">Case #{row.facility_id}{selected ? ' · Selected' : ''}</p></div>
                <EwsStateBadge state={row.state} />
              </div>
              <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                <div><dt className="text-slate-500">Baseline</dt><dd className="mt-1 font-semibold tabular">{formatNumber(row.baseline_score, 1)}</dd></div>
                <div><dt className="text-slate-500">Latest score</dt><dd className="mt-1 font-semibold tabular">{formatNumber(row.current_score, 1)}</dd></div>
                <div><dt className="text-slate-500">Total change</dt><dd className="mt-1 font-semibold tabular">{formatDeterioration(row.total_deterioration)}</dd></div>
              </dl>
              <p className="mt-3 text-xs text-slate-500">Score source: {scoreSourceLabel(row.score_source, { short: true })}. Month {row.last_month_number} · {row.last_observation_date ? formatDate(row.last_observation_date) : 'date not recorded'}</p>
              <p className={`mt-2 text-xs ${trend.className}`}>{trend.symbol} {trend.label} · {row.observations} recorded month{row.observations === 1 ? '' : 's'}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">{row.open_alert_status ? <AlertStatusBadge status={row.open_alert_status} /> : <span className="text-xs text-slate-500">No open alert</span>}{row.overdue ? <span className="text-xs font-semibold text-rose-700">Action overdue</span> : null}</div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="btn-secondary flex-1" disabled={disabled} aria-pressed={selected}
                  aria-label={`View history for case ${row.facility_id}: ${row.business_name}`} onClick={() => onSelect(row.facility_id)}>View history</button>
                {onRecord ? <button type="button" className="btn-primary flex-1" disabled={disabled}
                  aria-label={`Record a month for case ${row.facility_id}: ${row.business_name}`} onClick={() => onRecord(row.facility_id)}>Record month</button> : null}
              </div>
            </li>;
          })}
        </ul>
        <div className="hidden overflow-x-auto md:block">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="table-head">
              <tr>
                <th className="px-4 py-3 text-left">Facility</th>
                <th className="px-4 py-3 text-left">State</th>
                <th className="px-4 py-3 text-right">Baseline</th>
                <th className="px-4 py-3 text-right">Current</th>
                <th className="px-4 py-3 text-right">Total change</th>
                <th className="px-4 py-3 text-right">Since previous</th>
                <th className="px-4 py-3 text-left">Trend</th>
                <th className="px-4 py-3 text-left">Alert</th>
                <th className="px-4 py-3 text-left">Last observation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {overview.rows.map((row) => {
                const trend = trendStyle(row.trend_direction);
                const selected = row.facility_id === selectedId;
                return (
                  <tr
                    key={row.facility_id}
                    className={`hover:bg-slate-50 ${selected ? "bg-brand-50" : ""}`}
                    data-facility-id={row.facility_id}
                  >
                    <td className="px-4 py-3">
                      <button type="button" disabled={disabled} aria-pressed={selected}
                        aria-label={`View history for case ${row.facility_id}: ${row.business_name}`}
                        onClick={() => onSelect(row.facility_id)} className="rounded text-left font-semibold text-brand-800 underline-offset-4 hover:underline disabled:opacity-60">
                        {row.business_name}
                      </button>
                      <p className="mt-1 text-xs text-slate-500">Case #{row.facility_id}{selected ? ' · Selected' : ''}</p>
                      {onRecord ? <button type="button" disabled={disabled} onClick={() => onRecord(row.facility_id)}
                        aria-label={`Record a month for case ${row.facility_id}: ${row.business_name}`}
                        className="mt-2 min-h-11 rounded px-1 text-xs font-semibold text-brand-700 underline-offset-4 hover:underline disabled:opacity-60">Record month →</button> : null}
                    </td>
                    <td className="px-4 py-3">
                      <EwsStateBadge state={row.state} />
                    </td>
                    <td className="tabular px-4 py-3 text-right text-slate-600">
                      {row.baseline_score.toFixed(1)}
                    </td>
                    <td className="tabular px-4 py-3 text-right font-semibold">
                      {row.current_score?.toFixed(1) ?? "—"}
                      <p className="text-[10px] font-normal text-slate-500">
                        {scoreSourceLabel(row.score_source, { short: true })}
                      </p>
                    </td>
                    <td className="tabular px-4 py-3 text-right">
                      {formatDeterioration(row.total_deterioration)}
                    </td>
                    <td className="tabular px-4 py-3 text-right">
                      {formatDeterioration(row.recent_deterioration)}
                    </td>
                    <td className={`px-4 py-3 whitespace-nowrap ${trend.className}`}>
                      {trend.symbol} {trend.label}
                      <p className="text-[10px] font-normal text-slate-500">
                        {row.observations} month{row.observations === 1 ? "" : "s"}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      {row.open_alert_status ? (
                        <AlertStatusBadge status={row.open_alert_status} />
                      ) : (
                        <span className="text-xs text-slate-400">None open</span>
                      )}
                      {row.overdue ? (
                        <p className="mt-1 text-xs font-semibold text-rose-700">Action overdue</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      Month {row.last_month_number}
                      <p className="text-xs text-slate-500">
                        {row.last_observation_date ? formatDate(row.last_observation_date) : "date not recorded"}
                      </p>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </>
      )}
    </section>
  );
}
