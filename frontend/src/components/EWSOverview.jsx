import {
  formatDeterioration,
  scoreSourceLabel,
  stateCounts,
  trendStyle,
} from "../lib/ews.js";
import { formatDate } from "../lib/format.js";
import { AlertStatusBadge, EwsStateBadge } from "./common/Badges.jsx";
import { EmptyState } from "./common/States.jsx";

/**
 * Portfolio EWS position from `GET /ews/overview`: tiles, then one row per
 * monitored facility, worst first. Every figure is the API's.
 */
export default function EWSOverview({ overview, selectedId, onSelect }) {
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
            EWS states are monitoring states, not credit risk bands. Select a facility to see its
            history.
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
        <div className="overflow-x-auto">
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
                    onClick={() => onSelect(row.facility_id)}
                    className={`cursor-pointer hover:bg-slate-50 ${selected ? "bg-brand-50" : ""}`}
                    data-facility-id={row.facility_id}
                  >
                    <td className="px-4 py-3">
                      <p className="font-semibold text-slate-900">{row.business_name}</p>
                      <p className="text-xs text-slate-500">App #{row.facility_id}</p>
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
      )}
    </section>
  );
}
