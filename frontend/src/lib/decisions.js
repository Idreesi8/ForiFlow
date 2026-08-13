/** Credit policy bands shared by the dial, tables and charts. */

export const DECISION_APPROVED = "Approved";
export const DECISION_MANUAL_REVIEW = "Manual Review";
export const DECISION_REJECTED = "Rejected";

/** Policy matrix: 0-40 Rejected, 41-70 Manual Review, 71-100 Approved. */
export const SCORE_BANDS = [
  {
    decision: DECISION_REJECTED,
    riskBand: "High Risk",
    min: 0,
    max: 40,
    range: "0 – 40",
    color: "#e11d48",
    softColor: "#ffe4e6",
    textClass: "text-rose-700",
    bgClass: "bg-rose-50",
    borderClass: "border-rose-200",
    badgeClass: "bg-rose-100 text-rose-800 ring-1 ring-rose-200",
    dotClass: "bg-rose-500",
  },
  {
    decision: DECISION_MANUAL_REVIEW,
    riskBand: "Medium Risk",
    min: 41,
    max: 70,
    range: "41 – 70",
    color: "#f59e0b",
    softColor: "#fef3c7",
    textClass: "text-amber-700",
    bgClass: "bg-amber-50",
    borderClass: "border-amber-200",
    badgeClass: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
    dotClass: "bg-amber-500",
  },
  {
    decision: DECISION_APPROVED,
    riskBand: "Low Risk",
    min: 71,
    max: 100,
    range: "71 – 100",
    color: "#059669",
    softColor: "#d1fae5",
    textClass: "text-emerald-700",
    bgClass: "bg-emerald-50",
    borderClass: "border-emerald-200",
    badgeClass: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
    dotClass: "bg-emerald-500",
  },
];

const FALLBACK_BAND = SCORE_BANDS[1];

/** Resolve the policy band for a 0-100 score. */
export function bandForScore(score) {
  const value = Number(score);
  if (Number.isNaN(value)) return FALLBACK_BAND;
  if (value <= 40) return SCORE_BANDS[0];
  if (value <= 70) return SCORE_BANDS[1];
  return SCORE_BANDS[2];
}

/** Resolve the band from a decision string returned by the API. */
export function bandForDecision(decision) {
  return SCORE_BANDS.find((band) => band.decision === decision) ?? FALLBACK_BAND;
}

/** Alert lifecycle styling. Active alerts are always red. */
export const ALERT_STATUS_STYLES = {
  Active: {
    badgeClass: "bg-rose-100 text-rose-800 ring-1 ring-rose-300",
    dotClass: "bg-rose-500",
    rowClass: "bg-rose-50/40",
  },
  "In Review": {
    badgeClass: "bg-amber-100 text-amber-800 ring-1 ring-amber-300",
    dotClass: "bg-amber-500",
    rowClass: "",
  },
  Resolved: {
    badgeClass: "bg-slate-100 text-slate-600 ring-1 ring-slate-300",
    dotClass: "bg-slate-400",
    rowClass: "opacity-70",
  },
};

export function alertStatusStyle(status) {
  return ALERT_STATUS_STYLES[status] ?? ALERT_STATUS_STYLES.Resolved;
}

/**
 * Severity of an EWS alert. The backend triggers above a 15 point drop, so
 * anything past double that threshold is treated as critical.
 */
export function alertSeverity(scoreDrop) {
  const drop = Number(scoreDrop) || 0;
  if (drop >= 30) return { label: "Critical", className: "bg-rose-600 text-white" };
  if (drop >= 22) return { label: "High", className: "bg-rose-500 text-white" };
  return { label: "Elevated", className: "bg-amber-500 text-white" };
}
