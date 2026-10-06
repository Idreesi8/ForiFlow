import { useState } from "react";

import ApplicationForm from "../components/ApplicationForm.jsx";
import ReviewPanel from "../components/ReviewPanel.jsx";
import ShapWaterfall from "../components/ShapWaterfall.jsx";

/** Intake workspace: score an SME and immediately read the rationale. */
export default function ScoringPage() {
  const [lastScored, setLastScored] = useState(null);

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">Credit Scoring</h2>
        <p className="mt-1 text-sm text-slate-500">
          Score a thin-file SME on alternative data. The decision follows the policy
          matrix: 0-40 Rejected, 41-70 Manual Review, 71-100 Approved. A Manual
          Review case is approved or rejected by a manager or admin, with a written reason.
        </p>
      </header>

      <ApplicationForm onScored={setLastScored} />

      {lastScored?.explanation ? (
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">Why this decision</h2>
            <span className="text-xs text-slate-500">
              Application #{lastScored.application_id}
              {lastScored.borrower_public_id
                ? ` · borrower ${lastScored.borrower_public_id}${
                    lastScored.borrower_created ? " (new)" : ""
                  }`
                : ""}
            </span>
          </div>
          <div className="px-5 py-5">
            <ShapWaterfall explanation={lastScored.explanation} compact />
          </div>
        </section>
      ) : null}

      {lastScored?.decision === "Manual Review" ? (
        <ReviewPanel key={lastScored.application_id} applicationId={lastScored.application_id} />
      ) : null}
    </div>
  );
}
