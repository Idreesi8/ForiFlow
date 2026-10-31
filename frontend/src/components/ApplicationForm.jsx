import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  apiErrorMessage,
  fetchFeatureContract,
  scoreApplication,
  summariseStatement,
} from "../api/client.js";
import { FIELD_GROUPS, ALL_FIELDS, validateAssessment, assessmentPayload, assessmentKey, statementReview } from "../lib/assessmentIntake.js";
import AssessmentReview from "./AssessmentReview.jsx";
import { assessmentIntent, assessmentReceiptMatches, assessmentSaveUncertain } from '../lib/assessmentSave.js';
import { contractSummary, unusedFieldNames } from "../lib/featureContract.js";
import { formatPKR, formatPKRCompact, formatPercent } from "../lib/format.js";
import PathToApproval from "./PathToApproval.jsx";
import StatementResilience from "./StatementResilience.jsx";
import ScoreDial from "./ScoreDial.jsx";
import ModelInputCheck from "./ModelInputCheck.jsx";
import OperatingChecks from "./OperatingChecks.jsx";
import { OPERATING_USES } from "../lib/operatingChecks.js";
import { useActivePolicy } from "../lib/useActivePolicy.js";
import { Spinner } from "./common/States.jsx";
import { useUnsavedWork } from "./UnsavedWork.jsx";

const STATIC_UNUSED_FIELDS = ALL_FIELDS.filter((field) => field.unusedByModel).map(
  (field) => field.name,
);

/**
 * In the training data the default rate jumps from 22% to 67% once a loan
 * exceeds 30% of gross annual income, and the model inherits that cliff
 * (backend/README.md, "Model limitations"). Turnover is estimated exactly as
 * the backend does: the larger of digital receipts and cash flow, times 12.
 */
const FACILITY_TURNOVER_CLIFF = 0.3;

function facilityToTurnover(values) {
  const loan = Number(values.loan_amount_pkr);
  const monthly = Math.max(
    Number(values.monthly_digital_payments) || 0,
    Number(values.cash_flow_proxy) || 0,
  );
  if (!loan || !monthly) return null;
  return loan / (monthly * 12);
}

const EMPTY_FORM = Object.fromEntries(ALL_FIELDS.map((field) => [field.name, ""]));

