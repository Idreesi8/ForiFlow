import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { canDecideCredit } from "../api/auth.js";
import {
  alertLifecycle,
  apiErrorMessage,
  fetchAlertHistory,
  fetchAlerts,
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
import { AlertSeverityBadge, AlertStatusBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState, Spinner } from "./common/States.jsx";

const FILTERS = [
  { key: "attention", label: "Needs attention" },
  ...ALERT_STATUSES.map((status) => ({ key: status, label: status })),
  { key: "all", label: "All" },
];
const NOTE_MIN = 5;
const EMPTY_FORM = { alertId: null, step: null, note: "", assigned_to: "", due_date: "" };

/**
 * Early Warning System alert queue.
 *
 * Reads `GET /ews/alerts` (open first, worst severity first). Severity,
 * reasons and evidence are the API's; nothing is recomputed here. Managers
 * and admins acknowledge, assign, set a due date, mark Action Required,
 * resolve or dismiss; every step is written to the audit trail by the API.
 * Closed alerts stay listed.
 */
export default function EWSAlertFeed({
  limit = 200,
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
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [expandedId, setExpandedId] = useState(null);
  const [history, setHistory] = useState({});
  // The API enforces this (403 for analysts); hiding the buttons avoids dead clicks.
  const canManage = canDecideCredit();

  const onAlertsLoadedRef = useRef(onAlertsLoaded);
  onAlertsLoadedRef.current = onAlertsLoaded;

  const loadAlerts = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params = { limit };
      if (facilityId) params.facility_id = facilityId;
      const data = await fetchAlerts(params);
      setAlerts(data);
      onAlertsLoadedRef.current?.(data);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load EWS alerts."));
    } finally {
      setIsLoading(false);
    }
  }, [limit, facilityId]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts, refreshToken]);

  const loadHistory = useCallback(async (alertId) => {
    try {
      const entries = await fetchAlertHistory(alertId);
      setHistory((previous) => ({ ...previous, [alertId]: entries }));
    } catch (requestError) {
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

  const replaceAlert = (updated) =>
    setAlerts((previous) => {
      const next = previous.map((alert) => (alert.id === updated.id ? updated : alert));
      onAlertsLoadedRef.current?.(next);
      return next;
    });

  const submitStep = async (alertId, step, payload) => {
    setBusyId(alertId);
    setError(null);
    try {
      replaceAlert(await alertLifecycle(alertId, step, payload));
      setForm(EMPTY_FORM);
      if (expandedId === alertId) loadHistory(alertId);
      onChanged?.();
    } catch (requestError) {
      setError(
        apiErrorMessage(requestError, `Could not ${ACTION_LABELS[step].toLowerCase()} the alert.`),
      );
    } finally {
      setBusyId(null);
    }
  };

  const openForm = (alert, step) => {
    if (step === "acknowledge") {
      submitStep(alert.id, step, {});
      return;
    }
    setForm(
      form.alertId === alert.id && form.step === step
        ? EMPTY_FORM
        : {
            ...EMPTY_FORM,
            alertId: alert.id,
            step,
            assigned_to: alert.assigned_to ?? "",
            due_date: alert.action_due_date ?? "",
          },
    );
  };

  const formPayload = () => {
    const note = form.note.trim();
    const assignee = form.assigned_to.trim();
    switch (form.step) {
      case "assign":
        return {
          assigned_to: assignee,
          ...(form.due_date ? { due_date: form.due_date } : {}),
          ...(note ? { note } : {}),
        };
      case "due-date":
        return { due_date: form.due_date, ...(note ? { note } : {}) };
      case "action-required":
        return {
          action_note: note,
          ...(assignee ? { assigned_to: assignee } : {}),
          ...(form.due_date ? { due_date: form.due_date } : {}),
        };
      default:
        return { note };
    }
  };

  const formReady = () => {
    if (form.step === "assign") return form.assigned_to.trim().length > 0;
    if (form.step === "due-date") return Boolean(form.due_date);
    return form.note.trim().length >= NOTE_MIN;
  };

  const visibleAlerts = useMemo(() => {
    if (filter === "all") return alerts;
    if (filter === "attention") return alerts.filter(isOpenAlert);
    return alerts.filter((alert) => alert.alert_status === filter);
  }, [alerts, filter]);
  const counts = useMemo(() => {
    const open = alerts.filter(isOpenAlert);
    return {
      open: open.length,
      critical: open.filter((alert) => alert.severity === "CRITICAL").length,
      overdue: open.filter((alert) => alert.is_overdue).length,
      closed: alerts.length - open.length,
    };
  }, [alerts]);
  const shownAlerts = maxRows ? visibleAlerts.slice(0, maxRows) : visibleAlerts;
  const columns = 9;

  return (
    <section className="card" data-testid="ews-alert-feed">
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
                  onClick={() => setFilter(key)}
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

      {!compact && alerts.length > 0 ? (
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

      {error && !isLoading && alerts.length > 0 ? (
        <p role="alert" className="border-b border-rose-200 bg-rose-50 px-5 py-2 text-sm text-rose-700">
          {error}
        </p>
      ) : null}

      {isLoading ? (
        <LoadingState label="Loading alerts…" />
      ) : error && alerts.length === 0 ? (
        <ErrorState message={error} onRetry={loadAlerts} />
      ) : visibleAlerts.length === 0 ? (
        <EmptyState
          title="No alerts in this view"
          description={
            alerts.length === 0
              ? "No facility has reached the WARNING or CRITICAL state."
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
                const isBusy = busyId === alert.id;
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
                              disabled={isBusy}
                              onClick={() => openForm(alert, step)}
                              className={`py-1 text-xs ${
                                step === "acknowledge" || step === "resolve"
                                  ? "btn-primary"
                                  : "btn-secondary"
                              }`}
                            >
                              {isBusy && step === "acknowledge" ? (
                                <Spinner className="h-3.5 w-3.5 text-white" />
                              ) : (
                                ACTION_LABELS[step]
                              )}
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
                    {form.alertId === alert.id ? (
                      <tr className="bg-slate-50">
                        <td colSpan={columns} className="px-5 py-3">
                          <StepForm
                            alert={alert}
                            form={form}
                            setForm={setForm}
                            busy={isBusy}
                            ready={formReady()}
                            onSubmit={() => submitStep(alert.id, form.step, formPayload())}
                            onCancel={() => setForm(EMPTY_FORM)}
                          />
                        </td>
                      </tr>
                    ) : null}
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
          {shownAlerts.length < visibleAlerts.length ? (
            <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
              Showing {shownAlerts.length} of {visibleAlerts.length}.{" "}
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

const STEP_TITLES = {
  assign: "Assign the follow-up",
  "due-date": "Set the action due date",
  "action-required": "What must be done?",
  resolve: "How was it resolved?",
  dismiss: "Why is it dismissed?",
};

function StepForm({ alert, form, setForm, busy, ready, onSubmit, onCancel }) {
  const step = form.step;
  const set = (name) => (event) =>
    setForm((previous) => ({ ...previous, [name]: event.target.value }));
  const noteRequired = ["action-required", "resolve", "dismiss"].includes(step);
  return (
    <div className="space-y-2" data-step={step}>
      <p className="text-sm font-semibold text-slate-800">
        {STEP_TITLES[step]} <span className="font-normal text-slate-500">Alert #{alert.id}</span>
      </p>
      <div className="flex flex-wrap items-end gap-3">
        {step === "assign" || step === "action-required" ? (
          <label className="text-xs text-slate-600">
            Officer username{step === "assign" ? "" : " (optional)"}
            <input
              type="text"
              name="assigned_to"
              value={form.assigned_to}
              onChange={set("assigned_to")}
              maxLength={64}
              className="field-input mt-1 w-44 py-1.5"
              placeholder="e.g. zakria"
            />
          </label>
        ) : null}
        {step === "assign" || step === "due-date" || step === "action-required" ? (
          <label className="text-xs text-slate-600">
            Due date{step === "due-date" ? "" : " (optional)"}
            <input
              type="date"
              name="due_date"
              value={form.due_date}
              onChange={set("due_date")}
              className="field-input mt-1 w-40 py-1.5"
            />
          </label>
        ) : null}
        <label className="min-w-64 flex-1 text-xs text-slate-600">
          {step === "action-required" ? "Action" : "Note"}
          {noteRequired ? ` (at least ${NOTE_MIN} characters)` : " (optional)"}
          <input
            type="text"
            name="note"
            value={form.note}
            onChange={set("note")}
            maxLength={1000}
            className="field-input mt-1 py-1.5"
            placeholder={
              step === "action-required"
                ? "e.g. Visit the shop and collect the June bank statement"
                : step === "dismiss"
                  ? "e.g. Raised on a mistyped bureau balance"
                  : "e.g. Borrower paid the arrears on 12 Oct"
            }
          />
        </label>
        <button
          type="button"
          onClick={onSubmit}
          disabled={busy || !ready}
          className="btn-primary py-1.5 text-xs"
        >
          {busy ? <Spinner className="h-3.5 w-3.5 text-white" /> : `Confirm ${ACTION_LABELS[step].toLowerCase()}`}
        </button>
        <button type="button" onClick={onCancel} className="btn-ghost py-1.5 text-xs">
          Cancel
        </button>
      </div>
      <p className="text-xs text-slate-500">Saved with your name in the audit trail.</p>
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
