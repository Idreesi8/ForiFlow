import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiErrorMessage, fetchAlerts, resolveAlert } from "../api/client.js";
import { alertSeverity, alertStatusStyle } from "../lib/decisions.js";
import { formatDateTime, formatRelative } from "../lib/format.js";
import { AlertStatusBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState, Spinner } from "./common/States.jsx";

const STATUS_FILTERS = ["All", "Active", "Resolved"];

/**
 * Early Warning System alert feed.
 *
 * Reads `GET /ews/alerts` (already sorted worst-first by the API) and lets an
 * officer close an alert through `PATCH /ews/alerts/{id}/resolve`.
 */
export default function EWSAlertFeed({
  limit = 50,
  compact = false,
  showFilters = true,
  onAlertsLoaded,
  refreshToken = 0,
}) {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [statusFilter, setStatusFilter] = useState("Active");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resolvingId, setResolvingId] = useState(null);

  // Held in a ref so a parent re-render never retriggers the fetch effect.
  const onAlertsLoadedRef = useRef(onAlertsLoaded);
  onAlertsLoadedRef.current = onAlertsLoaded;

  const loadAlerts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      // Load the full queue and filter in the client so tab switches are
      // instant and Resolve updates Active/Resolved without a refetch.
      const data = await fetchAlerts({ limit });
      setAlerts(data);
      onAlertsLoadedRef.current?.(data);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load EWS alerts."));
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts, refreshToken]);

  const handleResolve = async (alertId) => {
    setResolvingId(alertId);
    try {
      const updated = await resolveAlert(alertId);
      setAlerts((previous) => {
        const next = previous.map((alert) => (alert.id === alertId ? updated : alert));
        onAlertsLoadedRef.current?.(next);
        return next;
      });
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not resolve the alert."));
    } finally {
      setResolvingId(null);
    }
  };

  const visibleAlerts = useMemo(
    () =>
      statusFilter === "All"
        ? alerts
        : alerts.filter((alert) => alert.alert_status === statusFilter),
    [alerts, statusFilter],
  );
  const activeCount = useMemo(
    () => alerts.filter((alert) => alert.alert_status === "Active").length,
    [alerts],
  );
  const resolvedCount = useMemo(
    () => alerts.filter((alert) => alert.alert_status === "Resolved").length,
    [alerts],
  );
  const worstDrop = useMemo(
    () => visibleAlerts.reduce((worst, alert) => Math.max(worst, alert.score_drop), 0),
    [visibleAlerts],
  );

  return (
    <section className="card">
      <div className="card-header">
        <div className="flex items-center gap-3">
          <h2 className="card-title">Early warning alerts</h2>
          {activeCount > 0 ? (
            <span className="badge animate-pulse bg-rose-600 text-white">
              {activeCount} active
            </span>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {showFilters
            ? STATUS_FILTERS.map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => setStatusFilter(status)}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                    statusFilter === status
                      ? "bg-brand-600 text-white"
                      : "border border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {status}
                </button>
              ))
            : null}
          <button type="button" onClick={loadAlerts} className="btn-secondary py-1.5">
            Refresh
          </button>
        </div>
      </div>

      {!compact && visibleAlerts.length > 0 ? (
        <div className="grid gap-px border-b border-slate-200 bg-slate-200 sm:grid-cols-3">
          <FeedStat label="Alerts shown" value={visibleAlerts.length} />
          <FeedStat label="Active" value={activeCount} tone="danger" />
          <FeedStat label="Worst score drop" value={`${worstDrop.toFixed(1)} pts`} tone="danger" />
        </div>
      ) : null}

      {isLoading ? (
        <LoadingState label="Loading alerts…" />
      ) : error ? (
        <ErrorState message={error} onRetry={loadAlerts} />
      ) : visibleAlerts.length === 0 ? (
        <EmptyState
          title="No alerts in this view"
          description={emptyStateDescription(statusFilter, {
            hasAny: alerts.length > 0,
            resolvedCount,
          })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="table-head">
              <tr>
                <th className="px-5 py-3 text-left">Severity</th>
                <th className="px-5 py-3 text-left">Borrower</th>
                <th className="px-5 py-3 text-right">Baseline</th>
                <th className="px-5 py-3 text-right">Current</th>
                <th className="px-5 py-3 text-right">Drop</th>
                <th className="px-5 py-3 text-right">Days to default</th>
                <th className="px-5 py-3 text-left">Status</th>
                <th className="px-5 py-3 text-left">Triggered</th>
                <th className="px-5 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibleAlerts.map((alert) => {
                const severity = alertSeverity(alert.score_drop);
                const statusStyle = alertStatusStyle(alert.alert_status);
                const isResolved = alert.alert_status === "Resolved";

                return (
                  <tr key={alert.id} className={`hover:bg-slate-50 ${statusStyle.rowClass}`}>
                    <td className="px-5 py-3">
                      <span className={`badge ${severity.className}`}>{severity.label}</span>
                    </td>
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        onClick={() => navigate(`/shap/${alert.borrower_id}`)}
                        className="font-semibold text-brand-700 hover:underline"
                      >
                        Borrower #{alert.borrower_id}
                      </button>
                      <p className="text-xs text-slate-500">Alert #{alert.id}</p>
                    </td>
                    <td className="tabular px-5 py-3 text-right text-slate-600">
                      {alert.baseline_score.toFixed(1)}
                    </td>
                    <td className="tabular px-5 py-3 text-right font-semibold text-slate-900">
                      {alert.current_score.toFixed(1)}
                    </td>
                    <td className="tabular px-5 py-3 text-right font-bold text-rose-600">
                      −{alert.score_drop.toFixed(1)}
                    </td>
                    <td className="tabular px-5 py-3 text-right">
                      <span
                        className={
                          alert.estimated_days_to_default <= 30
                            ? "font-semibold text-rose-600"
                            : "text-slate-700"
                        }
                      >
                        {alert.estimated_days_to_default}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <AlertStatusBadge status={alert.alert_status} />
                    </td>
                    <td className="px-5 py-3 text-slate-600">
                      <span title={formatDateTime(alert.triggered_at)}>
                        {formatRelative(alert.triggered_at)}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right">
                      {isResolved ? (
                        <span className="text-xs text-slate-400">
                          {formatRelative(alert.resolved_at)}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleResolve(alert.id)}
                          disabled={resolvingId === alert.id}
                          className="btn-secondary py-1.5 text-xs"
                        >
                          {resolvingId === alert.id ? (
                            <Spinner className="h-3.5 w-3.5" />
                          ) : (
                            "Resolve"
                          )}
                        </button>
                      )}
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

function emptyStateDescription(statusFilter, { hasAny, resolvedCount }) {
  if (statusFilter === "Active") {
    if (resolvedCount > 0) {
      return "No active alerts. Closed cases are listed under Resolved.";
    }
    return "No borrower has dropped more than 15 points below their origination score.";
  }
  if (statusFilter === "Resolved") {
    return "No resolved alerts yet.";
  }
  if (statusFilter === "All" && !hasAny) {
    return "No borrower has dropped more than 15 points below their origination score.";
  }
  return "Nothing recorded for this status yet.";
}

function FeedStat({ label, value, tone }) {
  return (
    <div className="bg-white px-5 py-3">
      <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">
        {label}
      </p>
      <p
        className={`tabular mt-0.5 text-xl font-bold ${
          tone === "danger" ? "text-rose-600" : "text-slate-900"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
