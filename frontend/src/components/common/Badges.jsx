import {
  alertStatusStyle,
  bandForDecision,
  decisionStatusOf,
  finalDecisionOf,
} from "../../lib/decisions.js";

/**
 * What the policy recommends for a score. Outlined, and worded as a
 * recommendation, so it is never read as a decision.
 */
export function RecommendationBadge({ decision, prefix = false }) {
  const band = bandForDecision(decision);
  return (
    <span className={`badge bg-white ring-1 ring-slate-300 ${band.textClass}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${band.dotClass}`} aria-hidden="true" />
      {prefix ? "Recommendation: " : ""}
      {band.recommendation}
    </span>
  );
}

/** An officer's decision (Approved / Rejected), as a filled chip. */
export function DecisionBadge({ decision }) {
  const band = bandForDecision(decision);
  return (
    <span className={`badge ${band.badgeClass}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${band.dotClass}`} aria-hidden="true" />
      {decision}
    </span>
  );
}

/** EWS alert lifecycle chip. Active alerts render red. */
export function AlertStatusBadge({ status }) {
  const style = alertStatusStyle(status);
  return (
    <span className={`badge ${style.badgeClass}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dotClass}`} aria-hidden="true" />
      {status}
    </span>
  );
}

const OPEN_STATUS = {
  Pending: { label: "Pending decision", tone: "bg-white text-amber-800 ring-1 ring-amber-300", dot: "bg-amber-500" },
  Escalated: { label: "Escalated to admin", tone: "bg-white text-violet-800 ring-1 ring-violet-300", dot: "bg-violet-500" },
  Superseded: { label: "Superseded", tone: "bg-slate-100 text-slate-600 ring-1 ring-slate-300", dot: "bg-slate-400" },
};

/**
 * The human decision. "Pending decision" until an officer decides, whatever
 * the policy recommended.
 */
export function FinalDecisionBadge({ application }) {
  const final = finalDecisionOf(application);
  if (final === null) {
    const open = OPEN_STATUS[decisionStatusOf(application)] ?? OPEN_STATUS.Pending;
    return (
      <span className={`badge ${open.tone}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${open.dot}`} aria-hidden="true" />
        {open.label}
      </span>
    );
  }
  return <DecisionBadge decision={final} />;
}
