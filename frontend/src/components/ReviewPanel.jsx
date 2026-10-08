import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { canDecideCredit, getStoredRole } from "../api/auth.js";
import { apiErrorMessage, decideApplication, fetchApplication } from "../api/client.js";
import { bandForDecision, finalDecisionOf } from "../lib/decisions.js";
import { formatDateTime, formatPercent, formatPKR } from "../lib/format.js";
import { FinalDecisionBadge, RecommendationBadge } from "./common/Badges.jsx";
import { ErrorState, LoadingState, Spinner } from "./common/States.jsx";

const NOTE_MIN = 10;
const NOTE_MAX = 1000;

const AUTHORITY_TEXT = {
  above_manager_limit: (application) =>
    `This facility of ${formatPKR(application.loan_amount_pkr)} is above the manager approval limit of ${formatPKR(
      application.manager_approval_limit_pkr,
    )}. An admin must approve it. You can still reject or escalate it.`,
  approval_against_decline_recommendation: () =>
    "The policy recommends Decline. Approving against that recommendation needs an admin. You can still reject or escalate it.",
};

/**
 * One application in three separate parts: what the model assessed, what the
 * credit policy recommends, and what an officer decided. Only the third part
 * is a decision, and it is recorded here by a manager or admin
 * (`POST /score/applications/{id}/decision`). The API enforces who may do what;
 * this panel only mirrors it.
 */
