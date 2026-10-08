import { useEffect, useState } from "react";

import { canDecideCredit } from "../api/auth.js";
import {
  apiErrorMessage,
  correctObservation,
  fetchApplications,
  fetchFacilityObservations,
  recordObservation,
} from "../api/client.js";
import { DECISION_APPROVED, finalDecisionOf } from "../lib/decisions.js";
import {
  formatDeterioration,
  scoreSourceLabel,
  trendMessage,
  trendStyle,
} from "../lib/ews.js";
import { formatPKR } from "../lib/format.js";
import { EwsStateBadge } from "./common/Badges.jsx";
import { Spinner } from "./common/States.jsx";

const INSTALLMENT_STATUSES = ["On Time", "Late 1-29", "Late 30-59", "Late 60-89", "Default"];
const DATA_SOURCES = ["ECIB", "POS", "Bank Statement", "Self Reported"];
const REASON_MIN = 10;

const today = () => new Date().toISOString().slice(0, 10);

const initialForm = () => ({
  borrower_id: "",
  month_number: "1",
  observation_date: today(),
  installment_status: "On Time",
  days_late: "",
  bureau_balance: "",
  pos_cash_balance: "",
  amount_paid_pkr: "",
  data_source_primary: "ECIB",
  override: false,
  current_score: "",
  override_reason: "",
});

/**
 * Record one month for an approved facility (`POST /ews/observations`).
 *
 * The backend derives the monitored score, assesses the facility's whole
 * history and opens or updates its alert. A month already on file is refused
 * (409); a manager can then record the figures as a correction, which keeps
 * the original. A score override needs a manager and a written reason and is
 * always shown as an officer override.
 */
