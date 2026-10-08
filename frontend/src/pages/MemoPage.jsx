import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { apiErrorMessage, explainApplication, fetchApplication } from "../api/client.js";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { finalDecisionOf } from "../lib/decisions.js";
import { formatDateTime, formatPKR, formatPercent, formatSigned } from "../lib/format.js";

/**
 * A printable credit memo for one application: what was asked, what the model
 * said and why, where the turnover came from, and who decided. Everything on
 * it is read from the stored record; nothing is recomputed for the print.
 */
export default function MemoPage() {
  const { applicationId } = useParams();
  const [application, setApplication] = useState(null);
  const [explanation, setExplanation] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [applicationData, explanationData] = await Promise.all([
        fetchApplication(applicationId),
        explainApplication(applicationId),
      ]);
      setApplication(applicationData);
      setExplanation(explanationData);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the credit memo."));
    } finally {
      setIsLoading(false);
    }
  }, [applicationId]);

  useEffect(() => {
    load();
  }, [load]);

  if (isLoading) return <LoadingState label="Loading credit memo…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const final = finalDecisionOf(application);
  const evidence = application.turnover_evidence;
  const path = explanation.approval_path;

  return (
    <div className="mx-auto max-w-3xl min-w-0 space-y-4">
      <div className="flex items-center justify-between gap-3 print:hidden">
        <Link to={`/shap/${application.id}`} className="text-sm font-semibold text-brand-700 hover:underline">
          ← Back to the SHAP report
        </Link>
        <button type="button" className="btn-primary px-4 py-2 text-sm" onClick={() => window.print()}>
          Print or save as PDF
        </button>
      </div>

      <article className="card min-w-0 space-y-6 px-5 py-6 text-sm sm:px-8 sm:py-8 text-slate-800 print:border-0 print:shadow-none">
        <header className="border-b border-slate-200 pb-4">
          <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            ForiFlow credit memo · Application #{application.id}
          </p>
          <h2 className="mt-1 text-2xl font-bold text-slate-900">{application.business_name}</h2>
          <p className="text-slate-600">
            {application.applicant_name}
            {application.business_sector ? ` · ${application.business_sector}` : ""}
          </p>
        </header>

        <Section title="Request">
          <Row label="Facility">{formatPKR(application.loan_amount_pkr)}</Row>
          <Row label="Tenure">{application.tenure_months} months</Row>
          <Row label="Straight-line installment">
            {formatPKR(application.loan_amount_pkr / application.tenure_months)}
          </Row>
          <Row label="Assessed">
            {formatDateTime(application.created_at)} by {application.scored_by ?? "—"}
          </Row>
        </Section>

        <Section title="Model assessment">
          <Row label="Score">{application.risk_score.toFixed(2)} out of 100</Row>
          <Row label="Risk band">{application.risk_band ?? "—"}</Row>
          {explanation.probability_of_default !== null &&
          explanation.probability_of_default !== undefined ? (
            <Row label="Calibrated PD (display only)">
              {formatPercent(explanation.probability_of_default)} (calibrated on the public
              training file)
            </Row>
          ) : null}
          <Row label="Model">{explanation.model_version ?? "—"}</Row>
        </Section>

        <Section title="Policy recommendation">
          <Row label="Recommendation">
            {application.recommendation} (a recommendation, not a decision)
          </Row>
          <Row label="Policy">
            {application.policy?.policy_version
              ? `${application.policy.policy_name} v${application.policy.policy_version}`
              : "Not recorded (scored before policy versions were stored)"}
          </Row>
          {application.reason_codes?.length ? (
            <Row label="Top risk factors">
              {application.reason_codes.map((code) => `${code.code} ${code.label}`).join("; ")}
            </Row>
          ) : null}
        </Section>

        <Section title="Why this score">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                <th className="py-2 font-medium">Factor</th>
                <th className="py-2 text-right font-medium">Value</th>
                <th className="py-2 text-right font-medium">Points</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              <tr>
                <td className="py-2 text-slate-600">Model reference baseline (not a portfolio average)</td>
                <td />
                <td className="tabular py-2 text-right">{explanation.base_value.toFixed(2)}</td>
              </tr>
              {explanation.feature_contributions.map((item) => (
                <tr key={item.feature}>
                  <td className="py-2">{item.label}</td>
                  <td className="tabular py-2 text-right text-slate-600">
                    {item.feature === "loan_to_income"
                      ? formatPercent(item.value)
                      : Number(item.value).toLocaleString("en-PK", { maximumFractionDigits: 2 })}
                  </td>
                  <td className="tabular py-2 text-right font-semibold">
                    {formatSigned(item.contribution)}
                  </td>
                </tr>
              ))}
              <tr className="border-t-2 border-slate-300">
                <td className="py-2 font-semibold">Score</td>
                <td />
                <td className="tabular py-2 text-right font-bold">
                  {explanation.risk_score.toFixed(2)}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-slate-700">{explanation.narrative}</p>
        </Section>

        {path ? (
          <Section title="Path to approval">
            {path.steps.map((step) => (
              <Row key={step.target_decision} label={step.target_decision}>
                {step.max_loan_pkr !== null
                  ? `facility of ${formatPKR(step.max_loan_pkr)} or less`
                  : null}
                {step.max_loan_pkr !== null && step.required_monthly_turnover_pkr !== null
                  ? ", or "
                  : null}
                {step.required_monthly_turnover_pkr !== null
                  ? `evidenced monthly turnover of ${formatPKR(
                      step.required_monthly_turnover_pkr,
                    )} or more`
                  : null}
                {step.max_loan_pkr === null && step.required_monthly_turnover_pkr === null
                  ? "not reachable at any facility size or turnover"
                  : null}
              </Row>
            ))}
            <p className="mt-1 text-xs text-slate-500">Model outputs, not an offer.</p>
          </Section>
        ) : null}

        <Section title="Turnover evidence">
          {evidence ? (
            <>
              <Row label="Source">
                Statement, {evidence.full_months} full months, {evidence.period_start} to{" "}
                {evidence.period_end}, {evidence.transactions.toLocaleString("en-PK")}{" "}
                transactions
              </Row>
              <Row label="Median money in per month">
                {formatPKR(evidence.monthly_inflow_median)}
              </Row>
              <Row label="Median net per month">{formatPKR(evidence.monthly_net_median)}</Row>
              <Row label="Scored figures match it">
                {evidence.matches_statement ? "Yes" : "No: the figures were changed after upload"}
              </Row>
              {evidence.warnings.map((warning) => (
                <p key={warning} className="mt-1 text-xs text-slate-600">
                  Check: {warning}
                </p>
              ))}
            </>
          ) : (
            <p>Turnover was typed by the officer. No statement was attached.</p>
          )}
        </Section>

        <Section title="Credit officer decision">
          <Row label="Status">{final ?? application.decision_status}</Row>
          {application.review_decision ? (
            <>
              <Row label="Decided by">
                {application.reviewed_by} on {formatDateTime(application.reviewed_at)}
              </Row>
              <Row label="Reason">{application.review_note}</Row>
            </>
          ) : final ? (
            <p className="text-slate-600">
              Recorded before release 2.0, when the score band alone decided. No officer
              decision is on file.
            </p>
          ) : (
            <p className="text-slate-600">Awaiting a manager or admin decision.</p>
          )}
          {application.escalated_by ? (
            <Row label="Escalated by">
              {application.escalated_by} on {formatDateTime(application.escalated_at)}
            </Row>
          ) : null}
        </Section>

        <footer className="border-t border-slate-200 pt-4 text-xs text-slate-500">
          {explanation.compliance_note}
        </footer>
      </article>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section className="break-inside-avoid">
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</h3>
      <div className="space-y-1">{children}</div>
    </section>
  );
}

function Row({ label, children }) {
  return (
    <div className="flex flex-col sm:flex-row sm:gap-4">
      <span className="shrink-0 text-slate-500 sm:w-52">{label}</span>
      <span className="min-w-0 font-medium break-words text-slate-900">{children}</span>
    </div>
  );
}
