import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { canDecideCredit } from "../api/auth.js";
import {
  apiErrorMessage,
  fetchAlertHistory,
  fetchAlertQueue,
} from "../api/client.js";
import {
  ACTION_LABELS,
  ALERT_STATUSES,
  alertActions,
  alertEvidence,
  alertStatusStyle,
  formatDeterioration,
  isOpenAlert,
} from "../lib/ews.js";
import { formatDate, formatDateTime, formatRelative } from "../lib/format.js";
import AlertActionDialog from "./AlertActionDialog.jsx";
import { AlertSeverityBadge, AlertStatusBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState } from "./common/States.jsx";

const FILTERS = [
  { key: "attention", label: "Needs attention" },
  ...ALERT_STATUSES.map((status) => ({ key: status, label: status })),
  { key: "all", label: "All" },
];

/**
 * Early Warning System alert queue.
 *
 * Reads `GET /ews/alert-queue` (open first, worst severity first). Severity,
 * reasons and evidence are the API's; nothing is recomputed here. Managers
 * and admins acknowledge, assign, set a due date, mark Action Required,
 * resolve or dismiss; every step is written to the audit trail by the API.
 * Closed alerts stay listed.
 */
export default function EWSAlertFeed({
  limit = 25,
  maxRows = null,
  compact = false,
  showFilters = true,
  onAlertsLoaded,
  refreshToken = 0,
  facilityId = null,
  onChanged,
}) {
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState([]);
  const [filter, setFilter] = useState("attention");
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [queue, setQueue] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [candidate, setCandidate] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [history, setHistory] = useState({});
  // The API enforces this (403 for analysts); hiding the buttons avoids dead clicks.
  const canManage = canDecideCredit();

  const onAlertsLoadedRef = useRef(onAlertsLoaded);
  const alertRequestSequence = useRef(0);
  const activeRequest = useRef(null);
  const historyRequests = useRef({});
  onAlertsLoadedRef.current = onAlertsLoaded;
  const pageSize = maxRows || limit;
  const requestKey = JSON.stringify([facilityId, filter, search.trim(), page, pageSize]);
  const ready = queue?.key === requestKey;

  const loadAlerts = useCallback(async () => {
    const request = ++alertRequestSequence.current;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      const params = { limit: pageSize, offset: page * pageSize, search: search.trim() };
      if (facilityId) params.facility_id = facilityId;
      if (filter === 'attention') params.open_only = true;
      else if (filter !== 'all') params.alert_status = filter;
      const data = await fetchAlertQueue(params, { signal: controller.signal });
      if (request !== alertRequestSequence.current) return;
      if (page > 0 && page * pageSize >= data.matching) {
        setPage(Math.max(0, Math.ceil(data.matching / pageSize) - 1));
        return;
      }
      setQueue({ ...data, key: requestKey });
      setAlerts(data.items);
      onAlertsLoadedRef.current?.(data.items, data.counts);
    } catch (requestError) {
      if (request === alertRequestSequence.current) setError(apiErrorMessage(requestError, "Could not load EWS alerts."));
    } finally {
      if (request === alertRequestSequence.current) setIsLoading(false);
    }
  }, [pageSize, facilityId, filter, search, page, requestKey]);

  useEffect(() => {
    loadAlerts();
    return () => { alertRequestSequence.current += 1; activeRequest.current?.abort(); };
  }, [loadAlerts, refreshToken]);

  const loadHistory = useCallback(async (alertId) => {
    const request = (historyRequests.current[alertId] || 0) + 1;
    historyRequests.current[alertId] = request;
    try {
      const entries = await fetchAlertHistory(alertId);
      if (request !== historyRequests.current[alertId]) return;
      setHistory((previous) => ({ ...previous, [alertId]: entries }));
    } catch (requestError) {
      if (request !== historyRequests.current[alertId]) return;
      setHistory((previous) => ({
        ...previous,
        [alertId]: { error: apiErrorMessage(requestError, "Could not load the history.") },
      }));
    }
  }, []);

  const toggleExpanded = (alertId) => {
    const next = expandedId === alertId ? null : alertId;
    setExpandedId(next);
    if (next !== null) loadHistory(next);
  };

  const savedAction = updated => {
    loadAlerts();
    setCandidate(null);
    if (expandedId === updated.id) loadHistory(updated.id);
    onChanged?.();
  };

  const visibleAlerts = ready && !error ? alerts : [];
  const counts = ready && !error ? queue.counts : { open: 0, critical: 0, overdue: 0, closed: 0 };
  const matching = ready && !error ? queue.matching : 0;
  const shownAlerts = visibleAlerts;
  const columns = 9;

  return (
    <section className="card" data-testid="ews-alert-feed">
      {candidate ? <AlertActionDialog candidate={candidate} onClose={() => setCandidate(null)} onSaved={savedAction} /> : null}
      <div className="card-header">
        <div className="flex items-center gap-3">
          <h2 className="card-title">Early warning alerts</h2>
          {counts.open > 0 ? (
            <span className="badge bg-rose-600 text-white">{counts.open} open</span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showFilters
            ? FILTERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => { setFilter(key); setPage(0); }}
                  aria-pressed={filter === key}
                  className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                    filter === key
                      ? "bg-brand-600 text-white"
                      : "border border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {label}
                </button>
              ))
            : null}
          <button type="button" onClick={loadAlerts} className="btn-secondary py-1.5">
            Refresh
          </button>
        </div>
      </div>

      {showFilters ? <div className="border-b border-slate-200 px-5 py-3">
        <label className="field-label" htmlFor="alert-search">Search all alerts</label>
        <input id="alert-search" type="search" maxLength={120} value={search}
          onChange={event => { setSearch(event.target.value); setPage(0); }}
          className="field-input" placeholder="Business, applicant or facility #" />
        <p className="mt-1 text-xs text-slate-500">Counts cover every matching alert, across all statuses. Results below use the selected status.</p>
      </div> : null}
      {!compact && ready && !error ? (
        <div className="grid gap-px border-b border-slate-200 bg-slate-200 sm:grid-cols-4">
          <FeedStat label="Open" value={counts.open} tone={counts.open ? "danger" : undefined} />
          <FeedStat
            label="Critical, open"
            value={counts.critical}
            tone={counts.critical ? "danger" : undefined}
          />
          <FeedStat
            label="Overdue actions"
            value={counts.overdue}
            tone={counts.overdue ? "danger" : undefined}
          />
          <FeedStat label="Resolved or dismissed" value={counts.closed} />
        </div>
      ) : null}

      {isLoading || (!ready && !error) ? (
        <LoadingState label="Loading alerts…" />
      ) : error ? (
        <ErrorState message={error} onRetry={loadAlerts} />
      ) : visibleAlerts.length === 0 ? (
        <EmptyState
          title="No alerts in this view"
          description={
            search.trim() ? "No alerts match this search and status. Try another name or choose All."
              : queue?.total === 0 ? "No facility has reached the WARNING or CRITICAL state."
              : "Nothing with this status. Closed alerts stay under Resolved and Dismissed."
          }
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="table-head">
              <tr>
                <th className="px-4 py-3 text-left">Severity</th>
                <th className="px-4 py-3 text-left">Facility</th>
                <th className="px-4 py-3 text-left">Reasons</th>
                <th className="px-4 py-3 text-right">Baseline</th>
                <th className="px-4 py-3 text-right">Current</th>
                <th className="px-4 py-3 text-right">Change</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Raised</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shownAlerts.map((alert) => {
                const style = alertStatusStyle(alert.alert_status);
                const actions = alertActions(alert, { canManage });
                const expanded = expandedId === alert.id;
                return (
                  <Fragment key={alert.id}>
                    <tr className={`hover:bg-slate-50 ${style.rowClass}`} data-alert-id={alert.id}>
                      <td className="px-4 py-3">
                        <AlertSeverityBadge alert={alert} />
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => navigate(`/shap/${alert.borrower_id}`)}
                          className="font-semibold text-brand-700 hover:underline"
                        >
                          {alert.business_name ?? `Facility #${alert.borrower_id}`}
                        </button>
                        <p className="text-xs whitespace-nowrap text-slate-500">
                          App #{alert.borrower_id} · Alert #{alert.id}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {alert.reason_codes?.length ? (
                          <div className="flex max-w-xs flex-wrap gap-1">
                            {alert.reason_codes.map((code) => (
                              <span
                                key={code}
                                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700"
                              >
                                {code}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-xs text-slate-400">
                            {alert.is_legacy ? "Not recorded (before 2.1)" : "—"}
                          </span>
                        )}
                      </td>
                      <td className="tabular px-4 py-3 text-right text-slate-600">
                        {alert.baseline_score.toFixed(1)}
                      </td>
                      <td className="tabular px-4 py-3 text-right font-semibold text-slate-900">
                        {alert.current_score.toFixed(1)}
                      </td>
                      <td className="tabular px-4 py-3 text-right font-bold text-rose-600">
                        {formatDeterioration(alert.score_drop)}
                      </td>
                      <td className="px-4 py-3">
                        <AlertStatusBadge status={alert.alert_status} />
                        <FollowUp alert={alert} />
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        <span title={formatDateTime(alert.triggered_at)}>
                          {formatRelative(alert.triggered_at)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex flex-wrap justify-end gap-1.5">
                          {actions.map((step) => (
                            <button
                              key={step}
                              type="button"
                              onClick={() => setCandidate({ alert, step })}
                              className={`py-1 text-xs ${
                                step === "acknowledge" || step === "resolve"
                                  ? "btn-primary"
                                  : "btn-secondary"
                              }`}
                            >
                              {ACTION_LABELS[step]}
                            </button>
                          ))}
                          {!canManage && isOpenAlert(alert) ? (
                            <span
                              className="self-center text-xs text-slate-400"
                              title="Alert follow-up needs a manager or admin."
                            >
                              Manager follow-up
                            </span>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => toggleExpanded(alert.id)}
                            className="btn-ghost py-1 text-xs"
                            aria-expanded={expanded}
                          >
                            {expanded ? "Hide" : "Details"}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {expanded ? (
                      <tr className="bg-white">
                        <td colSpan={columns} className="px-5 py-4">
                          <AlertDetails alert={alert} history={history[alert.id]} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {maxRows && shownAlerts.length < matching ? (
            <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
              Showing {shownAlerts.length} of {matching}.{" "}
              <button
                type="button"
                onClick={() => navigate("/alerts")}
                className="font-semibold text-brand-700 hover:underline"
              >
                See all alerts
              </button>
            </p>
          ) : null}
        </div>
      )}
      {!maxRows && ready && !error && matching > 0 ? <nav aria-label="Alert result pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-3 text-sm">
        <p role="status">{page * pageSize + 1}–{page * pageSize + shownAlerts.length} of {matching} alerts</p>
        <div className="flex gap-2"><button type="button" className="btn-secondary" disabled={isLoading || page === 0} onClick={() => setPage(value => value - 1)}>Previous</button>
          <button type="button" className="btn-secondary" disabled={isLoading || (page + 1) * pageSize >= matching} onClick={() => setPage(value => value + 1)}>Next</button></div>
      </nav> : null}
    </section>
  );
}

function FollowUp({ alert }) {
  if (!isOpenAlert(alert)) {
    return alert.resolved_by ? (
      <p className="mt-1 text-xs text-slate-500" title={formatDateTime(alert.resolved_at)}>
        by {alert.resolved_by} · {formatDate(alert.resolved_at)}
      </p>
    ) : null;
  }
  return (
    <div className="mt-1 space-y-0.5 text-xs text-slate-500">
      {alert.acknowledged_by ? <p>ack. {alert.acknowledged_by}</p> : null}
      {alert.assigned_to ? <p>with {alert.assigned_to}</p> : null}
      {alert.action_due_date ? (
        <p className={alert.is_overdue ? "font-semibold text-rose-700" : ""}>
          due {formatDate(alert.action_due_date)}
          {alert.is_overdue ? " · overdue" : ""}
        </p>
      ) : null}
    </div>
  );
}

function AlertDetails({ alert, history }) {
  const evidence = alertEvidence(alert);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div>
        <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Evidence</h4>
        {evidence.length ? (
          <ul className="mt-2 space-y-1.5 text-sm text-slate-700">
            {evidence.map((item, index) => (
              <li key={index}>
                <span className="font-medium">{item.label}.</span> {item.text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">
            None stored. This alert was raised before 2.1 by a score drop alone.
          </p>
        )}
        {alert.previous_score !== null && alert.previous_score !== undefined ? (
          <p className="mt-2 text-xs text-slate-500">
            Previous month {alert.previous_score.toFixed(1)} · latest{" "}
            {alert.current_score.toFixed(1)}
          </p>
        ) : null}
      </div>
      <div>
        <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Recommended actions
        </h4>
        {alert.recommended_actions?.length ? (
          <ul className="mt-2 list-disc space-y-1 pl-4 text-sm text-slate-700">
            {alert.recommended_actions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">None stored for this alert.</p>
        )}
        <p className="mt-2 text-xs text-slate-500">
          Recommendations only. ForiFlow does not approve, reject, freeze or restructure a
          facility.
        </p>
        {alert.action_note ? (
          <p className="mt-2 text-sm text-slate-700">
            <span className="font-semibold">Action:</span> {alert.action_note}
          </p>
        ) : null}
        {alert.resolution_note ? (
          <p className="mt-2 text-sm text-slate-700">
            <span className="font-semibold">
              {alert.alert_status === "Dismissed" ? "Dismissed:" : "Resolution:"}
            </span>{" "}
            {alert.resolution_note}
          </p>
        ) : null}
      </div>
      <div>
        <h4 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">History</h4>
        {!history ? (
          <p className="mt-2 text-sm text-slate-500">Loading…</p>
        ) : history.error ? (
          <p className="mt-2 text-sm text-rose-700">{history.error}</p>
        ) : history.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">
            No audit entries: raised before the audit trail existed.
          </p>
        ) : (
          <ol className="mt-2 space-y-1.5 text-xs text-slate-700">
            {history.map((entry) => (
              <li key={entry.id}>
                <span className="font-mono text-[11px] text-slate-500">
                  {formatDateTime(entry.occurred_at)}
                </span>{" "}
                <span className="font-semibold">
                  {entry.action.replace("ews.alert_", "").replaceAll("_", " ")}
                </span>{" "}
                by {entry.username}
                {entry.new_state?.alert_status ? ` → ${entry.new_state.alert_status}` : ""}
                {entry.details?.note ? `: ${entry.details.note}` : ""}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function FeedStat({ label, value, tone }) {
  return (
    <div className="bg-white px-5 py-3">
      <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</p>
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
