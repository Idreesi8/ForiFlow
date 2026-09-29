import { alertStatusStyle, bandForDecision, finalDecisionOf } from "../../lib/decisions.js";

/** Colour-coded credit decision chip used in tables and detail panels. */
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

/**
 * The decision that stands. A Manual Review case shows "Pending review" until
 * an officer decides, then the officer's decision.
 */
export function FinalDecisionBadge({ application }) {
  const final = finalDecisionOf(application);
  if (final === null) {
    return (
      <span className="badge bg-white text-amber-800 ring-1 ring-amber-300">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden="true" />
        Pending review
      </span>
    );
  }
  return <DecisionBadge decision={final} />;
}
