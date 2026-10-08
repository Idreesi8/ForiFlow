import { bandIndexForScore } from "./policyBands.js";

/**
 * Bands shared by the dial, tables and charts.
 *
 * Three different things are kept apart everywhere in the dashboard:
 *   - the model's assessment (score, risk band),
 *   - the policy's recommendation (Approve / Manual Review / Decline),
 *   - the officer's decision (Approved / Rejected, or still pending).
 * The API field `decision` holds the recommendation in its original wording
 * ("Approved" = recommend approve). It is never the final decision.
 */

export const DECISION_APPROVED = "Approved";
export const DECISION_MANUAL_REVIEW = "Manual Review";
export const DECISION_REJECTED = "Rejected";

/**
 * Colours and wording for the three bands, low score to high. The cut-offs are
 * not here: they come from the policy (see lib/policyBands.js).
 */
export const SCORE_BANDS = [
  {
    decision: DECISION_REJECTED,
    recommendation: "Decline",
    riskBand: "High Risk",
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
    recommendation: "Manual Review",
    riskBand: "Medium Risk",
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
    recommendation: "Approve",
    riskBand: "Low Risk",
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

/**
 * The band style for a score under the given policy bands, or the neutral
 * middle style when no bands are known yet.
 */
export function bandForScore(score, bands) {
  const index = bandIndexForScore(score, bands);
  return index === null ? FALLBACK_BAND : SCORE_BANDS[index];
}

/** Resolve the band from a decision string returned by the API. */
export function bandForDecision(decision) {
  return SCORE_BANDS.find((band) => band.decision === decision) ?? FALLBACK_BAND;
}

/** The recommendation wording for a stored `decision` value. */
export function recommendationLabel(decision) {
  return bandForDecision(decision).recommendation;
}

/** The officer's decision: "Approved", "Rejected", or `null` while undecided. */
export function finalDecisionOf(application) {
  if (!application) return null;
  return application.final_decision ?? null;
}

/** Pending, Escalated, Approved, Rejected or Superseded. */
export function decisionStatusOf(application) {
  return application?.decision_status ?? (finalDecisionOf(application) || "Pending");
}

/** Still waiting for an officer (pending, or escalated to an admin). */
export function isPendingReview(application) {
  return ["Pending", "Escalated"].includes(decisionStatusOf(application));
}

// EWS alert statuses, severities and states are styled in lib/ews.js. The
// severity of an alert comes from the API; the dashboard never derives it
// from a score drop.
