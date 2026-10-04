import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { apiErrorMessage, fetchPortfolioSummary } from "../api/client.js";
import { bandForDecision } from "../lib/decisions.js";
import { formatCount, formatPKR, formatPKRCompact } from "../lib/format.js";
import { ErrorState, LoadingState } from "./common/States.jsx";

// Repayment status is a state, so it wears the status colours: green for on
// time, amber deepening with lateness, red for default. Labels sit on the axis,
// so the colour is never the only cue.
const STATUS_COLORS = {
  "On Time": "#059669",
  "Late 1-29": "#fbbf24",
  "Late 30-59": "#f59e0b",
  "Late 60-89": "#d97706",
  Default: "#e11d48",
};

/**
 * The approved book: what was lent, what came back, what is late, and where it
 * is concentrated. Read from `GET /portfolio/summary`, which only counts months
 * where an officer recorded the amount paid.
 */
export default function PortfolioPanel() {
  const [summary, setSummary] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setSummary(await fetchPortfolioSummary());
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the loan book."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (isLoading) return <LoadingState label="Loading loan book…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const statusData = summary.latest_status.map((row) => ({
    ...row,
    color: STATUS_COLORS[row.status],
  }));
  const hasMonitoring = summary.monitored_facilities > 0;

  return (
    <section className="space-y-4" aria-labelledby="loan-book-title">
      <div>
        <h2 id="loan-book-title" className="text-base font-bold text-slate-900">
          Loan book
        </h2>
        <p className="mt-0.5 text-xs text-slate-500">
          {formatCount(summary.approved_facilities)} approved facilities,{" "}
          {formatCount(summary.monitored_facilities)} with monthly records. Installments are
          straight-line (facility ÷ tenure); ForiFlow holds no interest rate.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        <Tile label="Disbursed" value={formatPKRCompact(summary.disbursed_pkr)} hint="Approved facilities" />
        <Tile
          label="Collected"
          value={formatPKRCompact(summary.collected_pkr)}
          hint={
            summary.collection_rate === null
              ? "No payment recorded yet"
              : `${summary.collection_rate.toFixed(1)}% of ${formatPKRCompact(summary.due_pkr)} due`
          }
        />
        <Tile
          label="Overdue"
          value={formatPKRCompact(summary.overdue_pkr)}
          hint="Due but not paid"
          alert={summary.overdue_pkr > 0}
        />
        <Tile
          label="Outstanding"
          value={formatPKRCompact(summary.outstanding_pkr)}
          hint="Not yet repaid"
        />
        <Tile
          label="Portfolio at risk"
          value={summary.par30 === null ? "—" : `${summary.par30.toFixed(1)}%`}
          hint="Outstanding 30+ days late"
          alert={summary.par30 !== null && summary.par30 > 0}
        />
        <Tile
          label="Defaulted"
          value={formatCount(summary.defaulted_facilities)}
          hint={`${formatPKRCompact(summary.defaulted_outstanding_pkr)} outstanding`}
          alert={summary.defaulted_facilities > 0}
        />
      </div>

      {summary.months_without_amount > 0 ? (
        <p className="text-xs text-slate-500">
          {formatCount(summary.months_without_amount)} monthly record
          {summary.months_without_amount === 1 ? " has" : "s have"} no amount paid and{" "}
          {summary.months_without_amount === 1 ? "is" : "are"} left out of Collected and
          Overdue.
        </p>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Latest repayment status</h3>
            <span className="text-xs text-slate-500">outstanding, by each facility's last month</span>
          </div>
          <div className="px-5 py-4" style={{ height: 260 }}>
            {hasMonitoring ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={statusData}
                  layout="vertical"
                  margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
                >
                  <XAxis
                    type="number"
                    tickFormatter={(value) => formatPKRCompact(value).replace("PKR ", "")}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={{ stroke: "#cbd5e1" }}
                  />
                  <YAxis
                    type="category"
                    dataKey="status"
                    width={84}
                    tick={{ fontSize: 12, fill: "#334155" }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: "#f1f5f9" }}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                    formatter={(value, _name, item) => [
                      `${formatPKR(value)} · ${item.payload.facilities} facilit${
                        item.payload.facilities === 1 ? "y" : "ies"
                      }`,
                      "Outstanding",
                    ]}
                  />
                  <Bar dataKey="outstanding_pkr" radius={[0, 4, 4, 0]} maxBarSize={26}>
                    {statusData.map((row) => (
                      <Cell key={row.status} fill={row.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="pt-20 text-center text-sm text-slate-500">
                No facility has a monthly record yet. Record one under EWS Alerts.
              </p>
            )}
          </div>
        </div>

        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Decision matrix</h3>
            <span className="text-xs text-slate-500">model band against final outcome</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">Model said</th>
                  <th className="px-3 py-3 text-right font-medium">Approved</th>
                  <th className="px-3 py-3 text-right font-medium">Rejected</th>
                  <th className="px-5 py-3 text-right font-medium">Pending</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {summary.decision_matrix.map((row) => (
                  <tr key={row.model_decision}>
                    <td className="px-5 py-3">
                      <span className={`badge ${bandForDecision(row.model_decision).badgeClass}`}>
                        {row.model_decision}
                      </span>
                    </td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.approved)}</td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.rejected)}</td>
                    <td className="tabular px-5 py-3 text-right">{formatCount(row.pending)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            The Manual Review row shows what officers decided. The other two bands are
            final as the model set them.
          </p>
        </div>
      </div>

      <div className="card min-w-0">
        <div className="card-header">
          <h3 className="card-title">By business sector</h3>
          <span className="text-xs text-slate-500">largest approved exposure first</span>
        </div>
        {summary.sectors.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-slate-500">No applications yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">Sector</th>
                  <th className="px-3 py-3 text-right font-medium">Applications</th>
                  <th className="px-3 py-3 text-right font-medium">Approved</th>
                  <th className="px-3 py-3 text-right font-medium">Approval rate</th>
                  <th className="px-3 py-3 text-right font-medium">Exposure</th>
                  <th className="px-3 py-3 text-right font-medium">Avg score</th>
                  <th className="px-3 py-3 text-right font-medium">Overdue</th>
                  <th className="px-5 py-3 text-right font-medium">Open alerts</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {summary.sectors.map((row) => (
                  <tr key={row.sector}>
                    <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">
                      {row.sector}
                    </td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.applications)}</td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.approved)}</td>
                    <td className="tabular px-3 py-3 text-right">{row.approval_rate.toFixed(0)}%</td>
                    <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                      {formatPKRCompact(row.approved_exposure_pkr)}
                    </td>
                    <td className="tabular px-3 py-3 text-right">{row.average_score.toFixed(1)}</td>
                    <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                      {row.overdue_pkr > 0 ? formatPKRCompact(row.overdue_pkr) : "—"}
                    </td>
                    <td className="tabular px-5 py-3 text-right">{formatCount(row.open_alerts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Tile({ label, value, hint, alert = false }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`tabular mt-1 text-xl font-bold ${alert ? "text-rose-700" : "text-slate-900"}`}>
        {value}
      </p>
      <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
    </div>
  );
}