/** Demo profiles so an officer can walk through each policy band quickly. */
const SAMPLE_PROFILES = [
  {
    id: "strong",
    label: "Established textile exporter",
    values: {
      applicant_name: "Ayesha Siddiqui",
      business_name: "Siddiqui Textiles (Faisalabad)",
      business_sector: "Textile & Garments",
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
      business_sector: "Retail",
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
      business_sector: "Wholesale & Trading",
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

/** Fields the statement fills, and the summary key each one comes from. */
const STATEMENT_FIELDS = {
  monthly_digital_payments: "suggested_monthly_digital_payments",
  cash_flow_proxy: "suggested_cash_flow_proxy",
  order_consistency: "suggested_order_consistency",
};

/**
 * Credit application intake form.
 *
 * Submits to `POST /score` and renders the returned score in the gauge next to
 * the form, together with the decision and the strongest SHAP factors.
 */
export default function ApplicationForm({ onScored, reviewLocked = false, onReviewFocus }) {
  const navigate = useNavigate();
  // Before an assessment the dial shows the policy in force; afterwards the
  // assessment's own policy snapshot, which is what its recommendation used.
  const activePolicy = useActivePolicy();
  const [values, setValues] = useState(EMPTY_FORM);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const submitting = useRef(false);
  const [review, setReview] = useState(null);
  const [saveUncertain, setSaveUncertain] = useState(false);
  const reviewHeading = useRef(null);
  const resultHeading = useRef(null);
  const [result, setResult] = useState(null);
  const [statement, setStatement] = useState(null);
  const [statementError, setStatementError] = useState(null);
  const [isReadingStatement, setIsReadingStatement] = useState(false);
  const statementRequest = useRef(0);
  const statementController = useRef(null);
  const [savedFingerprint, setSavedFingerprint] = useState(null);
  const [pendingReplacement, setPendingReplacement] = useState(null);
  const replacementNotice = useRef(null);
  const errorSummary = useRef(null);
  const requiredFields = ALL_FIELDS.filter(field => !field.optional);
  const filledRequired = requiredFields.filter(field => String(values[field.name] ?? "").trim()).length;
  const hasEntries = Boolean(statement) || Object.values(values).some(value => String(value ?? "").trim());
  const unchangedSaved = Boolean(result && savedFingerprint?.intent === assessmentIntent(values, statement) && !Object.keys(validateAssessment(values)).length);
  useUnsavedWork({ label: saveUncertain ? 'Assessment save outcome unverified' : 'New credit assessment', dirty: saveUncertain || (hasEntries && !unchangedSaved),
    busy: isSubmitting || isReadingStatement,
    leaveWarning: saveUncertain ? 'The server may already have saved this assessment. Leaving loses this tab’s retry reference and does not cancel that save. Recover its result before starting another assessment.' : null });
  const cancelStatement = () => {
    statementRequest.current += 1;
    statementController.current?.abort();
    setIsReadingStatement(false);
  };
  useEffect(() => () => { statementRequest.current += 1; statementController.current?.abort(); }, []);
  const focusField = id => {
    const element = document.getElementById(id);
    element?.scrollIntoView({ block: "center" });
    element?.focus({ preventScroll: true });
  };
  const editReview = (id = "assessment-applicant") => {
    if (submitting.current || saveUncertain) return;
    setReview(null);
    setSubmitError(null);
    requestAnimationFrame(() => focusField(id));
  };
  useEffect(() => { if (review) { reviewHeading.current?.scrollIntoView({ block: "start" }); reviewHeading.current?.focus({ preventScroll: true }); } }, [review]);
  useEffect(() => { if (result) { resultHeading.current?.scrollIntoView({ block: "start" }); resultHeading.current?.focus({ preventScroll: true }); } }, [result]);
  useEffect(() => { if (saveUncertain) { reviewHeading.current?.scrollIntoView({ block: 'start' }); reviewHeading.current?.focus({ preventScroll: true }); } }, [saveUncertain]);
  useEffect(() => { if (pendingReplacement) replacementNotice.current?.focus(); }, [pendingReplacement]);
  useEffect(() => { if (Object.keys(errors).length) errorSummary.current?.focus(); }, [submitError]);
  // Which fields the model serving now actually reads (GET /model/feature-contract).
  const [contract, setContract] = useState(null);
  useEffect(() => {
    let alive = true;
    fetchFeatureContract()
      .then((value) => alive && setContract(value))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);
  const unusedFields = unusedFieldNames(contract, STATIC_UNUSED_FIELDS);
  const contractLine = contractSummary(contract);
  const turnoverRatio = facilityToTurnover(values);
  const fieldNotes = {
    loan_amount_pkr:
      turnoverRatio !== null && turnoverRatio > FACILITY_TURNOVER_CLIFF
        ? `This facility is ${Math.round(turnoverRatio * 100)}% of estimated annual turnover. Above 30% the model scores sharply lower, inherited from its training data.`
        : null,
  };

  const handleChange = (event) => {
    if (submitting.current || saveUncertain) return;
    const { name, value } = event.target;
    setReview(null);
    setValues((previous) => ({ ...previous, [name]: value }));
    setErrors((previous) => {
      if (!previous[name]) return previous;
      const next = { ...previous };
      delete next[name];
      return next;
    });
  };

  const applySample = (sample) => {
    if (submitting.current || saveUncertain) return;
    setReview(null);
    cancelStatement();
    setValues({ ...EMPTY_FORM, ...sample.values });
    setErrors({});
    setSubmitError(null);
    setStatement(null);
    setStatementError(null);
    setPendingReplacement(null);
  };

  // Read the chosen CSV in the browser, let the API summarise it, and fill the
  // turnover fields. The same text is sent again with the application, so the
  // API can store what the statement really shows.
  const handleStatement = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (isSubmitting || saveUncertain) return;
    setReview(null);
    const request = ++statementRequest.current;
    statementController.current?.abort();
    const controller = new AbortController();
    statementController.current = controller;
    setIsReadingStatement(true);
    setStatementError(null);
    try {
      const csv = await file.text();
      if (controller.signal.aborted || request !== statementRequest.current) return;
      const summary = await summariseStatement(csv, { signal: controller.signal });
      if (controller.signal.aborted || request !== statementRequest.current) return;
      setStatement({ csv, summary, fileName: file.name });
      setValues((previous) => ({
        ...previous,
        ...Object.fromEntries(
          Object.entries(STATEMENT_FIELDS).map(([name, key]) => [name, String(summary[key])]),
        ),
      }));
      setErrors({});
    } catch (error) {
      if (!controller.signal.aborted && request === statementRequest.current) {
        setStatementError(apiErrorMessage(error, "The statement could not be read.") +
          (statement ? ' The previously attached statement is still in use.' : ''));
      }
    } finally {
      if (request === statementRequest.current) setIsReadingStatement(false);
    }
  };

  const handleReset = () => {
    if (reviewLocked || submitting.current || saveUncertain) return;
    cancelStatement();
    setReview(null);
    setStatement(null);
    setStatementError(null);
    setValues(EMPTY_FORM);
    setErrors({});
    setSubmitError(null);
    setResult(null);
    setSavedFingerprint(null);
    setPendingReplacement(null);
    onScored?.(null);
    requestAnimationFrame(() => focusField('assessment-applicant'));
  };

  const requestReplacement = change => {
    if (isSubmitting || saveUncertain) return;
    if (hasEntries && !unchangedSaved) setPendingReplacement(change);
    else if (change.sample) applySample(change.sample);
    else handleReset();
  };

  const handleReview = (event) => {
    event.preventDefault();
    if (submitting.current || isReadingStatement || reviewLocked || review) return;
    if (unchangedSaved) { resultHeading.current?.scrollIntoView({ block: 'start' }); resultHeading.current?.focus({ preventScroll: true }); return; }
    const validationErrors = validateAssessment(values);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) {
      setSubmitError("Please correct the highlighted fields before reviewing.");
      requestAnimationFrame(() => errorSummary.current?.focus());
      return;
    }
    setSubmitError(null);
    setPendingReplacement(null);
    setReview({ key: assessmentKey(values, statement), submissionKey: crypto.randomUUID(), payload: assessmentPayload(values), statement });
  };

  const handleConfirm = async () => {
    if (submitting.current || isReadingStatement || reviewLocked || !review) return;
    if (review.key !== assessmentKey(values, statement) || Object.keys(validateAssessment(values)).length) {
      editReview();
      return;
    }
    submitting.current = true;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const scored = await scoreApplication({
        ...review.payload,
        ...(review.statement ? { statement_csv: review.statement.csv } : {}),
      }, { submissionKey: review.submissionKey });
      if (!assessmentReceiptMatches(scored, review.payload)) {
        const failure = new Error('The save receipt could not be matched to these reviewed figures.');
        failure.code = 'UNVERIFIED_ASSESSMENT';
        throw failure;
      }
      setResult(scored);
      setSaveUncertain(false);
      setReview(null);
      setSavedFingerprint({ intent: assessmentIntent(values, statement) });
      onScored?.(scored);
    } catch (error) {
      setSaveUncertain(previous => previous || assessmentSaveUncertain(error));
      setSubmitError(error.code === 'UNVERIFIED_ASSESSMENT' ? error.message : apiErrorMessage(error, "The assessment save could not be verified."));
    } finally {
      submitting.current = false;
      setIsSubmitting(false);
    }
  };

  return (
    <div className="grid min-w-0 grid-cols-1 gap-6 xl:grid-cols-3">
      <form onSubmit={handleReview} noValidate className="card min-w-0 xl:col-span-2">
        <div className="card-header">
          <div>
            <h2 className="card-title">New credit assessment</h2>
            <p className="mt-1 text-sm text-slate-500">
              All amounts in PKR. Bureau-style fields are typed in by the officer — not a live ECIB connection.
            </p>
          </div>
          <details hidden={Boolean(review)} className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <summary className="text-xs font-semibold text-slate-600">Try a sample profile</summary>
            <p className="mt-3 text-xs leading-relaxed text-slate-500">Examples for exploring the form. Scoring a sample creates a saved assessment, just like any submission.</p>
            <div className="mt-3 flex flex-wrap gap-2">
            {SAMPLE_PROFILES.map((sample) => (
              <button
                key={sample.id}
                type="button"
                onClick={() => requestReplacement({ sample })}
                disabled={isSubmitting}
                className="btn-secondary text-xs"
              >
                {sample.label}
              </button>
            ))}
            </div>
          </details>
        </div>

        <div hidden={Boolean(review)} className="space-y-7 px-5 py-5">
          {reviewLocked ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" data-testid="review-replacement-lock"><p className="font-semibold">A decision reason is still being edited or saved below.</p><p className="mt-1 text-xs leading-relaxed">Finish that decision or clear its typed reason before scoring or clearing another assessment on this page.</p><button type="button" className="btn-secondary mt-3 text-xs" onClick={onReviewFocus}>Return to the decision reason</button></div> : null}
          {pendingReplacement ? <div ref={replacementNotice} tabIndex={-1} role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950" data-testid="assessment-replace-guard"><p className="font-semibold">Keep your current entries?</p><p className="mt-1 text-xs leading-relaxed">{pendingReplacement.sample ? "Loading this sample replaces the figures and any attached statement in this form." : "Clearing this form removes its entries and any attached statement. Saved assessments remain on file."}</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary text-xs" onClick={() => setPendingReplacement(null)}>Keep my entries</button><button type="button" className="btn-primary text-xs" disabled={isSubmitting || (reviewLocked && !pendingReplacement.sample)} onClick={() => pendingReplacement.sample ? applySample(pendingReplacement.sample) : handleReset()}>{pendingReplacement.sample ? "Replace with sample" : "Clear form"}</button></div></div> : null}
          <div aria-label="Assessment guide">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-semibold text-slate-800">Three sections. One assessment.</p><p className="text-xs text-slate-500">{filledRequired} of {requiredFields.length} required fields filled</p></div>
            <div role="progressbar" aria-label="Required fields filled" aria-valuemin={0} aria-valuemax={requiredFields.length} aria-valuenow={filledRequired} className="mb-4 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${filledRequired / requiredFields.length * 100}%` }} /></div>
            <div className="grid gap-2 sm:grid-cols-3">{FIELD_GROUPS.map((group, index) => {
              const required = group.fields.filter(field => !field.optional);
              const filled = required.filter(field => String(values[field.name] ?? "").trim()).length;
              const issues = group.fields.filter(field => errors[field.name]).length;
              return <button key={group.id} type="button" onClick={() => focusField(group.id)} className={`flex items-center gap-3 rounded-xl border p-3 text-left transition hover:border-brand-400 ${issues ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-slate-50"}`}><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-xs font-bold text-brand-700 ring-1 ring-slate-200">{index + 1}</span><span><span className="block text-xs font-semibold text-slate-800">{group.title}</span><span className={`mt-1 block text-[11px] ${issues ? "text-rose-700" : "text-slate-500"}`}>{issues ? `${issues} fields need attention` : `${filled}/${required.length} required fields filled`}</span></span></button>;
            })}</div>
            <p className="mt-3 text-xs text-slate-500">Optional fields are labelled. Filled fields still need to pass validation before scoring.</p>
          </div>
          {submitError ? <div ref={errorSummary} tabIndex={-1} role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800" data-testid="assessment-errors"><p className="font-semibold">{submitError}</p>{Object.keys(errors).length ? <ul className="mt-3 grid gap-2 sm:grid-cols-2">{ALL_FIELDS.filter(field => errors[field.name]).map(field => <li key={field.name}><button type="button" className="text-left text-xs underline underline-offset-2" onClick={() => focusField(field.name)}>{field.label}: {errors[field.name]}</button></li>)}</ul> : null}</div> : null}
          <StatementBox
            statement={statement}
            error={statementError}
            values={values}
            onPick={handleStatement}
            onRemove={() => { cancelStatement(); setReview(null); setStatement(null); setStatementError(null); }}
            busy={isReadingStatement}
            disabled={isSubmitting}
            onCancel={cancelStatement}
          />
          {contractLine ? (
            <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600" data-testid="feature-contract">
              {contractLine}
            </p>
          ) : null}
          {FIELD_GROUPS.map((group) => (
            <fieldset key={group.title} className="space-y-4 border-t border-slate-200 pt-5" disabled={isSubmitting || isReadingStatement}>
              <legend id={group.id} tabIndex={-1} className="scroll-mt-28 px-1 text-sm font-semibold text-slate-900">
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
                    note={fieldNotes[field.name]}
                    unused={unusedFields.has(field.name)}
                    onChange={handleChange}
                  />
                ))}
              </div>
            </fieldset>
          ))}
          <ModelInputCheck values={values} disabled={isSubmitting || isReadingStatement} onFixField={focusField} />
          {!review ? <OperatingChecks values={values} statement={statement} disabled={isSubmitting || isReadingStatement} onFixField={focusField} /> : null}
        </div>
        {review ? <>
          <AssessmentReview review={review} headingRef={reviewHeading} unusedFields={unusedFields} onEdit={editReview} disabled={isSubmitting || saveUncertain} saveUncertain={saveUncertain} onRetry={handleConfirm} retryDisabled={isSubmitting || isReadingStatement || reviewLocked} />
          {reviewLocked ? <p role="alert" className="mx-5 mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">Finish the decision reason below before saving another assessment.</p> : null}
          {submitError ? <p role="alert" className="mx-5 mb-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">{submitError}</p> : null}
        </> : null}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-5 py-4">
          <p className="text-xs text-slate-500">
            {review ? saveUncertain ? "Retry recovers or completes the original save. It does not approve or disburse a loan." : "Saving creates a new assessment on-premise. It does not approve or disburse a loan." : unchangedSaved ? "These figures are already saved. View their result or start another assessment." : "Next: review your entries before creating a saved assessment. Not SBP-certified."}
          </p>
          <div className="flex min-w-0 flex-wrap gap-2">
            <button type="button" onClick={() => review ? editReview() : requestReplacement({ clear: true })} disabled={isSubmitting || reviewLocked || saveUncertain} className="btn-secondary">
              {review ? "Back to editing" : unchangedSaved ? "Start new assessment" : "Clear"}
            </button>
            <button type={review || unchangedSaved ? "button" : "submit"} onClick={review ? handleConfirm : unchangedSaved ? () => { resultHeading.current?.scrollIntoView({ block: 'start' }); resultHeading.current?.focus({ preventScroll: true }); } : undefined} className="btn-primary" disabled={isSubmitting || isReadingStatement || reviewLocked}>
              {isSubmitting ? (
                <>
                  <Spinner className="h-4 w-4 text-white" />
                  Saving assessment…
                </>
              ) : (
                review ? saveUncertain ? "Retry same assessment" : "Save and score assessment" : unchangedSaved ? "View saved assessment" : "Review assessment"
              )}
            </button>
          </div>
        </div>
      </form>

      <aside className="card h-fit min-w-0 xl:sticky xl:top-28">
        <div className="card-header">
          <h2 ref={resultHeading} tabIndex={-1} className="card-title scroll-mt-28">Assessment result</h2>
          {result ? (
            <span className="text-xs text-slate-500">#{result.application_id}</span>
          ) : null}
        </div>

        <div className="px-5 py-6">
          {result ? <p className="mb-4 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">Last saved assessment #{result.application_id}. Editing these figures does not update that record. Changed figures need a new review and save.</p> : null}
          {saveUncertain ? <p role="status" className="mb-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">Waiting for a verified save result. Recover the assessment using its original submission reference.</p> : null}
          {result || !saveUncertain ? <ScoreDial
            score={result ? result.risk_score : null}
            decision={result?.decision}
            riskBand={result?.risk_band}
            bands={result ? result.policy?.bands : activePolicy}
            size={260}
          /> : null}

          {result ? (
            <div className="mt-6 space-y-4">
              {result.scoring_engine === "surrogate" ? (
                <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Demo formula active. This assessment was not produced by the trained ensemble.
                </p>
              ) : null}
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
                {result.probability_of_default !== null &&
                result.probability_of_default !== undefined ? (
                  <ResultRow
                    label="Calibrated PD (display only)"
                    value={formatPercent(result.probability_of_default)}
                  />
                ) : null}
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

              <PathToApproval path={result.explanation?.approval_path} compact />
              <StatementResilience evidence={result.turnover_evidence} compact />

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
              Complete the form to get a Risk Assessment, a ForiFlow Recommendation and an
              explainable rationale. The Credit Officer Decision comes after.
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}

/**
 * Fill the turnover fields from a wallet or bank statement instead of typing
 * them. Shows what the statement says and whether the form still matches it.
 */
function StatementBox({ statement, error, values, onPick, onRemove, busy, disabled, onCancel }) {
  const summary = statement?.summary;
  const edited = statementReview(statement, values).status === "edited";

  return (
    <div id="assessment-statement" tabIndex={-1} className="scroll-mt-28 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">Fill turnover from a statement</p>
          <p className="text-xs text-slate-500">
            A CSV export of the applicant's wallet or bank account, at least 3 full months.
            It replaces typing the turnover, which drives most of the score.
          </p>
        </div>
        <label aria-disabled={disabled} className={`btn-secondary px-3 py-1.5 text-xs ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
          {statement ? "Choose another file" : "Choose CSV file"}
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={onPick} disabled={disabled} />
        </label>
      </div>

      {busy ? <div className="mt-3 flex flex-wrap items-center justify-between gap-3"><p role="status" className="flex items-center gap-2 text-xs text-brand-700"><Spinner className="h-4 w-4" />Checking statement. Financial inputs are paused until it finishes.</p><button type="button" className="btn-secondary text-xs" onClick={onCancel}>Cancel statement read</button></div> : null}

      {error ? (
        <p role="alert" className="mt-2 text-xs font-medium text-rose-700">
          {error}
        </p>
      ) : null}

      {summary ? (
        <div className="mt-3 border-t border-slate-200 pt-3 text-xs text-slate-700">
          <p>
            <span className="font-semibold text-slate-900">{statement.fileName}</span>:{" "}
            {summary.full_months} full months, {summary.transactions.toLocaleString("en-PK")}{" "}
            transactions, {summary.period_start} to {summary.period_end}.
          </p>
          <p className="tabular mt-1">
            Median money in per month {formatPKR(summary.monthly_inflow_median)} · median net{" "}
            {formatPKR(summary.monthly_net_median)} · monthly spread{" "}
            {(summary.inflow_variation * 100).toFixed(0)}% of the average.
          </p>
          {summary.warnings.map((warning) => (
            <p key={warning} className="mt-1 font-medium text-amber-800">
              Check: {warning}
            </p>
          ))}
          <p className={`mt-1 font-medium ${edited ? "text-amber-800" : "text-brand-700"}`}>
            {edited
              ? "The turnover fields no longer match the statement. The credit file will say so."
              : "Digital payments, cash flow and order consistency are filled from this file."}
          </p>
          <button
            type="button"
            onClick={onRemove}
            disabled={disabled}
            className="mt-1 text-xs font-semibold text-slate-500 underline hover:text-slate-700"
          >
            Remove statement
          </button>
        </div>
      ) : null}
    </div>
  );
}

function FormField({ field, value, error, note, unused, onChange }) {
  const showCurrencyHint = field.currency && value !== "" && !Number.isNaN(Number(value));

  return (
    <div>
      <label className="field-label" htmlFor={field.name}>
        {field.label}
        {field.optional ? <span className="ml-1 text-xs font-normal text-slate-500">(optional)</span> : null}
        {field.currency ? (
          <span className="ml-1 text-xs font-normal text-slate-400">(PKR)</span>
        ) : null}
      </label>
      {field.type === "select" ? (
        <select
          id={field.name}
          name={field.name}
          value={value ?? ""}
          onChange={onChange}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${field.name}-error` : undefined}
          className="field-input"
        >
          <option value="">Not recorded</option>
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={field.name}
          name={field.name}
          type={field.type}
          value={value ?? ""}
          onChange={onChange}
          placeholder={field.placeholder}
          min={field.min}
          max={field.max}
          step={field.step}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${field.name}-error` : undefined}
          className={`field-input ${error ? "field-input-error" : ""}`}
        />
      )}
      {error ? (
        <p id={`${field.name}-error`} className="mt-1 text-xs font-medium text-rose-600">
          {error}
        </p>
      ) : showCurrencyHint ? (
        <p className="tabular mt-1 text-xs text-slate-500">{formatPKR(value)}</p>
      ) : field.hint ? (
        <p className="mt-1 text-xs text-slate-500">{field.hint}</p>
      ) : null}
      {note ? (
        <p role="status" className="mt-1 text-xs font-semibold text-amber-800">
          {note}
        </p>
      ) : null}
      {unused ? (
        <p
          className="mt-1 text-xs font-semibold text-amber-800"
          title={OPERATING_USES[field.name] || "Recorded on the credit file; not read by the current model."}
          data-unused-field={field.name}
        >
          {OPERATING_USES[field.name] ? `Active in business checks: ${OPERATING_USES[field.name].toLowerCase()}. Not in the current ML score.` : "Recorded, not used by the current model — does not change this score."}
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
