/**
 * Early Warning System display helpers (no React, so `npm test` can run them).
 *
 * The backend decides every EWS fact: the state of a facility, the severity
 * and reasons of an alert, the trend direction and whether there is enough
 * history for one. Nothing here compares a score with a threshold; these
 * helpers only choose words and colours for what the API returned. The
 * thresholds themselves are served by `GET /ews/methodology`.
 */

export const OPEN_ALERT_STATUSES = ["Open", "Acknowledged", "Action Required"];
export const CLOSED_ALERT_STATUSES = ["Resolved", "Dismissed"];
export const ALERT_STATUSES = [...OPEN_ALERT_STATUSES, ...CLOSED_ALERT_STATUSES];

/** Still needs attention. Uses the API's own flag when it sent one. */
export function isOpenAlert(alert) {
  if (!alert) return false;
  if (typeof alert.is_open === "boolean") return alert.is_open;
  return OPEN_ALERT_STATUSES.includes(alert.alert_status);
}

/** Monitoring states, mildest first. Kept apart from credit risk bands on purpose. */
export const EWS_STATES = ["NORMAL", "WATCH", "WARNING", "CRITICAL"];

const STATE_STYLES = {
  NORMAL: {
    label: "Normal",
    badgeClass: "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-300",
    dotClass: "bg-emerald-500",
    color: "#059669",
  },
  WATCH: {
    label: "Watch",
    badgeClass: "bg-sky-50 text-sky-800 ring-1 ring-sky-300",
    dotClass: "bg-sky-500",
    color: "#0284c7",
  },
  WARNING: {
    label: "Warning",
    badgeClass: "bg-amber-100 text-amber-900 ring-1 ring-amber-300",
    dotClass: "bg-amber-500",
    color: "#d97706",
  },
  CRITICAL: {
    label: "Critical",
    badgeClass: "bg-rose-600 text-white ring-1 ring-rose-700",
    dotClass: "bg-white",
    color: "#e11d48",
  },
};

const UNKNOWN_STATE = {
  label: "Not monitored",
  badgeClass: "bg-slate-100 text-slate-600 ring-1 ring-slate-300",
  dotClass: "bg-slate-400",
  color: "#94a3b8",
};

/** Words and colours for an EWS state returned by the API. */
export function ewsStateStyle(state) {
  return STATE_STYLES[state] ?? UNKNOWN_STATE;
}

/**
 * Severity of an alert, exactly as the API set it. An alert raised before
 * 2.1 has none (it was raised by a score drop alone) and is shown as such,
 * never guessed from its drop.
 */
export function alertSeverityStyle(alert) {
  const severity = alert?.severity ?? null;
  if (severity === null) {
    return {
      label: "Legacy",
      title: "Raised before 2.1 by a score drop alone; no severity or reasons were stored.",
      className: "bg-slate-200 text-slate-700",
    };
  }
  const style = ewsStateStyle(severity);
  return {
    label: style.label,
    title: `${style.label} severity`,
    className: severity === "CRITICAL" ? "bg-rose-600 text-white" : "bg-amber-500 text-white",
  };
}

const STATUS_STYLES = {
  Open: {
    badgeClass: "bg-rose-100 text-rose-800 ring-1 ring-rose-300",
    dotClass: "bg-rose-500",
    rowClass: "bg-rose-50/40",
  },
  Acknowledged: {
    badgeClass: "bg-amber-100 text-amber-800 ring-1 ring-amber-300",
    dotClass: "bg-amber-500",
    rowClass: "",
  },
  "Action Required": {
    badgeClass: "bg-violet-100 text-violet-800 ring-1 ring-violet-300",
    dotClass: "bg-violet-500",
    rowClass: "",
  },
  Resolved: {
    badgeClass: "bg-slate-100 text-slate-600 ring-1 ring-slate-300",
    dotClass: "bg-slate-400",
    rowClass: "opacity-75",
  },
  Dismissed: {
    badgeClass: "bg-white text-slate-500 ring-1 ring-slate-300 line-through",
    dotClass: "bg-slate-300",
    rowClass: "opacity-60",
  },
};

