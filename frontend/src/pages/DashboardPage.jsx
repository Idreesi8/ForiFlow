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
import ActionDeskPreview from "../components/ActionDeskPreview.jsx";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import PortfolioPanel from "../components/PortfolioPanel.jsx";
import ScoreDial from "../components/ScoreDial.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { SCORE_BANDS, bandForDecision } from "../lib/decisions.js";
import { bandIndexForRiskBand, describeBands } from "../lib/policyBands.js";
import { formatPKRCompact } from "../lib/format.js";
import { isOpenAlert } from "../lib/ews.js";
import { getStoredUsername } from "../api/auth.js";

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
    // Open = Open, Acknowledged or Action Required (the API's is_open).
    setOpenAlerts(alerts.filter(isOpenAlert));
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

  // Bars are (lower, upper] with edges on the ACTIVE policy's cut-offs, and
  // the API says which band each bar is in, so the colours follow the policy.
  const histogramData = useMemo(
    () =>
      (portfolio?.score_histogram ?? []).map((bucket) => {
        const index = bandIndexForRiskBand(bucket.risk_band);
        return {
          label: bucket.label,
          count: bucket.count,
          color: index === null ? "#94a3b8" : SCORE_BANDS[index].color,
        };
      }),
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
      <section className="relative overflow-hidden rounded-2xl border border-brand-800 bg-brand-900 p-6 text-white sm:p-8" aria-label="Workspace overview">
        <div aria-hidden="true" className="pointer-events-none absolute -right-16 -top-32 h-80 w-80 rounded-full border-[48px] border-brand-700/30" />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-xl"><p className="text-xs font-semibold tracking-[0.16em] text-brand-200 uppercase">Your portfolio, in focus</p><h2 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">Welcome back{getStoredUsername() ? `, ${getStoredUsername()}` : ""}.</h2><p className="mt-3 text-sm leading-relaxed text-brand-100">Start an assessment or pick up the next case that needs your attention.</p></div>
          <div className="flex flex-wrap gap-3"><Link to="/scoring" className="btn-primary border border-brand-400 bg-brand-500 hover:bg-brand-600">New assessment <span aria-hidden="true">＋</span></Link><Link to="/action-desk?actionable_only=true" className="btn-secondary border-brand-600 bg-brand-800 text-white hover:bg-brand-700">View next actions <span aria-hidden="true">→</span></Link></div>
        </div>
      </section>

      <section className="grid gap-3 min-[360px]:grid-cols-2 sm:gap-4 xl:grid-cols-5">
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
          hint="Recorded approved facilities"
          accent="slate"
        />
        <StatCard
          label="Open EWS alerts"
          value={openCount}
          hint={worstOpenDrop !== null ? `Worst drop ${worstOpenDrop.toFixed(1)} pts` : "No open alerts recorded"}
          accent={openCount ? "rose" : "emerald"}
        />
      </section>

      <ActionDeskPreview />

      <section className="grid gap-3 md:grid-cols-3" aria-label="Quick access">
        {[
          { to: "/applications", number: "01", title: "Find an application", detail: "Search the register and open a case for review." },
          { to: "/alerts", number: "02", title: "Record a monitoring month", detail: "Choose a facility and review its reporting calendar." },
          { to: "/reminders", number: "03", title: "Prepare a follow-up", detail: "Review payment evidence and reminder drafts." },
        ].map(item => <Link key={item.to} to={item.to} className="group flex gap-4 rounded-2xl border border-slate-200 bg-white p-5 transition hover:border-brand-300 hover:shadow-sm"><span className="pt-1 text-xs font-bold text-brand-600">{item.number}</span><div className="flex-1"><h2 className="text-sm font-bold text-slate-900 group-hover:text-brand-700">{item.title} <span aria-hidden="true">↗</span></h2><p className="mt-2 text-xs leading-relaxed text-slate-500">{item.detail}</p></div></Link>)}
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
            {portfolio?.histogram_policy_version ? (
              <span className="text-xs text-slate-500" data-testid="histogram-policy">
                Colours: current policy v{portfolio.histogram_policy_version} ·{" "}
                {describeBands(portfolio.histogram_bands)}
              </span>
            ) : null}
          </div>
          <div className="px-5 py-4" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={histogramData} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                <XAxis
                  dataKey="label"
                  interval={0}
                  tick={{ fontSize: 10, fill: "#64748b" }}
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
              riskBand={latest ? (latest.risk_band ?? bandForDecision(latest.decision).riskBand) : null}
              bands={latest ? latest.policy?.bands : portfolio?.histogram_bands}
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
    <div className="card min-w-0 px-4 py-4 min-[360px]:last:col-span-2 sm:px-5 xl:last:col-span-1">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className={`tabular mt-1 break-words text-xl font-bold sm:text-2xl ${accentClass}`}>{value}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}
