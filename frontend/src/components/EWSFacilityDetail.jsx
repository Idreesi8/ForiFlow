import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  apiErrorMessage,
  fetchFacilityObservations,
  fetchFacilityState,
  fetchFacilityTimeline,
} from "../api/client.js";
import {
  ewsStateStyle,
  formatDeterioration,
  isOverride,
  scoreSourceLabel,
  timelineSourceLabel,
  trendChartData,
  trendMessage,
  trendStyle,
} from "../lib/ews.js";
import { formatDate, formatDateTime, formatPKR } from "../lib/format.js";
import { EwsStateBadge } from "./common/Badges.jsx";
import { ErrorState, LoadingState } from "./common/States.jsx";

/**
 * One facility under monitoring: state and why, the score history, every
 * recorded month (corrections included) and the stored timeline.
 */
export default function EWSFacilityDetail({ facilityId, refreshToken = 0 }) {
  const [state, setState] = useState(null);
  const [rows, setRows] = useState([]);
  const [timeline, setTimeline] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [stateData, rowData, timelineData] = await Promise.all([
        fetchFacilityState(facilityId),
        fetchFacilityObservations(facilityId),
        fetchFacilityTimeline(facilityId),
      ]);
      setState(stateData);
      setRows(rowData);
      setTimeline(timelineData);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the facility."));
    } finally {
      setIsLoading(false);
    }
  }, [facilityId]);

  useEffect(() => {
    load();
  }, [load, refreshToken]);

  if (isLoading) return <LoadingState label="Loading facility history…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!state) return null;

  const trend = state.trend;
  const direction = trendStyle(trend.direction);
  const message = trendMessage(trend);
  const chartData = trendChartData(trend);
  const stateStyle = ewsStateStyle(state.state);

  return (
    <section className="card" data-testid="ews-facility-detail">
      <div className="card-header">
        <div>
          <h2 className="card-title">
            {state.business_name} <span className="text-sm font-normal text-slate-500">App #{state.facility_id}</span>
          </h2>
          <p className="mt-1 text-sm text-slate-500">{state.note}</p>
        </div>
        <EwsStateBadge state={state.state} />
      </div>

      <div className="grid gap-6 px-5 py-5 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-slate-800">Score history</h3>
            <p className={`text-sm ${direction.className}`} data-testid="trend-direction">
              {direction.symbol} {direction.label}
              {trend.slope_points_per_month !== null && trend.slope_points_per_month !== undefined
                ? ` (${trend.slope_points_per_month > 0 ? "+" : ""}${trend.slope_points_per_month} pts/month)`
                : ""}
            </p>
          </div>
          {message ? (
            <p className="mt-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-600" data-testid="trend-message">
              {message}. {trend.observations} month{trend.observations === 1 ? "" : "s"} recorded;
              a direction needs {trend.min_observations}.
            </p>
          ) : null}
          <div className="mt-3 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 16, bottom: 4, left: -8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip content={<PointTooltip />} />
                <Line
                  type="linear"
                  dataKey="score"
                  stroke={stateStyle.color}
                  strokeWidth={2}
                  isAnimationActive={false}
                  dot={<PointDot />}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            ◆ Baseline: the ForiFlow origination assessment. ● EWS rules. ■ Officer override. The
            line joins recorded months only; nothing is interpolated.
          </p>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Figure label="Baseline" value={trend.baseline_score.toFixed(1)} />
            <Figure label="Latest" value={trend.latest_score?.toFixed(1) ?? "—"} />
            <Figure label="Total change" value={formatDeterioration(trend.total_deterioration)} />
            <Figure label="Since previous month" value={formatDeterioration(trend.recent_deterioration)} />
          </dl>
        </div>

        <div className="space-y-4 xl:col-span-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Why {stateStyle.label}</h3>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
              {state.state_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Signals in the latest month</h3>
            {state.signals.length ? (
              <ul className="mt-1 space-y-1 text-sm text-slate-700" data-testid="signals">
                {state.signals.map((signal) => (
                  <li key={signal.code}>
                    <span className="font-mono text-[11px] text-slate-500">{signal.code}</span>{" "}
                    {signal.evidence}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-sm text-slate-500">None.</p>
            )}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-800">Recommended actions</h3>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
              {state.recommended_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      <div className="border-t border-slate-200">
        <h3 className="px-5 pt-4 text-sm font-semibold text-slate-800">Recorded months</h3>
        <div className="overflow-x-auto">
          <table className="mt-2 min-w-full divide-y divide-slate-200 text-sm" data-testid="observation-history">
            <thead className="table-head">
              <tr>
                <th className="px-4 py-2 text-left">Month</th>
                <th className="px-4 py-2 text-left">Observed</th>
                <th className="px-4 py-2 text-left">Repayment</th>
                <th className="px-4 py-2 text-right">Bureau balance</th>
                <th className="px-4 py-2 text-right">POS inflow</th>
                <th className="px-4 py-2 text-right">Paid</th>
                <th className="px-4 py-2 text-right">Score</th>
                <th className="px-4 py-2 text-left">Score source</th>
                <th className="px-4 py-2 text-left">Recorded by</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((row) => {
                const superseded = row.record_status === "superseded";
                return (
                  <tr key={row.id} className={superseded ? "bg-slate-50 text-slate-400" : ""}>
                    <td className="px-4 py-2">
                      <span className={superseded ? "line-through" : "font-semibold"}>
                        {row.month_number}
                      </span>
                      <p className="text-[10px]">#{row.id}</p>
                    </td>
                    <td className="px-4 py-2">
                      {row.observation_date ? formatDate(row.observation_date) : "not recorded"}
                    </td>
                    <td className="px-4 py-2">
                      {row.installment_status}
                      {row.days_late !== null && row.days_late !== undefined ? ` · ${row.days_late}d` : ""}
                    </td>
                    <td className="tabular px-4 py-2 text-right">{formatPKR(row.bureau_balance)}</td>
                    <td className="tabular px-4 py-2 text-right">{formatPKR(row.pos_cash_balance)}</td>
                    <td className="tabular px-4 py-2 text-right">{formatPKR(row.amount_paid_pkr)}</td>
                    <td className="tabular px-4 py-2 text-right font-semibold">
                      {row.monthly_score.toFixed(1)}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      <span className={isOverride(row.score_source) ? "font-semibold text-violet-700" : ""}>
                        {scoreSourceLabel(row.score_source, { short: true })}
                      </span>
                      {isOverride(row.score_source) ? (
                        <p title={row.override_reason}>
                          rules gave {row.rule_score?.toFixed(1)} · “{row.override_reason}”
                        </p>
                      ) : null}
                      {superseded ? <p>superseded by #{row.superseded_by_observation_id}</p> : null}
                      {row.supersedes_observation_id ? (
                        <p>corrects #{row.supersedes_observation_id}: {row.correction_reason}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {row.created_by ?? "not recorded"}
                      {row.created_at ? <p>{formatDateTime(row.created_at)}</p> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="border-t border-slate-200 px-5 py-4">
        <h3 className="text-sm font-semibold text-slate-800">Timeline</h3>
        {timeline?.note ? <p className="mt-1 text-xs text-slate-500">{timeline.note}</p> : null}
        <ol className="mt-3 space-y-2 border-l-2 border-slate-200 pl-4" data-testid="facility-timeline">
          {(timeline?.events ?? []).map((event, index) => (
            <li key={`${event.kind}-${event.entity_id}-${index}`} className="text-sm">
              <p className="text-xs text-slate-500">
                {event.occurred_at ? formatDateTime(event.occurred_at) : "time not recorded"}
                {event.actor ? ` · ${event.actor}` : ""} ·{" "}
                <span className={event.source === "record" ? "italic" : ""}>{timelineSourceLabel(event)}</span>
              </p>
              <p className="font-medium text-slate-800">{event.title}</p>
              {event.detail ? <p className="text-xs text-slate-600">{event.detail}</p> : null}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function Figure({ label, value }) {
  return (
    <div>
      <dt className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="tabular text-lg font-bold text-slate-900">{value}</dd>
    </div>
  );
}

function PointDot({ cx, cy, payload }) {
  if (cx === undefined || cy === undefined) return null;
  if (payload.isBaseline) {
    return (
      <path
        d={`M ${cx} ${cy - 7} L ${cx + 7} ${cy} L ${cx} ${cy + 7} L ${cx - 7} ${cy} Z`}
        fill="#0f172a"
        stroke="#fff"
        strokeWidth={1.5}
        data-point="baseline"
      />
    );
  }
  if (payload.isOverride) {
    return <rect x={cx - 5} y={cy - 5} width={10} height={10} fill="#7c3aed" stroke="#fff" data-point="override" />;
  }
  return <circle cx={cx} cy={cy} r={4.5} fill="#fff" stroke="#334155" strokeWidth={2} data-point="month" />;
}

function PointTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow">
      <p className="font-semibold text-slate-900">
        {point.label}: {point.score.toFixed(1)}
      </p>
      <p className="text-slate-600">Score Source: {scoreSourceLabel(point.source)}</p>
      {point.status ? <p className="text-slate-600">{point.status}</p> : null}
    </div>
  );
}