export default function ReviewPanel({ applicationId, onDecided }) {
  const [application, setApplication] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const canDecide = canDecideCredit();
  const isAdmin = getStoredRole() === "admin";

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setApplication(await fetchApplication(applicationId));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the application."));
    } finally {
      setIsLoading(false);
    }
  }, [applicationId]);

  useEffect(() => {
    setNote("");
    setSubmitError(null);
    load();
  }, [load]);

  const decide = async (decision) => {
    setSubmitting(decision);
    setSubmitError(null);
    try {
      const updated = await decideApplication(applicationId, { decision, note: note.trim() });
      setApplication(updated);
      setNote("");
      onDecided?.(updated);
    } catch (requestError) {
      setSubmitError(apiErrorMessage(requestError, "The decision was not saved."));
      // 409: someone else acted first. Reload so the record on file shows.
      if (requestError?.response?.status === 409) {
        await load();
      }
    } finally {
      setSubmitting(null);
    }
  };

  const noteLength = note.trim().length;
  const noteReady = noteLength >= NOTE_MIN && noteLength <= NOTE_MAX;

  if (isLoading) {
    return (
      <section className="card">
        <LoadingState label="Loading decision…" />
      </section>
    );
  }
  if (error) {
    return (
      <section className="card">
        <ErrorState message={error} onRetry={load} />
      </section>
    );
  }

  const status = application.decision_status;
  const final = finalDecisionOf(application);
  const band = bandForDecision(application.decision);
  const authority = application.policy?.authority;
  const escalated = status === "Escalated";
  const open = status === "Pending" || escalated;
  const needsAdmin = application.approval_authority === "admin" && !isAdmin;
  const withAdmin = escalated && !isAdmin;
  const pd = application.assessment?.probability_of_default;

  return (
    <section className="card" aria-labelledby="review-panel-title">
      <div className="card-header">
        <h3 id="review-panel-title" className="card-title">
          Assessment, recommendation and decision
        </h3>
        <Link
          to={`/memo/${application.id}`}
          className="text-xs font-semibold text-brand-700 hover:underline"
        >
          Credit memo
        </Link>
      </div>

      <div className="grid gap-px bg-slate-200 text-sm lg:grid-cols-3">
        {/* 1. The model: an assessment, nothing more. */}
        <div className="space-y-3 bg-white px-5 py-5">
          <StepTitle step="1" title="Risk assessment" source="From the model" />
          <dl className="space-y-2">
            <Fact label="Risk score">
              <span className={`tabular text-lg font-bold ${band.textClass}`}>
                {application.risk_score.toFixed(2)}
              </span>
              <span className="ml-1 text-slate-500">/ 100</span>
            </Fact>
            <Fact label="Risk band">{application.risk_band ?? band.riskBand}</Fact>
            <Fact label="Calibrated PD (display only)">
              {pd !== null && pd !== undefined ? formatPercent(pd) : "Not available"}
            </Fact>
            <Fact label="Model version">
              <span className="break-all text-xs">
                {application.model_version ?? "not recorded"}
              </span>
            </Fact>
          </dl>
          {application.scoring_engine === "surrogate" ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Scored by the fallback formula, not the trained model.
            </p>
          ) : null}
        </div>

        {/* 2. The policy: a recommendation, never a decision. */}
        <div className="space-y-3 bg-white px-5 py-5">
          <StepTitle step="2" title="ForiFlow recommendation" source="From the credit policy" />
          <RecommendationBadge decision={application.decision} prefix />
          <dl className="space-y-2">
            <Fact label="Policy">
              {application.policy?.policy_version
                ? `${application.policy.policy_name} v${application.policy.policy_version}`
                : "Not recorded"}
            </Fact>
            <Fact label="Approval needs">
              {application.approval_authority === "admin" ? "An admin" : "A manager or admin"}
            </Fact>
          </dl>
          {application.reason_codes?.length ? (
            <div>
              <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">
                Top risk factors
              </p>
              <ul className="mt-1 space-y-1">
                {application.reason_codes.map((code) => (
                  <li key={code.code + code.feature} className="text-slate-800">
                    <span className="tabular font-semibold">{code.code}</span> — {code.label}{" "}
                    <span className="tabular text-xs text-rose-700">
                      ({code.points.toFixed(1)} points)
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              No risk factor took more than half a point off this score.
            </p>
          )}
          <p className="text-xs text-slate-500">
            A recommendation only. The policy is configurable and its cut-offs are demo
            values.
          </p>
        </div>

        {/* 3. The human: the only decision. */}
        <div className="space-y-3 bg-white px-5 py-5">
          <StepTitle step="3" title="Credit officer decision" source="Made by a person" />
          <FinalDecisionBadge application={application} />
          <dl className="space-y-2">
            <Fact label="Scored by">{application.scored_by ?? "—"}</Fact>
            <Fact label="Borrower">{application.borrower_public_id ?? "—"}</Fact>
            {application.escalated_by ? (
              <Fact label="Escalated by">
                {application.escalated_by} · {formatDateTime(application.escalated_at)}
              </Fact>
            ) : null}
          </dl>
          {final !== null && application.reviewed_by ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="font-semibold text-slate-900">
                {final} by {application.reviewed_by}
              </p>
              <p className="text-xs text-slate-500">{formatDateTime(application.reviewed_at)}</p>
              <p className="mt-1 whitespace-pre-line text-slate-700">{application.review_note}</p>
              {application.officer_decision?.overrides_recommendation ? (
                <p className="mt-1 text-xs font-medium text-amber-800">
                  Decided against the recommendation.
                </p>
              ) : null}
            </div>
          ) : final !== null ? (
            <p className="text-xs text-slate-600">
              Recorded before release 2.0, when the score band alone decided. No officer
              decision is on file.
            </p>
          ) : status === "Superseded" ? (
            <p className="text-xs text-slate-600">
              Re-scored as application{" "}
              <Link
                className="font-semibold text-brand-700 hover:underline"
                to={`/shap/${application.superseded_by_application_id}`}
              >
                #{application.superseded_by_application_id}
              </Link>
              . This assessment is kept for the record.
            </p>
          ) : null}
        </div>
      </div>

      <div className="space-y-3 border-t border-slate-200 px-5 py-5 text-sm">
        <TurnoverEvidence evidence={application.turnover_evidence} />

        {!open ? null : !canDecide ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
            Awaiting an officer decision. Approving, rejecting or escalating needs the
            manager or admin role.
          </p>
        ) : withAdmin ? (
          <p className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-violet-900">
            Escalated by {application.escalated_by}. It is now with an admin.
          </p>
        ) : (
          <>
            <p className="text-slate-600">
              Read the assessment and the SHAP factors, then record your decision. It is
              saved with your name and the time, and it cannot be changed afterwards.
            </p>
            <div>
              <label className="field-label" htmlFor={`review-note-${applicationId}`}>
                Reason for the credit file
              </label>
              <textarea
                id={`review-note-${applicationId}`}
                rows={3}
                maxLength={NOTE_MAX}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="e.g. Five years of clean POS receipts; facility is 28% of turnover."
                className="field-input"
              />
              <p className="mt-1 text-xs text-slate-500">
                {noteLength < NOTE_MIN
                  ? `At least ${NOTE_MIN} characters (${noteLength} so far).`
                  : `${noteLength} / ${NOTE_MAX} characters.`}
              </p>
            </div>

            {needsAdmin && AUTHORITY_TEXT[authority?.reason] ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                {AUTHORITY_TEXT[authority.reason](application)}
              </p>
            ) : null}

            {submitError ? (
              <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800" role="alert">
                {submitError}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={!noteReady || submitting !== null || needsAdmin}
                onClick={() => decide("Approved")}
                className="btn bg-emerald-600 text-white hover:bg-emerald-700"
              >
                {submitting === "Approved" ? <Spinner className="h-4 w-4 text-white" /> : null}
                Approve
              </button>
              <button
                type="button"
                disabled={!noteReady || submitting !== null}
                onClick={() => decide("Rejected")}
                className="btn bg-rose-600 text-white hover:bg-rose-700"
              >
                {submitting === "Rejected" ? <Spinner className="h-4 w-4 text-white" /> : null}
                Reject
              </button>
              {isAdmin ? null : (
                <button
                  type="button"
                  disabled={!noteReady || submitting !== null}
                  onClick={() => decide("Escalated")}
                  className="btn border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
                >
                  {submitting === "Escalated" ? <Spinner className="h-4 w-4" /> : null}
                  Escalate to admin
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function StepTitle({ step, title, source }) {
  return (
    <div>
      <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-slate-900 uppercase">
        <span className="tabular flex h-5 w-5 items-center justify-center rounded-full bg-slate-900 text-[11px] text-white">
          {step}
        </span>
        {title}
      </p>
      <p className="mt-0.5 pl-7 text-[11px] text-slate-500">{source}</p>
    </div>
  );
}

/** Where the turnover behind the score came from: a statement, or typing. */
function TurnoverEvidence({ evidence }) {
  if (!evidence) {
    return (
      <p className="text-xs text-slate-500">
        Turnover: typed by the officer. No statement was attached.
      </p>
    );
  }
  return (
    <p
      className={`rounded-lg border px-3 py-2 text-xs ${
        evidence.matches_statement
          ? "border-brand-200 bg-brand-50 text-slate-700"
          : "border-amber-200 bg-amber-50 text-amber-900"
      }`}
    >
      {evidence.matches_statement
        ? "Turnover taken from a statement: "
        : "A statement was attached, but the turnover figures were changed afterwards: "}
      {evidence.full_months} full months, {evidence.transactions.toLocaleString("en-PK")}{" "}
      transactions, {evidence.period_start} to {evidence.period_end}.
    </p>
  );
}

function Fact({ label, children }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-xs text-slate-500">{label}</dt>
      <dd className="min-w-0 text-right text-slate-900">{children}</dd>
    </div>
  );
}