export default function MonitoringPanel({ onMonitored, facilityId = null }) {
  const [borrowers, setBorrowers] = useState([]);
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [correctionReason, setCorrectionReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const canManage = canDecideCredit();

  useEffect(() => {
    let cancelled = false;
    fetchApplications({ final_decision: DECISION_APPROVED, limit: 200 })
      .then((data) => {
        if (cancelled) return;
        // Only an approved application became a facility; the API answers 409 otherwise.
        const monitorable = data.filter(
          (application) => finalDecisionOf(application) === DECISION_APPROVED,
        );
        setBorrowers(monitorable);
        setForm((previous) =>
          previous.borrower_id || monitorable.length === 0
            ? previous
            : { ...previous, borrower_id: String(monitorable[0].id) },
        );
      })
      .catch(() => setBorrowers([]));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (facilityId) setForm((previous) => ({ ...previous, borrower_id: String(facilityId) }));
  }, [facilityId]);

  const selectedBorrower =
    borrowers.find((borrower) => String(borrower.id) === String(form.borrower_id)) ?? null;

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setForm((previous) => ({ ...previous, [name]: type === "checkbox" ? checked : value }));
    setConflict(null);
  };

  /** The month's figures, as both the record and the correction routes take them. */
  const figures = () => ({
    installment_status: form.installment_status,
    bureau_balance: Number(form.bureau_balance),
    pos_cash_balance: Number(form.pos_cash_balance),
    data_source_primary: form.data_source_primary,
    ...(form.observation_date ? { observation_date: form.observation_date } : {}),
    ...(form.days_late === "" ? {} : { days_late: Number(form.days_late) }),
    // Optional: a month without it is left out of the collection figures.
    ...(form.amount_paid_pkr === "" ? {} : { amount_paid_pkr: Number(form.amount_paid_pkr) }),
    ...(form.override && canManage
      ? { current_score: Number(form.current_score), override_reason: form.override_reason.trim() }
      : {}),
  });

  const finish = (response) => {
    setResult(response);
    setConflict(null);
    setCorrectionReason("");
    onMonitored?.(response);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setConflict(null);
    try {
      finish(
        await recordObservation({
          borrower_id: Number(form.borrower_id),
          month_number: Number(form.month_number),
          ...figures(),
        }),
      );
    } catch (requestError) {
      setResult(null);
      setError(apiErrorMessage(requestError, "The month could not be recorded."));
      if (requestError?.response?.status === 409) {
        // Find the recorded row this month collides with, to offer a correction.
        try {
          const rows = await fetchFacilityObservations(Number(form.borrower_id), {
            include_superseded: false,
          });
          const row = rows.find((item) => item.month_number === Number(form.month_number));
          if (row) setConflict(row);
        } catch {
          /* the error above already explains the refusal */
        }
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCorrection = async () => {
    if (!conflict) return;
    setIsSubmitting(true);
    setError(null);
    try {
      finish(
        await correctObservation(conflict.id, {
          ...figures(),
          correction_reason: correctionReason.trim(),
        }),
      );
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "The correction was not saved."));
    } finally {
      setIsSubmitting(false);
    }
  };

  const overrideIncomplete =
    form.override &&
    (form.current_score === "" || form.override_reason.trim().length < REASON_MIN);

  return (
    <section className="card" data-testid="monitoring-panel">
      <div className="card-header">
        <div>
          <h2 className="card-title">Record a monitoring month</h2>
          <p className="mt-1 text-sm text-slate-500">
            Officer-typed figures. ForiFlow has no live ECIB or bureau feed. A recorded month is
            never overwritten.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4 px-5 py-5 md:grid-cols-3">
        <div className="md:col-span-1">
          <label className="field-label" htmlFor="borrower_id">
            Facility
          </label>
          <select
            id="borrower_id"
            name="borrower_id"
            value={form.borrower_id}
            onChange={handleChange}
            required
            className="field-input"
          >
            <option value="" disabled>
              Select an approved facility
            </option>
            {borrowers.map((borrower) => (
              <option key={borrower.id} value={borrower.id}>
                #{borrower.id} · {borrower.business_name} ·{" "}
                {borrower.reviewed_by ? `Approved by ${borrower.reviewed_by}` : "Approved before 2.0"}
              </option>
            ))}
          </select>
          {borrowers.length === 0 ? (
            <p className="mt-1 text-xs text-slate-500">
              No approved facility yet. An application becomes a facility when a manager or admin
              approves it.
            </p>
          ) : null}
        </div>

        <div>
          <label className="field-label" htmlFor="month_number">
            Reporting month (since disbursement)
          </label>
          <input
            id="month_number"
            name="month_number"
            type="number"
            min="1"
            max="84"
            step="1"
            value={form.month_number}
            onChange={handleChange}
            required
            className="field-input"
          />
        </div>

        <div>
          <label className="field-label" htmlFor="observation_date">
            Observation date
          </label>
          <input
            id="observation_date"
            name="observation_date"
            type="date"
            max={today()}
            value={form.observation_date}
            onChange={handleChange}
            className="field-input"
          />
        </div>

        <div>
          <label className="field-label" htmlFor="installment_status">
            Installment status
          </label>
          <select
            id="installment_status"
            name="installment_status"
            value={form.installment_status}
            onChange={handleChange}
            className="field-input"
          >
            {INSTALLMENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="field-label" htmlFor="days_late">
            Days late <span className="text-xs text-slate-400">(optional)</span>
          </label>
          <input
            id="days_late"
            name="days_late"
            type="number"
            min="0"
            step="1"
            value={form.days_late}
            onChange={handleChange}
            className="field-input"
          />
          <p className="mt-1 text-xs text-slate-500">Must fit the status bucket.</p>
        </div>

        <div>
          <label className="field-label" htmlFor="bureau_balance">
            Bureau balance <span className="text-xs text-slate-400">(PKR)</span>
          </label>
          <input
            id="bureau_balance"
            name="bureau_balance"
            type="number"
            min="0"
            step="any"
            value={form.bureau_balance}
            onChange={handleChange}
            required
            className="field-input"
          />
          {form.bureau_balance ? (
            <p className="tabular mt-1 text-xs text-slate-500">{formatPKR(form.bureau_balance)}</p>
          ) : null}
        </div>

        <div>
          <label className="field-label" htmlFor="pos_cash_balance">
            POS cash inflow <span className="text-xs text-slate-400">(PKR)</span>
          </label>
          <input
            id="pos_cash_balance"
            name="pos_cash_balance"
            type="number"
            min="0"
            step="any"
            value={form.pos_cash_balance}
            onChange={handleChange}
            required
            className="field-input"
          />
          {form.pos_cash_balance ? (
            <p className="tabular mt-1 text-xs text-slate-500">{formatPKR(form.pos_cash_balance)}</p>
          ) : null}
        </div>

        <div>
          <label className="field-label" htmlFor="amount_paid_pkr">
            Amount paid <span className="text-xs text-slate-400">(PKR, optional)</span>
          </label>
          <input
            id="amount_paid_pkr"
            name="amount_paid_pkr"
            type="number"
            min="0"
            step="any"
            value={form.amount_paid_pkr}
            onChange={handleChange}
            className="field-input"
          />
          <p className="tabular mt-1 text-xs text-slate-500">
            {form.amount_paid_pkr
              ? formatPKR(form.amount_paid_pkr)
              : selectedBorrower
                ? `Installment due: ${formatPKR(
                    selectedBorrower.loan_amount_pkr / selectedBorrower.tenure_months,
                  )}`
                : "Feeds the collection figures."}
          </p>
        </div>

        <div>
          <label className="field-label" htmlFor="data_source_primary">
            Primary data source
          </label>
          <select
            id="data_source_primary"
            name="data_source_primary"
            value={form.data_source_primary}
            onChange={handleChange}
            className="field-input"
          >
            {DATA_SOURCES.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">“ECIB” means figures keyed from an extract.</p>
        </div>

        {canManage ? (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 md:col-span-3">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input
                type="checkbox"
                name="override"
                checked={form.override}
                onChange={handleChange}
              />
              Override the monitored score (manager or admin)
            </label>
            {form.override ? (
              <div className="mt-3 grid gap-3 md:grid-cols-3">
                <div>
                  <label className="field-label" htmlFor="current_score">
                    Score (0–100)
                  </label>
                  <input
                    id="current_score"
                    name="current_score"
                    type="number"
                    min="0"
                    max="100"
                    step="any"
                    value={form.current_score}
                    onChange={handleChange}
                    className="field-input"
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="field-label" htmlFor="override_reason">
                    Reason (at least {REASON_MIN} characters)
                  </label>
                  <input
                    id="override_reason"
                    name="override_reason"
                    type="text"
                    maxLength={1000}
                    value={form.override_reason}
                    onChange={handleChange}
                    className="field-input"
                  />
                </div>
                <p className="text-xs text-slate-500 md:col-span-3">
                  Stored and shown as “Officer Override” with your name and reason, next to the
                  score the rules gave. It is never presented as a model score.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 md:col-span-3">
          {error ? (
            <p role="alert" className="text-sm font-medium text-rose-700">
              {error}
            </p>
          ) : (
            <p className="text-xs text-slate-500">
              The EWS assesses the facility's recorded history and opens or updates its alert.
              The thresholds are listed under Methodology on this page.
            </p>
          )}
          <button type="submit" className="btn-primary" disabled={isSubmitting || overrideIncomplete}>
            {isSubmitting ? (
              <>
                <Spinner className="h-4 w-4 text-white" />
                Saving…
              </>
            ) : (
              "Record month"
            )}
          </button>
        </div>
      </form>

      {conflict ? (
        <div className="border-t border-amber-200 bg-amber-50 px-5 py-4 text-sm" data-testid="correction-offer">
          <p className="font-semibold text-amber-900">
            Month {conflict.month_number} is already recorded (observation #{conflict.id}, score{" "}
            {conflict.monthly_score.toFixed(1)}, {conflict.installment_status}).
          </p>
          {canManage ? (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <label className="min-w-72 flex-1 text-xs text-slate-700">
                Correction reason (at least {REASON_MIN} characters). The original stays on file,
                marked superseded.
                <input
                  type="text"
                  name="correction_reason"
                  value={correctionReason}
                  onChange={(event) => setCorrectionReason(event.target.value)}
                  maxLength={1000}
                  className="field-input mt-1 py-1.5"
                />
              </label>
              <button
                type="button"
                onClick={handleCorrection}
                disabled={isSubmitting || correctionReason.trim().length < REASON_MIN || overrideIncomplete}
                className="btn-primary py-1.5 text-xs"
              >
                Save as a correction of month {conflict.month_number}
              </button>
            </div>
          ) : (
            <p className="mt-1 text-amber-900">Ask a manager to correct it; analysts cannot change history.</p>
          )}
        </div>
      ) : null}

      {result ? <MonitoringResult result={result} /> : null}
    </section>
  );
}

function MonitoringResult({ result }) {
  const trend = result.trend;
  const message = trendMessage(trend);
  const direction = trendStyle(trend?.direction);
  return (
    <div
      className={`border-t px-5 py-4 ${
        result.alert_triggered ? "border-rose-200 bg-rose-50" : "border-emerald-200 bg-emerald-50"
      }`}
      data-testid="monitoring-result"
    >
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
        <span>
          <span className="block text-[11px] font-medium tracking-wide text-slate-500 uppercase">
            EWS state
          </span>
          <EwsStateBadge state={result.ews_state} />
        </span>
        <Metric label="Baseline" value={result.baseline_score.toFixed(1)} />
        <Metric label={`Month ${result.month_number}`} value={result.current_score.toFixed(1)} />
        <Metric label="Change vs baseline" value={formatDeterioration(result.score_drop)} />
        <span>
          <span className="block text-[11px] font-medium tracking-wide text-slate-500 uppercase">
            Trend
          </span>
          <span className={direction.className}>
            {direction.symbol} {direction.label}
          </span>
        </span>
        <span className={`badge ${result.alert_triggered ? "bg-rose-600 text-white" : "bg-emerald-600 text-white"}`}>
          {result.alert_triggered
            ? `Alert #${result.alert?.id ?? ""} ${result.alert?.severity ?? ""}`.trim()
            : "No alert"}
        </span>
      </div>
      <p className="mt-2 text-xs text-slate-600">
        Score Source: <span className="font-semibold">{scoreSourceLabel(result.score_source)}</span>
        {result.tracking?.override_reason ? ` — “${result.tracking.override_reason}”` : ""}
        {result.tracking?.supersedes_observation_id
          ? ` · corrects observation #${result.tracking.supersedes_observation_id}`
          : ""}
      </p>
      {message ? <p className="mt-1 text-xs text-slate-500">{message}.</p> : null}

      {result.signals?.length ? (
        <ul className="mt-3 space-y-1 text-sm text-slate-800">
          {result.signals.map((signal) => (
            <li key={signal.code}>
              <span className="font-mono text-[11px] text-slate-500">{signal.code}</span>{" "}
              {signal.evidence}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-slate-700">No warning signal this month.</p>
      )}

      <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
        {result.recommended_actions.map((action) => (
          <li key={action}>{action}</li>
        ))}
      </ul>

      {result.default_probability_3m !== null && result.default_probability_3m !== undefined ? (
        <p className="mt-2 text-xs text-slate-500">
          Reference only, not used for alerts: a Markov chain fitted on consumer card repayment
          histories (UCI, Taiwan 2005), not SME loans, gives{" "}
          {(result.default_probability_3m * 100).toFixed(1)}% default within 3 months for this
          repayment bucket.
        </p>
      ) : null}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <span>
      <span className="block text-[11px] font-medium tracking-wide text-slate-500 uppercase">
        {label}
      </span>
      <span className="tabular text-lg font-bold text-slate-900">{value}</span>
    </span>
  );
}
