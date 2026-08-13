import { useEffect, useState } from "react";

import { apiErrorMessage, fetchApplications, monitorBorrower } from "../api/client.js";
import { formatPKR } from "../lib/format.js";
import { Spinner } from "./common/States.jsx";

const INSTALLMENT_STATUSES = [
  "On Time",
  "Late 1-29",
  "Late 30-59",
  "Late 60-89",
  "Default",
];

const DATA_SOURCES = ["ECIB", "POS", "Bank Statement", "Self Reported"];

const INITIAL_FORM = {
  borrower_id: "",
  month_number: "1",
  installment_status: "On Time",
  bureau_balance: "",
  pos_cash_balance: "",
  data_source_primary: "ECIB",
};

/**
 * Record one month of post-disbursement surveillance through
 * `POST /ews/monitor`. The backend re-scores the borrower and raises an alert
 * when the drop from the origination baseline exceeds 15 points.
 */
export default function MonitoringPanel({ onMonitored }) {
  const [borrowers, setBorrowers] = useState([]);
  const [form, setForm] = useState(INITIAL_FORM);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchApplications({ limit: 200 })
      .then((data) => {
        if (cancelled) return;
        setBorrowers(data);
        setForm((previous) =>
          previous.borrower_id || data.length === 0
            ? previous
            : { ...previous, borrower_id: String(data[0].id) },
        );
      })
      .catch(() => setBorrowers([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await monitorBorrower({
        borrower_id: Number(form.borrower_id),
        month_number: Number(form.month_number),
        installment_status: form.installment_status,
        bureau_balance: Number(form.bureau_balance),
        pos_cash_balance: Number(form.pos_cash_balance),
        data_source_primary: form.data_source_primary,
      });
      setResult(response);
      onMonitored?.(response);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "The monitoring run failed."));
      setResult(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">Run monthly monitoring</h2>
          <p className="mt-1 text-sm text-slate-500">
            Feeds ECIB balances and POS settlements into the EWS model.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4 px-5 py-5 md:grid-cols-3">
        <div className="md:col-span-1">
          <label className="field-label" htmlFor="borrower_id">
            Borrower
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
              Select a disbursed facility
            </option>
            {borrowers.map((borrower) => (
              <option key={borrower.id} value={borrower.id}>
                #{borrower.id} · {borrower.business_name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="field-label" htmlFor="month_number">
            Month since disbursement
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
          <label className="field-label" htmlFor="bureau_balance">
            Bureau balance <span className="text-xs text-slate-400">(PKR)</span>
          </label>
          <input
            id="bureau_balance"
            name="bureau_balance"
            type="number"
            min="0"
            step="10000"
            value={form.bureau_balance}
            onChange={handleChange}
            required
            className="field-input"
          />
          {form.bureau_balance ? (
            <p className="tabular mt-1 text-xs text-slate-500">
              {formatPKR(form.bureau_balance)}
            </p>
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
            step="10000"
            value={form.pos_cash_balance}
            onChange={handleChange}
            required
            className="field-input"
          />
          {form.pos_cash_balance ? (
            <p className="tabular mt-1 text-xs text-slate-500">
              {formatPKR(form.pos_cash_balance)}
            </p>
          ) : null}
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
        </div>

        <div className="md:col-span-3 flex flex-wrap items-center justify-between gap-3">
          {error ? (
            <p role="alert" className="text-sm font-medium text-rose-700">
              {error}
            </p>
          ) : (
            <p className="text-xs text-slate-500">
              An alert is raised when the score falls more than 15 points below the
              origination baseline.
            </p>
          )}
          <button type="submit" className="btn-primary" disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Spinner className="h-4 w-4 text-white" />
                Running…
              </>
            ) : (
              "Run monitoring"
            )}
          </button>
        </div>
      </form>

      {result ? (
        <div
          className={`border-t px-5 py-4 ${
            result.alert_triggered
              ? "border-rose-200 bg-rose-50"
              : "border-emerald-200 bg-emerald-50"
          }`}
        >
          <div className="flex flex-wrap items-center gap-x-8 gap-y-2 text-sm">
            <Metric label="Baseline" value={result.baseline_score.toFixed(1)} />
            <Metric label="Current" value={result.current_score.toFixed(1)} />
            <Metric
              label="Drop"
              value={`${result.score_drop >= 0 ? "−" : "+"}${Math.abs(result.score_drop).toFixed(1)}`}
              tone={result.alert_triggered ? "danger" : "normal"}
            />
            {result.estimated_days_to_default !== null ? (
              <Metric
                label="Days to default"
                value={result.estimated_days_to_default}
                tone="danger"
              />
            ) : null}
            <span
              className={`badge ${
                result.alert_triggered
                  ? "bg-rose-600 text-white"
                  : "bg-emerald-600 text-white"
              }`}
            >
              {result.alert_triggered ? "Alert triggered" : "No alert"}
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-700">{result.recommended_action}</p>
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value, tone = "normal" }) {
  return (
    <span>
      <span className="block text-[11px] font-medium tracking-wide text-slate-500 uppercase">
        {label}
      </span>
      <span
        className={`tabular text-lg font-bold ${
          tone === "danger" ? "text-rose-700" : "text-slate-900"
        }`}
      >
        {value}
      </span>
    </span>
  );
}