export function alertStatusStyle(status) {
  return STATUS_STYLES[status] ?? STATUS_STYLES.Resolved;
}

const TREND_STYLES = {
  Improving: { label: "Improving", symbol: "↗", className: "text-emerald-700" },
  Stable: { label: "Stable", symbol: "→", className: "text-slate-700" },
  Deteriorating: { label: "Deteriorating", symbol: "↘", className: "text-rose-700 font-semibold" },
  "Insufficient Data": { label: "Insufficient data", symbol: "·", className: "text-slate-400" },
};

export function trendStyle(direction) {
  return TREND_STYLES[direction] ?? TREND_STYLES["Insufficient Data"];
}

const SOURCE_LABELS = {
  ews_rule_adjusted: "EWS rules applied to the ForiFlow origination assessment",
  officer_override: "Officer Override",
  latest_foriflow_assessment: "ForiFlow Assessment",
  origination_assessment: "ForiFlow Assessment (origination)",
  legacy_unknown: "Unknown (recorded before 2.1)",
};

const SOURCE_SHORT = {
  ews_rule_adjusted: "EWS rules",
  officer_override: "Officer Override",
  latest_foriflow_assessment: "ForiFlow Assessment",
  origination_assessment: "ForiFlow Assessment",
  legacy_unknown: "Unknown",
};

/** "Score Source: …" text. An override is always named as one. */
export function scoreSourceLabel(source, { short = false } = {}) {
  const table = short ? SOURCE_SHORT : SOURCE_LABELS;
  return table[source] ?? "Unknown";
}

export function isOverride(source) {
  return source === "officer_override";
}

/**
 * Deterioration as the API reports it (positive means the score fell). Shown
 * as a signed change in score so a fall reads as a minus.
 */
export function formatDeterioration(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const amount = Number(value);
  if (amount === 0) return "0.0";
  return `${amount > 0 ? "−" : "+"}${Math.abs(amount).toFixed(1)}`;
}

/** Points for the score-history chart. The baseline is marked so it can be drawn apart. */
export function trendChartData(trend) {
  return (trend?.points ?? []).map((point) => ({
    label: point.label,
    month: point.month_number,
    score: point.score,
    source: point.score_source,
    isBaseline: point.month_number === 0,
    isOverride: isOverride(point.score_source),
    status: point.installment_status ?? null,
  }));
}

/** The API's own message when there are too few months for a trend, else null. */
export function trendMessage(trend) {
  if (!trend) return null;
  if (trend.message) return trend.message;
  if (trend.observations < trend.min_observations) return "Insufficient history for multi-month trend";
  return null;
}

/** Signals and state rules of an alert, ready to list. Nothing is added. */
export function alertEvidence(alert) {
  return (alert?.evidence ?? []).map((item) => ({
    kind: item.kind ?? "signal",
    code: item.code ?? null,
    label: item.label ?? item.code ?? "Evidence",
    text: item.evidence ?? "",
  }));
}

/**
 * The lifecycle steps an officer may take on an alert now. The server checks
 * the same rules; this only hides buttons that would be refused.
 */
export function alertActions(alert, { canManage }) {
  if (!canManage || !isOpenAlert(alert)) return [];
  const actions = [];
  if (alert.alert_status === "Open") actions.push("acknowledge");
  if (alert.alert_status === "Acknowledged") actions.push("action-required");
  actions.push("assign", "due-date", "resolve", "dismiss");
  return actions;
}

export const ACTION_LABELS = {
  acknowledge: "Acknowledge",
  "action-required": "Action required",
  assign: "Assign",
  "due-date": "Due date",
  resolve: "Resolve",
  dismiss: "Dismiss",
};

/** Where a timeline event came from, in words. */
export function timelineSourceLabel(event) {
  return event?.source === "record" ? "Stored record (before the audit trail)" : "Audit trail";
}

/** Order states worst first for the overview tiles. */
export function stateCounts(overview) {
  const counts = overview?.state_counts ?? {};
  return EWS_STATES.map((state) => ({ state, count: counts[state] ?? 0, ...ewsStateStyle(state) }));
}
