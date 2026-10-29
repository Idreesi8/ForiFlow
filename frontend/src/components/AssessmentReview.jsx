import { FIELD_GROUPS, assessmentDisplay, statementReview } from "../lib/assessmentIntake.js";
import OperatingChecks from './OperatingChecks.jsx';

/** Review the same payload that will be submitted, without creating a record. */
export default function AssessmentReview({ review, headingRef, unusedFields, onEdit, disabled }) {
  const evidence = statementReview(review.statement, review.payload);
  return <section aria-labelledby="assessment-review-title" className="space-y-5 px-5 py-5" data-testid="assessment-review">
    <div className="rounded-xl border border-brand-200 bg-brand-50 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Review before saving</p>
      <h3 ref={headingRef} id="assessment-review-title" tabIndex={-1} className="mt-1 scroll-mt-28 text-lg font-bold text-slate-900">Check the credit file</h3>
      <p className="mt-2 text-sm leading-relaxed text-slate-700">Nothing has been saved from this review. Confirming below creates a new assessment with these figures and a model recommendation. A credit officer decides separately.</p>
    </div>
    <div className={`rounded-xl border p-4 ${evidence.status === "edited" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex items-start justify-between gap-3">
        <h4 className="text-sm font-semibold text-slate-900">Turnover evidence</h4>
        <button type="button" className="shrink-0 text-xs font-semibold text-brand-700 underline underline-offset-2" disabled={disabled} onClick={() => onEdit("assessment-statement")}>Edit evidence</button>
      </div>
      {review.statement ? <>
        <p className="mt-2 break-words text-sm text-slate-700">{review.statement.fileName} · {review.statement.summary.full_months} full months</p>
        <p className="mt-1 text-xs text-slate-600">{review.statement.summary.period_start} to {review.statement.summary.period_end}</p>
        <p className={`mt-2 text-xs font-semibold ${evidence.status === "edited" ? "text-amber-900" : "text-slate-700"}`}>{evidence.status === "edited" ? "Entered turnover differs from the attached statement. Both will be sent; the API checks and records the difference." : "Entered turnover matches the statement suggestions. This does not verify the source or the borrower’s income."}</p>
        {evidence.changed.length ? <ul className="mt-2 space-y-1 text-xs text-amber-900">{evidence.changed.map(name => <li key={name}>{FIELD_GROUPS.flatMap(group => group.fields).find(field => field.name === name).label} was edited.</li>)}</ul> : null}
        {review.statement.summary.warnings?.map(warning => <p key={warning} className="mt-2 text-xs font-medium text-amber-900">Statement warning: {warning}</p>)}
      </> : <p className="mt-2 text-sm leading-relaxed text-slate-600">Officer-entered figures. No statement is attached to this assessment; the figures have not been verified against a statement.</p>}
    </div>
    {FIELD_GROUPS.map(group => <section key={group.id} aria-label={`Review ${group.title}`}>
      <h4 className="mb-2 text-sm font-semibold text-slate-900">{group.title}</h4>
      <dl className="divide-y divide-slate-100 rounded-xl border border-slate-200 px-4">
        {group.fields.map(field => <div key={field.name} className="grid gap-1 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-start sm:gap-3">
          <dt className="text-xs text-slate-600">{field.label}{unusedFields.has(field.name) ? <span className="mt-1 block text-[11px] text-amber-800">Active in business checks; not in the ML score</span> : null}</dt>
          <dd className="break-words text-sm font-medium text-slate-900 tabular-nums" data-review-field={field.name}>{assessmentDisplay(field, review.payload[field.name])}</dd>
          <dd><button type="button" disabled={disabled} className="text-xs font-semibold text-brand-700 underline underline-offset-2" aria-label={`Edit ${field.label}`} onClick={() => onEdit(field.name)}>Edit</button></dd>
        </div>)}
      </dl>
    </section>)}
    <OperatingChecks values={review.payload} statement={review.statement} disabled={disabled} onFixField={onEdit} />
  </section>;
}
