import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiErrorMessage, scoreApplication } from "../api/client.js";
import { formatPKR, formatPKRCompact } from "../lib/format.js";
import ScoreDial from "./ScoreDial.jsx";
import { Spinner } from "./common/States.jsx";

/** Field definitions mirror the backend's Pydantic ranges exactly. */
const FIELD_GROUPS = [
  {
    title: "Applicant & business",
    description: "Identity of the borrower as recorded in the credit file.",
    fields: [
      {
        name: "applicant_name",
        label: "Applicant name",
        type: "text",
        placeholder: "e.g. Ayesha Siddiqui",
        minLength: 2,
        maxLength: 120,
      },
      {
        name: "business_name",
        label: "Business name",
        type: "text",
        placeholder: "e.g. Siddiqui Textiles (Faisalabad)",
        minLength: 2,
        maxLength: 160,
      },
    ],
  },
  {
    title: "Facility requested",
    description: "Amount and tenure being underwritten.",
    fields: [
      {
        name: "loan_amount_pkr",
        label: "Loan amount",
        type: "number",
        currency: true,
        min: 1,
        max: 500000000,
        step: 50000,
        hint: "Requested facility in PKR.",
      },
      {
        name: "tenure_months",
        label: "Tenure (months)",
        type: "number",
        min: 3,
        max: 84,
        step: 1,
        integer: true,
        hint: "Between 3 and 84 months.",
        unusedByModel: true,
      },
    ],
  },
  {
    title: "Alternative data signals",
    description:
      "Digital footprint and officer-entered bureau-style signals (not a live bureau feed).",
    fields: [
      {
        name: "monthly_digital_payments",
        label: "Monthly digital payments",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 25000,
        hint: "Average monthly Raast, POS and wallet receipts.",
      },
      {
        name: "payment_history_score",
        label: "Payment history score",
        type: "number",
        min: 0,
        max: 100,
        step: 1,
        hint: "Officer-entered 0–100 score on an ECIB-oriented scale. Not pulled from a live bureau.",
      },
      {
        name: "inventory_turnover",
        label: "Inventory turnover",
        type: "number",
        min: 0,
        max: 50,
        step: 0.1,
        hint: "Times stock is sold per year.",
        unusedByModel: true,
      },
      {
        name: "order_consistency",
        label: "Order consistency",
        type: "number",
        min: 0,
        max: 100,
        step: 1,
        hint: "Stability of order volumes over 12 months (0-100).",
        unusedByModel: true,
      },
      {
        name: "existing_debt_pkr",
        label: "Existing debt",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 50000,
        hint: "Outstanding exposure across all lenders.",
        unusedByModel: true,
      },
      {
        name: "cash_flow_proxy",
        label: "Monthly cash flow proxy",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 25000,
        hint: "Estimated monthly net cash flow.",
      },
      {
        name: "years_in_operation",
        label: "Years in operation",
        type: "number",
        min: 0,
        max: 100,
        step: 0.5,
        hint: "How long the business has been trading.",
      },
      {
        name: "num_employees",
        label: "Employees",
        type: "number",
        min: 0,
        max: 5000,
        step: 1,
        integer: true,
        hint: "Headcount including owners.",
        unusedByModel: true,
      },
    ],
  },
];

const ALL_FIELDS = FIELD_GROUPS.flatMap((group) => group.fields);

const EMPTY_FORM = Object.fromEntries(ALL_FIELDS.map((field) => [field.name, ""]));

