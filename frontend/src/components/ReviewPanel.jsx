import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { canDecideCredit, getStoredRole } from "../api/auth.js";
import { apiErrorMessage, fetchApplication, reviewApplication } from "../api/client.js";
import { DECISION_MANUAL_REVIEW, finalDecisionOf } from "../lib/decisions.js";
import { formatDateTime, formatPKR } from "../lib/format.js";
import { DecisionBadge, FinalDecisionBadge } from "./common/Badges.jsx";
import { ErrorState, LoadingState, Spinner } from "./common/States.jsx";

const NOTE_MIN = 10;
const NOTE_MAX = 1000;

/**
 * The decision on file for one application, and, for a Manual Review case,
 * where an admin records the final Approve / Reject with a reason
 * (`POST /score/applications/{id}/review`). The model's band is kept beside it.
 */
export default function ReviewPanel({ applicationId, onDecided }) {
  const [application, setApplication] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  // The API enforces this (403 for analysts); the role only decides what to show.
  const canDecide = canDecideCredit();

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
      const updated = await reviewApplication(applicationId, { decision, note: note.trim() });
      setApplication(updated);
      onDecided?.(updated);
    } catch (requestError) {
      setSubmitError(apiErrorMessage(requestError, "The decision was not saved."));
      // 409: someone else decided first. Reload so the recorded decision shows.
      if (requestError?.response?.status === 409) {
        await load();
      }
    } finally {
      setSubmitting(null);
    }
  };

  const noteLength = note.trim().length;
  const noteReady = noteLength >= NOTE_MIN && noteLength <= NOTE_MAX;
  // Above the manager limit only an admin may approve. The API enforces it (403).
  const needsAdmin =
    application?.approval_authority === "admin" && getStoredRole() !== "admin";

  return (
    <section className="card" aria-labelledby="review-panel-title">
      <div className="card-header">
        <h3 id="review-panel-title" className="card-title">
          Decision on file
        </h3>
        <span className="flex items-center gap-3">
          {application ? (
            <Link
              to={`/memo/${application.id}`}
              className="text-xs font-semibold text-brand-700 hover:underline"
            >
              Credit memo
            </Link>
          ) : null}
          {application ? <FinalDecisionBadge application={application} /> : null}
        </span>
      </div>

      {isLoading ? (
        <LoadingState label="Loading decision…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : (
        <div className="space-y-4 px-5 py-5 text-sm">
          <dl className="grid gap-3 sm:grid-cols-3">
            <Fact label="Model decision">
              <DecisionBadge decision={application.decision} />
              <span className="tabular ml-2 text-slate-500">
                score {application.risk_score.toFixed(2)}
              </span>
            </Fact>
            <Fact label="Scored by">{application.scored_by ?? "—"}</Fact>
            <Fact label="Assessed">{formatDateTime(application.created_at)}</Fact>
          </dl>
          <TurnoverEvidence evidence={application.turnover_evidence} />

          {application.decision !== DECISION_MANUAL_REVIEW ? (
            <p className="text-slate-600">
              The model's decision is final. Only Manual Review cases (41–70) need an
              officer decision.
            </p>
          ) : finalDecisionOf(application) !== null ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
              <p className="font-semibold text-slate-900">
                {application.review_decision} by {application.reviewed_by} ·{" "}
                <span className="font-normal text-slate-500">
                  {formatDateTime(application.reviewed_at)}
                </span>
              </p>
              <p className="mt-1 whitespace-pre-line text-slate-700">{application.review_note}</p>
            </div>
          ) : !canDecide ? (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
              Awaiting an officer decision. Approving or rejecting a Manual Review case
              needs the manager or admin role.
            </p>
          ) : (
            <div className="space-y-3">
              <p className="text-slate-600">
                The model placed this case in Manual Review. Read the SHAP factors, then
                record your decision. It is saved with your name and the time, and it
                cannot be changed afterwards.
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

              {needsAdmin ? (
                <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                  This facility of {formatPKR(application.loan_amount_pkr)} is above the manager
                  approval limit of {formatPKR(application.manager_approval_limit_pkr)}. An
                  admin must approve it. You can still reject it.
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
              </div>
            </div>
          )}
        </div>
      )}
    </section>
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
    <div>
      <dt className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 flex items-center text-slate-900">{children}</dd>
    </div>
  );
}
