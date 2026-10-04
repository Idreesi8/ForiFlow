import { bandForDecision } from "../lib/decisions.js";
import { formatPKR } from "../lib/format.js";

/**
 * What would move a Rejected or Manual Review application into a better band.
 *
 * The API finds each figure by searching the monotone model: a smaller
 * facility or a higher turnover can only score the same or better, so there is
 * exactly one crossing point for each. Renders nothing when there is no path
 * (Approved outcomes, the surrogate engine, explanations stored before 1.5).
 */
export default function PathToApproval({ path, compact = false }) {
  if (!path || path.steps.length === 0) return null;

  return (
    <div className="rounded-lg border border-brand-200 bg-brand-50 px-4 py-3">
      <p className="text-xs font-semibold tracking-wide text-brand-800 uppercase">
        Path to approval
      </p>
      {compact ? null : (
        <p className="mt-1 text-xs text-slate-600">
          Requested {formatPKR(path.requested_loan_pkr)} against a monthly turnover of{" "}
          {formatPKR(path.monthly_turnover_pkr)}. Everything else is kept as submitted.
        </p>
      )}

      <ul className="mt-2 space-y-2">
        {path.steps.map((step) => {
          const band = bandForDecision(step.target_decision);
          const reachable =
            step.max_loan_pkr !== null || step.required_monthly_turnover_pkr !== null;
          return (
            <li key={step.target_decision} className="text-sm text-slate-800">
              <span className={`badge mr-2 ${band.badgeClass}`}>{step.target_decision}</span>
              {reachable ? (
                <span>
                  {step.max_loan_pkr !== null ? (
                    <>
                      at a facility of{" "}
                      <strong className="tabular">{formatPKR(step.max_loan_pkr)}</strong> or
                      less (score {step.score_at_max_loan.toFixed(1)})
                    </>
                  ) : null}
                  {step.max_loan_pkr !== null && step.required_monthly_turnover_pkr !== null
                    ? ", or "
                    : null}
                  {step.required_monthly_turnover_pkr !== null ? (
                    <>
                      with an evidenced monthly turnover of{" "}
                      <strong className="tabular">
                        {formatPKR(step.required_monthly_turnover_pkr)}
                      </strong>{" "}
                      or more (score {step.score_at_turnover.toFixed(1)})
                    </>
                  ) : null}
                  .
                </span>
              ) : (
                <span>not reachable at any facility size or turnover.</span>
              )}
            </li>
          );
        })}
      </ul>

      {path.blocked_by.length > 0 ? (
        <p className="mt-2 text-xs text-slate-700">
          Held back by: {path.blocked_by.join(", ")}.
        </p>
      ) : null}
      {compact ? null : (
        <p className="mt-2 text-xs text-slate-500">
          These are what the model would score, not an offer. A higher turnover has to
          be supported by statements, and the officer still decides.
        </p>
      )}
    </div>
  );
}