/** Demo profiles so an officer can walk through each policy band quickly. */
const SAMPLE_PROFILES = [
  {
    id: "strong",
    label: "Established textile exporter",
    values: {
      applicant_name: "Ayesha Siddiqui",
      business_name: "Siddiqui Textiles (Faisalabad)",
      loan_amount_pkr: "2400000",
      tenure_months: "36",
      monthly_digital_payments: "3200000",
      payment_history_score: "92",
      inventory_turnover: "9.5",
      order_consistency: "90",
      existing_debt_pkr: "400000",
      cash_flow_proxy: "850000",
      years_in_operation: "12",
      num_employees: "45",
    },
  },
  {
    id: "borderline",
    label: "Neighbourhood kiryana store",
    values: {
      applicant_name: "Hina Raza",
      business_name: "Raza Kiryana Store (Lahore)",
      loan_amount_pkr: "1200000",
      tenure_months: "24",
      monthly_digital_payments: "500000",
      payment_history_score: "62",
      inventory_turnover: "5",
      order_consistency: "58",
      existing_debt_pkr: "900000",
      cash_flow_proxy: "220000",
      years_in_operation: "4",
      num_employees: "8",
    },
  },
  {
    id: "weak",
    label: "Over-leveraged spare parts trader",
    values: {
      applicant_name: "Bilal Ahmed",
      business_name: "Ahmed Auto Spares (Karachi)",
      loan_amount_pkr: "3000000",
      tenure_months: "12",
      monthly_digital_payments: "25000",
      payment_history_score: "18",
      inventory_turnover: "0.6",
      order_consistency: "15",
      existing_debt_pkr: "4500000",
      cash_flow_proxy: "60000",
      years_in_operation: "0.5",
      num_employees: "2",
    },
  },
];

function validate(values) {
  const errors = {};

  for (const field of ALL_FIELDS) {
    const raw = String(values[field.name] ?? "").trim();

    if (!raw) {
      errors[field.name] = "Required.";
      continue;
    }

    if (field.type === "text") {
      if (raw.length < field.minLength) {
        errors[field.name] = `At least ${field.minLength} characters.`;
      } else if (raw.length > field.maxLength) {
        errors[field.name] = `At most ${field.maxLength} characters.`;
      }
      continue;
    }

    const numeric = Number(raw);
    if (Number.isNaN(numeric)) {
      errors[field.name] = "Enter a number.";
    } else if (numeric < field.min) {
      errors[field.name] = `Minimum is ${field.min}.`;
    } else if (numeric > field.max) {
      errors[field.name] = `Maximum is ${field.max.toLocaleString("en-PK")}.`;
    } else if (field.integer && !Number.isInteger(numeric)) {
      errors[field.name] = "Whole numbers only.";
    }
  }

  return errors;
}

function toPayload(values) {
  const payload = {};
  for (const field of ALL_FIELDS) {
    const raw = String(values[field.name]).trim();
    payload[field.name] = field.type === "number" ? Number(raw) : raw;
  }
  return payload;
}

/**
 * Credit application intake form.
 *
 * Submits to `POST /score` and renders the returned score in the gauge next to
 * the form, together with the decision and the strongest SHAP factors.
 */
