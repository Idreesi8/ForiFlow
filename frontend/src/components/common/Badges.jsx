import { alertStatusStyle, bandForDecision } from "../../lib/decisions.js";

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
