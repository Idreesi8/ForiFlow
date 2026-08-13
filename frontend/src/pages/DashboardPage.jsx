import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiErrorMessage, fetchApplications } from "../api/client.js";
import ApplicationTable from "../components/ApplicationTable.jsx";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import ScoreDial from "../components/ScoreDial.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { SCORE_BANDS, bandForDecision } from "../lib/decisions.js";
import { formatPKRCompact } from "../lib/format.js";

// Bucket edges land on the policy boundaries (40 and 70) so no bar mixes
// decisions and every bar can take a single band colour.
const SCORE_BUCKETS = [
  { label: "0-20", min: 0, max: 20 },
  { label: "21-40", min: 21, max: 40 },
  { label: "41-55", min: 41, max: 55 },
  { label: "56-70", min: 56, max: 70 },
  { label: "71-85", min: 71, max: 85 },
  { label: "86-100", min: 86, max: 100 },
];

/** Portfolio overview: origination quality on the left, surveillance below. */
export default function DashboardPage() {
  const [applications, setApplications] = useState([]);
  const [activeAlerts, setActiveAlerts] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadApplications = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setApplications(await fetchApplications({ limit: 200 }));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the portfolio."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApplications();
  }, [loadApplications]);

  const handleAlertsLoaded = useCallback((alerts) => {
    setActiveAlerts(alerts.filter((alert) => alert.alert_status === "Active"));
  }, []);

  const stats = useMemo(() => {
    const total = applications.length;
    const approved = applications.filter((app) => app.decision === "Approved");
    const averageScore = total
      ? applications.reduce((sum, app) => sum + app.risk_score, 0) / total
      : 0;
    const exposure = approved.reduce((sum, app) => sum + app.loan_amount_pkr, 0);

    return {
      total,
      approvalRate: total ? (approved.length / total) * 100 : 0,
      averageScore,
      exposure,
      pending: applications.filter((app) => app.decision === "Manual Review").length,
    };
  }, [applications]);

  const decisionData = useMemo(
    () =>
      SCORE_BANDS.map((band) => ({
        name: band.decision,
        value: applications.filter((app) => app.decision === band.decision).length,
        color: band.color,
      })).filter((item) => item.value > 0),
    [applications],
  );

  const histogramData = useMemo(
    () =>
      SCORE_BUCKETS.map((bucket) => ({
        label: bucket.label,
        count: applications.filter(
          (app) => app.risk_score >= bucket.min && app.risk_score <= bucket.max,
        ).length,
        color: bucket.max <= 40 ? "#e11d48" : bucket.max <= 70 ? "#f59e0b" : "#059669",
      })),
    [applications],
  );

  const latest = useMemo(() => {
    if (applications.length === 0) return null;
    return [...applications].sort((a, b) => b.id - a.id)[0];
  }, [applications]);

  if (isLoading) return <LoadingState label="Loading portfolio…" />;
  if (error) return <ErrorState message={error} onRetry={loadApplications} />;

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Applications scored"
          value={stats.total}
          hint="All time"
          accent="brand"
        />
        <StatCard
          label="Approval rate"
          value={`${stats.approvalRate.toFixed(0)}%`}
          hint={`${stats.pending} awaiting manual review`}
          accent="emerald"
        />
        <StatCard
          label="Average score"
          value={stats.averageScore.toFixed(1)}
          hint="Out of 100"
          accent="slate"
        />
        <StatCard
          label="Approved exposure"
          value={formatPKRCompact(stats.exposure)}
          hint="Sanctioned facilities"
          accent="slate"
        />
        <StatCard
          label="Active EWS alerts"
          value={activeAlerts.length}
          hint={
            activeAlerts.length
              ? `Worst drop ${Math.max(...activeAlerts.map((a) => a.score_drop)).toFixed(1)} pts`
              : "Portfolio stable"
          }
          accent={activeAlerts.length ? "rose" : "emerald"}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-3">
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Decision mix</h2>
          </div>
          <div className="px-5 py-4" style={{ height: 300 }}>
            {decisionData.length === 0 ? (
              <p className="pt-16 text-center text-sm text-slate-500">
                No assessments yet.
              </p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={decisionData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius="55%"
                    outerRadius="80%"
                    paddingAngle={2}
                    stroke="none"
                  >
                    {decisionData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [`${value} applications`, name]}
                    contentStyle={{ fontSize: 12, borderRadius: 8 }}
                  />
                  <Legend
                    verticalAlign="bottom"
                    iconType="circle"
                    wrapperStyle={{ fontSize: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Score distribution</h2>
          </div>
          <div className="px-5 py-4" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histogramData} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  tickLine={false}
                  axisLine={{ stroke: "#cbd5e1" }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ fill: "#f1f5f9" }}
                  formatter={(value) => [`${value} applications`, "Count"]}
                  contentStyle={{ fontSize: 12, borderRadius: 8 }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48}>
                  {histogramData.map((entry) => (
                    <Cell key={entry.label} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Latest assessment</h2>
            {latest ? (
              <Link to={`/shap/${latest.id}`} className="text-xs font-semibold text-brand-700 hover:underline">
                View SHAP
              </Link>
            ) : null}
          </div>
          <div className="px-5 py-4">
            <ScoreDial
              score={latest ? latest.risk_score : null}
              decision={latest?.decision}
              riskBand={latest ? bandForDecision(latest.decision).riskBand : null}
              size={230}
              showLegend={false}
              caption={
                latest
                  ? `${latest.business_name} · ${formatPKRCompact(latest.loan_amount_pkr)} over ${latest.tenure_months} months`
                  : "Score an application to see it here."
              }
            />
          </div>
        </div>
      </section>

      <EWSAlertFeed limit={5} compact showFilters={false} onAlertsLoaded={handleAlertsLoaded} />

      <ApplicationTable
        applications={[...applications].sort((a, b) => b.id - a.id).slice(0, 5)}
        showFilters={false}
        title="Recent applications"
      />
    </div>
  );
}

function StatCard({ label, value, hint, accent = "slate" }) {
  const accentClass = {
    brand: "text-brand-700",
    emerald: "text-emerald-700",
    rose: "text-rose-700",
    slate: "text-slate-900",
  }[accent];

  return (
    <div className="card px-5 py-4">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`tabular mt-1 text-2xl font-bold ${accentClass}`}>{value}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}
