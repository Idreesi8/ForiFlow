import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getStoredRole } from "../api/auth.js";
import {
  apiErrorMessage,
  fetchAlerts,
  resolveAlert,
  takeAlertForReview,
} from "../api/client.js";
import { alertSeverity, alertStatusStyle } from "../lib/decisions.js";
import { formatDateTime, formatRelative } from "../lib/format.js";
import { AlertStatusBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState, Spinner } from "./common/States.jsx";

// "Open" = not yet resolved (Active, or In Review with an officer).
const STATUS_FILTERS = ["Open", "Active", "In Review", "Resolved", "All"];
const NOTE_MIN = 5;

/**
 * Early Warning System alert feed.
 *
 * Reads `GET /ews/alerts` (already sorted worst-first by the API). Any officer
 * can take an alert for review (`PATCH /ews/alerts/{id}/review`); an admin
 * closes it with a note (`PATCH /ews/alerts/{id}/resolve`).
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
  const [statusFilter, setStatusFilter] = useState("Open");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [noteFor, setNoteFor] = useState(null);
  const [note, setNote] = useState("");
  // The API enforces this (403 for analysts); hiding the button just avoids a dead click.
  const canResolve = getStoredRole() === "admin";

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

  const replaceAlert = (updated) =>
    setAlerts((previous) => {
      const next = previous.map((alert) => (alert.id === updated.id ? updated : alert));
      onAlertsLoadedRef.current?.(next);
      return next;
    });

  const handleTakeForReview = async (alertId) => {
    setBusyId(alertId);
    try {
      replaceAlert(await takeAlertForReview(alertId));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not take the alert for review."));
    } finally {
      setBusyId(null);
    }
  };

  const handleResolve = async (alertId) => {
    setBusyId(alertId);
    try {
      replaceAlert(await resolveAlert(alertId, note.trim()));
      setNoteFor(null);
      setNote("");
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not resolve the alert."));
    } finally {
      setBusyId(null);
    }
  };

  const visibleAlerts = useMemo(
    () =>
      statusFilter === "All"
        ? alerts
        : statusFilter === "Open"
          ? alerts.filter((alert) => alert.alert_status !== "Resolved")
          : alerts.filter((alert) => alert.alert_status === statusFilter),
    [alerts, statusFilter],
  );
  const activeCount = useMemo(
    () => alerts.filter((alert) => alert.alert_status === "Active").length,
    [alerts],
  );
  const inReviewCount = useMemo(
    () => alerts.filter((alert) => alert.alert_status === "In Review").length,
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
        <div className="grid gap-px border-b border-slate-200 bg-slate-200 sm:grid-cols-4">
          <FeedStat label="Alerts shown" value={visibleAlerts.length} />
          <FeedStat label="Active" value={activeCount} tone="danger" />
          <FeedStat label="In review" value={inReviewCount} />
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
                const isBusy = busyId === alert.id;

                return (
                  <Fragment key={alert.id}>
                  <tr className={`hover:bg-slate-50 ${statusStyle.rowClass}`}>
                    <td className="px-5 py-3">
                      <span className={`badge ${severity.className}`}>{severity.label}</span>
                    </td>
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        onClick={() => navigate(`/shap/${alert.borrower_id}`)}
                        className="font-semibold text-brand-700 hover:underline"
                      >
                        {alert.business_name ?? `Borrower #${alert.borrower_id}`}
                      </button>
                      <p className="text-xs whitespace-nowrap text-slate-500">
                        App #{alert.borrower_id} · Alert #{alert.id}
                      </p>
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
                      {isResolved && alert.resolved_by ? (
                        <p className="mt-1 text-xs text-slate-500">by {alert.resolved_by}</p>
                      ) : alert.assigned_to ? (
                        <p className="mt-1 text-xs text-slate-500">with {alert.assigned_to}</p>
                      ) : null}
                    </td>
                    <td className="px-5 py-3 text-slate-600">
                      <span title={formatDateTime(alert.triggered_at)}>
                        {formatRelative(alert.triggered_at)}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      {isResolved ? (
                        <span className="text-xs text-slate-400" title={formatDateTime(alert.resolved_at)}>
                          {formatRelative(alert.resolved_at)}
                        </span>
                      ) : (
                        <span className="inline-flex gap-2">
                          {alert.alert_status === "Active" ? (
                            <button
                              type="button"
                              onClick={() => handleTakeForReview(alert.id)}
                              disabled={isBusy}
                              className="btn-secondary py-1.5 text-xs"
                            >
                              {isBusy && noteFor !== alert.id ? (
                                <Spinner className="h-3.5 w-3.5" />
                              ) : (
                                "Take for review"
                              )}
                            </button>
                          ) : null}
                          {canResolve ? (
                            <button
                              type="button"
                              onClick={() => {
                                setNoteFor(noteFor === alert.id ? null : alert.id);
                                setNote("");
                              }}
                              disabled={isBusy}
                              className="btn-secondary py-1.5 text-xs"
                            >
                              Resolve
                            </button>
                          ) : (
                            <span
                              className="self-center text-xs text-slate-400"
                              title="Resolving an alert needs the admin role."
                            >
                              Resolve: admin
                            </span>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                  {isResolved && alert.resolution_note ? (
                    <tr className={statusStyle.rowClass}>
                      <td colSpan={9} className="px-5 pb-3 text-xs text-slate-600">
                        <span className="font-semibold">Resolution:</span> {alert.resolution_note}
                      </td>
                    </tr>
                  ) : null}
                  {noteFor === alert.id && !isResolved ? (
                    <tr className="bg-slate-50">
                      <td colSpan={9} className="px-5 py-3">
                        <label className="field-label" htmlFor={`resolve-note-${alert.id}`}>
                          How was alert #{alert.id} resolved?
                        </label>
                        <div className="flex flex-wrap items-start gap-2">
                          <input
                            id={`resolve-note-${alert.id}`}
                            type="text"
                            maxLength={1000}
                            value={note}
                            onChange={(event) => setNote(event.target.value)}
                            placeholder="e.g. Borrower paid the arrears on 12 Oct."
                            className="field-input max-w-xl flex-1 py-1.5"
                          />
                          <button
                            type="button"
                            onClick={() => handleResolve(alert.id)}
                            disabled={isBusy || note.trim().length < NOTE_MIN}
                            className="btn-primary py-1.5 text-xs"
                          >
                            {isBusy ? <Spinner className="h-3.5 w-3.5 text-white" /> : "Confirm resolve"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setNoteFor(null)}
                            className="btn-ghost py-1.5 text-xs"
                          >
                            Cancel
                          </button>
                        </div>
                        <p className="mt-1 text-xs text-slate-500">
                          Saved with your name. At least {NOTE_MIN} characters.
                        </p>
                      </td>
                    </tr>
                  ) : null}
                  </Fragment>
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
  if (statusFilter === "Open") {
    if (resolvedCount > 0) {
      return "No open alerts. Closed cases are listed under Resolved.";
    }
    return "No borrower has dropped more than 15 points below their origination score.";
  }
  if (statusFilter === "Active") {
    if (resolvedCount > 0) {
      return "No active alerts. Closed cases are listed under Resolved.";
    }
    return "No borrower has dropped more than 15 points below their origination score.";
  }
  if (statusFilter === "Resolved") {
    return "No resolved alerts yet.";
  }
  if (statusFilter === "In Review") {
    return "No alert is being handled right now. Use Take for review on an active alert.";
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