export default function ApplicationForm({ onScored }) {
  const navigate = useNavigate();
  const [values, setValues] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setValues((previous) => ({ ...previous, [name]: value }));
    setErrors((previous) => {
      if (!previous[name]) return previous;
      const next = { ...previous };
      delete next[name];
      return next;
    });
  };

  const applySample = (sample) => {
    setValues(sample.values);
    setErrors({});
    setSubmitError(null);
  };

  const handleReset = () => {
    setValues(EMPTY_FORM);
    setErrors({});
    setSubmitError(null);
    setResult(null);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const validationErrors = validate(values);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      setSubmitError("Please correct the highlighted fields before submitting.");
      return;
    }

    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const scored = await scoreApplication(toPayload(values));
      setResult(scored);
      onScored?.(scored);
    } catch (error) {
      setSubmitError(apiErrorMessage(error, "The application could not be scored."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <form onSubmit={handleSubmit} noValidate className="card xl:col-span-2">
        <div className="card-header">
          <div>
            <h2 className="card-title">New credit assessment</h2>
            <p className="mt-1 text-sm text-slate-500">
              All amounts in PKR. Bureau-style fields are typed in by the officer — not a live ECIB connection.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-slate-500">Load sample:</span>
            {SAMPLE_PROFILES.map((sample) => (
              <button
                key={sample.id}
                type="button"
                onClick={() => applySample(sample)}
                className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:border-brand-400 hover:text-brand-700"
              >
                {sample.label}
              </button>
            ))}
          </div>
        </div>

        <div className="space-y-7 px-5 py-5">
          {FIELD_GROUPS.map((group) => (
            <fieldset key={group.title} className="space-y-4">
              <legend className="text-sm font-semibold text-slate-900">
                {group.title}
              </legend>
              <p className="-mt-3 text-xs text-slate-500">{group.description}</p>
              <div className="grid gap-4 sm:grid-cols-2">
                {group.fields.map((field) => (
                  <FormField
                    key={field.name}
                    field={field}
                    value={values[field.name]}
                    error={errors[field.name]}
                    onChange={handleChange}
                  />
                ))}
              </div>
            </fieldset>
          ))}
        </div>

        {submitError ? (
          <div
            role="alert"
            className="mx-5 mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800"
          >
            {submitError}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4">
          <p className="text-xs text-slate-500">
            Submitting stores the assessment and its SHAP rationale on-premise for later review. Not SBP-certified.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={handleReset} className="btn-secondary">
              Clear
            </button>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Spinner className="h-4 w-4 text-white" />
                  Scoring…
                </>
              ) : (
                "Score application"
              )}
            </button>
          </div>
        </div>
      </form>

      <aside className="card h-fit xl:sticky xl:top-6">
        <div className="card-header">
          <h2 className="card-title">Assessment result</h2>
          {result ? (
            <span className="text-xs text-slate-500">#{result.application_id}</span>
          ) : null}
        </div>

        <div className="px-5 py-6">
          <ScoreDial
            score={result ? result.risk_score : null}
            decision={result?.decision}
            riskBand={result?.risk_band}
            size={260}
          />

          {result ? (
            <div className="mt-6 space-y-4">
              <dl className="space-y-2 text-sm">
                <ResultRow label="Applicant" value={result.applicant_name} />
                <ResultRow label="Business" value={result.business_name} />
                <ResultRow
                  label="Facility"
                  value={`${formatPKRCompact(result.loan_amount_pkr)} · ${result.tenure_months} months`}
                />
                <ResultRow
                  label="Monthly installment"
                  value={formatPKR(result.monthly_installment_pkr)}
                />
              </dl>

              {result.explanation ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                  <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
                    Key drivers
                  </p>
                  <p className="mt-1 text-sm text-slate-700">
                    {result.explanation.narrative}
                  </p>
                </div>
              ) : null}

              <button
                type="button"
                className="btn-primary w-full"
                onClick={() => navigate(`/shap/${result.application_id}`)}
              >
                View full SHAP report
              </button>
            </div>
          ) : (
            <p className="mt-6 text-center text-sm text-slate-500">
              Complete the form to generate a score, a decision and an explainable
              rationale.
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}

function FormField({ field, value, error, onChange }) {
  const showCurrencyHint = field.currency && value !== "" && !Number.isNaN(Number(value));

  return (
    <div>
      <label className="field-label" htmlFor={field.name}>
        {field.label}
        {field.currency ? (
          <span className="ml-1 text-xs font-normal text-slate-400">(PKR)</span>
        ) : null}
      </label>
      <input
        id={field.name}
        name={field.name}
        type={field.type}
        value={value}
        onChange={onChange}
        placeholder={field.placeholder}
        min={field.min}
        max={field.max}
        step={field.step}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${field.name}-error` : undefined}
        className={`field-input ${error ? "field-input-error" : ""}`}
      />
      {error ? (
        <p id={`${field.name}-error`} className="mt-1 text-xs font-medium text-rose-600">
          {error}
        </p>
      ) : showCurrencyHint ? (
        <p className="tabular mt-1 text-xs text-slate-500">{formatPKR(value)}</p>
      ) : field.hint ? (
        <p className="mt-1 text-xs text-slate-500">{field.hint}</p>
      ) : null}
      {field.unusedByModel ? (
        <p
          className="mt-1 text-xs font-semibold text-amber-800"
          title="Collected for future scoring versions — not currently used in this risk score."
        >
          Collected for future scoring versions — not currently used in this risk score.
        </p>
      ) : null}
    </div>
  );
}

function ResultRow({ label, value }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 pb-2 last:border-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right font-medium text-slate-900">{value}</dd>
    </div>
  );
}
