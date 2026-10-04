import { useCallback, useEffect, useState } from "react";

import { apiErrorMessage, fetchReminders } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States.jsx";
import { formatDate, formatPKR } from "../lib/format.js";

const KIND = {
  overdue: { label: "Overdue", className: "bg-rose-100 text-rose-800 ring-1 ring-rose-200" },
  arrears: { label: "Arrears", className: "bg-amber-100 text-amber-800 ring-1 ring-amber-200" },
  due_soon: { label: "Due soon", className: "bg-sky-100 text-sky-800 ring-1 ring-sky-200" },
};

/**
 * Payment reminders for approved facilities: installments past due, due within
 * a week, or unpaid from earlier months. ForiFlow drafts the message; the
 * officer copies it or opens it in WhatsApp and sends it themselves.
 */
export default function RemindersPage() {
  const [reminders, setReminders] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [language, setLanguage] = useState("ur");
  const [copiedId, setCopiedId] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setReminders(await fetchReminders());
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the reminders."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const copy = async (reminder, message) => {
    try {
      await navigator.clipboard.writeText(message);
      setCopiedId(reminder.application_id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      setCopiedId(null);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Payment reminders</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Installments that are overdue, due within 7 days, or unpaid from earlier
            months. The schedule runs monthly from the day a facility was approved, and
            an installment is cleared once its month is recorded under EWS Alerts.
            ForiFlow only drafts the message. You send it.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-500">Message in</span>
          {[
            ["ur", "Roman Urdu"],
            ["en", "English"],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setLanguage(value)}
              aria-pressed={language === value}
              className={`rounded-md border px-2.5 py-1 text-xs font-medium transition ${
                language === value
                  ? "border-brand-600 bg-brand-600 text-white"
                  : "border-slate-300 text-slate-600 hover:border-brand-400"
              }`}
            >
              {label}
            </button>
          ))}
          <button type="button" className="btn-secondary px-3 py-1.5 text-xs" onClick={load}>
            Refresh
          </button>
        </div>
      </header>

      {isLoading ? (
        <LoadingState label="Loading reminders…" />
      ) : error ? (
        <ErrorState message={error} onRetry={load} />
      ) : reminders.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No reminders today"
            description="No approved facility has an installment overdue, due within 7 days, or unpaid from earlier months."
          />
        </div>
      ) : (
        <ul className="space-y-4">
          {reminders.map((reminder) => {
            const kind = KIND[reminder.kind];
            const message = language === "ur" ? reminder.message_ur : reminder.message_en;
            const phone = reminder.contact_phone?.replace(/^\+/, "");
            return (
              <li key={reminder.application_id} className="card px-5 py-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {reminder.business_name}
                      <span className="ml-2 font-normal text-slate-500">
                        {reminder.applicant_name} · App #{reminder.application_id}
                      </span>
                    </p>
                    <p className="tabular mt-0.5 text-xs text-slate-500">
                      {reminder.installment_number
                        ? `Installment ${reminder.installment_number} of ${formatPKR(
                            reminder.installment_pkr,
                          )}, due ${formatDate(reminder.due_date)}`
                        : `Installment ${formatPKR(reminder.installment_pkr)}`}
                      {reminder.days_until_due !== null
                        ? reminder.days_until_due < 0
                          ? ` · ${-reminder.days_until_due} days late`
                          : ` · in ${reminder.days_until_due} days`
                        : ""}
                      {reminder.arrears_pkr > 0
                        ? ` · ${formatPKR(reminder.arrears_pkr)} unpaid from earlier months`
                        : ""}
                    </p>
                  </div>
                  <span className={`badge ${kind.className}`}>{kind.label}</span>
                </div>

                <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800">
                  {message}
                </p>

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="btn-secondary px-3 py-1.5 text-xs"
                    onClick={() => copy(reminder, message)}
                  >
                    {copiedId === reminder.application_id ? "Copied" : "Copy message"}
                  </button>
                  {phone ? (
                    <a
                      className="btn-primary px-3 py-1.5 text-xs"
                      href={`https://wa.me/${phone}?text=${encodeURIComponent(message)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open in WhatsApp
                    </a>
                  ) : (
                    <span className="text-xs text-slate-500">
                      No contact number on file for this borrower.
                    </span>
                  )}
                  {phone ? (
                    <span className="tabular text-xs text-slate-500">{reminder.contact_phone}</span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
