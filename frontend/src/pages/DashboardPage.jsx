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

import { apiErrorMessage, fetchApplications, fetchPortfolioStats } from "../api/client.js";
import ApplicationTable from "../components/ApplicationTable.jsx";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import PortfolioPanel from "../components/PortfolioPanel.jsx";
import ScoreDial from "../components/ScoreDial.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { SCORE_BANDS, bandForDecision } from "../lib/decisions.js";
import { formatPKRCompact } from "../lib/format.js";

/** Portfolio overview: origination quality on the left, surveillance below. */
export default function DashboardPage() {
  const [applications, setApplications] = useState([]);
  const [portfolio, setPortfolio] = useState(null);
  // null until the alert feed has loaded; the stats snapshot is used until then.
  const [openAlerts, setOpenAlerts] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Totals come from GET /score/stats (computed in SQL over every row); the
  // application list is only needed for the latest and most recent rows.
  const loadPortfolio = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [stats, recent] = await Promise.all([
        fetchPortfolioStats(),
        fetchApplications({ limit: 5 }),
      ]);
      setPortfolio(stats);
      setApplications(recent);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the portfolio."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPortfolio();
  }, [loadPortfolio]);

  const handleAlertsLoaded = useCallback((alerts) => {
    // Open = not yet resolved: Active, or In Review with an officer.
    setOpenAlerts(alerts.filter((alert) => alert.alert_status !== "Resolved"));
  }, []);

  const decisionData = useMemo(
    () =>
      SCORE_BANDS.map((band) => ({
        name: band.recommendation,
        value: portfolio?.model_decisions?.[band.decision] ?? 0,
        color: band.color,
      })).filter((item) => item.value > 0),
    [portfolio],
  );

  // Bars are (lower, upper], with edges on the policy boundaries 40 and 70,
  // so every score is counted once and no bar mixes decisions.
  const histogramData = useMemo(
    () =>
      (portfolio?.score_histogram ?? []).map((bucket) => ({
        label: bucket.label,
        count: bucket.count,
        color: bucket.upper <= 40 ? "#e11d48" : bucket.upper <= 70 ? "#f59e0b" : "#059669",
      })),
    [portfolio],
  );

  const latest = applications[0] ?? null;
  const openCount = openAlerts ? openAlerts.length : (portfolio?.open_alerts ?? 0);
  const worstOpenDrop = openAlerts
    ? openAlerts.length
      ? Math.max(...openAlerts.map((alert) => alert.score_drop))
      : null
    : (portfolio?.worst_open_drop ?? null);

  if (isLoading) return <LoadingState label="Loading portfolio…" />;
  if (error) return <ErrorState message={error} onRetry={loadPortfolio} />;

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Applications scored"
          value={portfolio.total_applications}
          hint="All time"
          accent="brand"
        />
        <StatCard
          label="Approval rate"
          value={`${portfolio.approval_rate.toFixed(0)}%`}
          hint={`${portfolio.pending_review} awaiting an officer decision`}
          accent="emerald"
        />
        <StatCard
          label="Average score"
          value={portfolio.average_score === null ? "—" : portfolio.average_score.toFixed(1)}
          hint="Out of 100"
          accent="slate"
        />
        <StatCard
          label="Approved exposure"
          value={formatPKRCompact(portfolio.approved_exposure_pkr)}
          hint="Model and officer approvals"
          accent="slate"
        />
        <StatCard
          label="Open EWS alerts"
          value={openCount}
          hint={worstOpenDrop !== null ? `Worst drop ${worstOpenDrop.toFixed(1)} pts` : "Portfolio stable"}
          accent={openCount ? "rose" : "emerald"}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-3">
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Recommendation mix</h2>
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

      <PortfolioPanel />

      <EWSAlertFeed
        maxRows={5}
        compact
        showFilters={false}
        onAlertsLoaded={handleAlertsLoaded}
      />

      <ApplicationTable
        applications={applications}
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
