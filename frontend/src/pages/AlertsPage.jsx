import { useCallback, useEffect, useState } from "react";

import { apiErrorMessage, fetchEwsOverview } from "../api/client.js";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import EWSFacilityDetail from "../components/EWSFacilityDetail.jsx";
import EWSOverview from "../components/EWSOverview.jsx";
import MonitoringPanel from "../components/MonitoringPanel.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";

/**
 * Early Warning System workspace: the portfolio position, one facility's
 * history, the month entry form and the alert queue.
 */
export default function AlertsPage() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [refreshToken, setRefreshToken] = useState(0);

  const loadOverview = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchEwsOverview();
      setOverview(data);
      setSelectedId((current) => current ?? data.rows[0]?.facility_id ?? null);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the EWS overview."));
    }
  }, []);

  useEffect(() => {
    loadOverview();
  }, [loadOverview, refreshToken]);

  const refresh = () => setRefreshToken((token) => token + 1);
  const method = overview?.methodology;

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">Early Warning System</h2>
        <p className="mt-1 max-w-4xl text-sm text-slate-500">
          Monitoring of approved facilities from officer-recorded months. The EWS is rule- and
          trend-based: it is not a model that predicts default, and it recommends follow-up
          without changing any facility or credit decision. There is no live ECIB connector.
        </p>
      </header>

      {error ? (
        <ErrorState message={error} onRetry={loadOverview} />
      ) : !overview ? (
        <LoadingState label="Loading the EWS overview…" />
      ) : (
        <EWSOverview overview={overview} selectedId={selectedId} onSelect={setSelectedId} />
      )}

      {selectedId ? <EWSFacilityDetail facilityId={selectedId} refreshToken={refreshToken} /> : null}

      <MonitoringPanel
        facilityId={selectedId}
        onMonitored={(response) => {
          setSelectedId(response.borrower_id);
          refresh();
        }}
      />

      <EWSAlertFeed refreshToken={refreshToken} onChanged={refresh} />

      {method ? (
        <section className="card" data-testid="ews-methodology">
          <div className="card-header">
            <h2 className="card-title">Methodology</h2>
          </div>
          <div className="grid gap-4 px-5 py-4 text-sm text-slate-700 md:grid-cols-2">
            <ul className="list-disc space-y-1 pl-5">
              <li>
                WARNING when the monitored score is more than {method.score_drop_warning} points below
                the origination baseline; CRITICAL from {method.score_drop_critical} points, or when
                the latest month is {method.critical_statuses.join(" or ")}.
              </li>
              <li>
                A trend direction needs {method.trend_min_observations} recorded months; it is the
                least-squares slope, with ±{method.trend_slope_points_per_month} points a month as
                the line between Stable and a direction.
              </li>
              <li>
                Signals: bureau balance up more than {method.balance_increase_pct}%, POS inflow down
                more than {method.pos_decline_pct}%, repayment later than the month before.
              </li>
              <li>Alerts are raised at {method.alert_states.join(" and ")}; one open alert per facility.</li>
            </ul>
            <ul className="list-disc space-y-1 pl-5">
              {method.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}
    </div>
  );
}
