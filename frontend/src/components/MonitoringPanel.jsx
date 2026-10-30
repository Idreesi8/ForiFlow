import { useEffect, useRef, useState } from "react";

import { canDecideCredit } from "../api/auth.js";
import {
  apiErrorMessage,
  correctObservation,
  fetchApplicationRegister,
  fetchApplication,
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
import { businessDate, formatPKR } from "../lib/format.js";
import { useBusinessDate } from "../hooks/useBusinessDate.js";
import { monitoringCoverage, monitoringFormDirty, observationForm } from "../lib/monitoringCoverage.js";
import MonitoringCalendar, { RecordedMonth } from "./MonitoringCalendar.jsx";
import { EwsStateBadge } from "./common/Badges.jsx";
import { ErrorState, Spinner } from "./common/States.jsx";
import { useUnsavedWork } from "./UnsavedWork.jsx";

const INSTALLMENT_STATUSES = ["On Time", "Late 1-29", "Late 30-59", "Late 60-89", "Default"];
const DATA_SOURCES = ["ECIB", "POS", "Bank Statement", "Self Reported"];
const REASON_MIN = 10;

const initialForm = () => ({
  borrower_id: "",
  month_number: "1",
  observation_date: businessDate(),
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
export default function MonitoringPanel({ onMonitored, facilityId = null, initialMonth = null,
  refreshToken = 0, onFacilityChange, onDirtyChange, onBusyChange, onReady }) {
  const today = useBusinessDate();
  const baseline = useRef(initialForm());
  const [borrowers, setBorrowers] = useState([]);
  const [form, setForm] = useState(baseline.current);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(null);
  const [correctionReason, setCorrectionReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [coverage, setCoverage] = useState({ facilityId: null, state: 'waiting', data: null, error: null });
  const [historyRevision, setHistoryRevision] = useState(0);
  const [borrowerRevision, setBorrowerRevision] = useState(0);
  const [borrowerError, setBorrowerError] = useState(null);
  const [borrowersLoading, setBorrowersLoading] = useState(true);
  const [facilitySearch, setFacilitySearch] = useState('');
  const [facilityPage, setFacilityPage] = useState(0);
  const [facilityChoices, setFacilityChoices] = useState(null);
  const choiceKey = JSON.stringify([facilityId, facilitySearch.trim(), facilityPage]);
  const choicesReady = facilityChoices?.key === choiceKey && !borrowersLoading && !borrowerError;
  const [pendingMonth, setPendingMonth] = useState(null);
  const preferred = useRef(null);
  const lastLink = useRef('');
  const formRef = useRef(form);
  const editorElement = useRef(null);
  formRef.current = form;
  const canManage = canDecideCredit();
  const dirty = monitoringFormDirty(form, baseline.current) || Boolean(conflict) || Boolean(correctionReason);
  useUnsavedWork({ label: `Monitoring month ${form.month_number} for case #${form.borrower_id || '—'}`, dirty, busy: isSubmitting });
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => { onBusyChange?.(isSubmitting); }, [isSubmitting, onBusyChange]);

  const resetSelection = (id, month) => {
    baseline.current = initialForm();
    preferred.current = { id: String(id), month };
    setForm({ ...baseline.current, borrower_id: String(id), month_number: String(month ?? 1) });
    setConflict(null);
    setCorrectionReason('');
    setPendingMonth(null);
    setError(null);
    setResult(null);
  };

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setBorrowersLoading(true);
    setBorrowerError(null);
    fetchApplicationRegister({ status: DECISION_APPROVED, search: facilitySearch.trim(),
      limit: 25, offset: facilityPage * 25 }, { signal: controller.signal })
      .then(async (register) => {
        if (cancelled) return;
        if (facilityPage > 0 && facilityPage * 25 >= register.matching) {
          setFacilityPage(Math.max(0, Math.ceil(register.matching / 25) - 1));
          return;
        }
        let data = register.items;
        // Keep the selected facility available while searching other pages.
        const selectedId = facilityId || Number(formRef.current.borrower_id);
        if (selectedId && !data.some(item => item.id === selectedId)) {
          const focused = await fetchApplication(selectedId, { signal: controller.signal });
          data = [...data, focused];
        }
        if (cancelled) return;
        // Only an approved application became a facility; the API answers 409 otherwise.
        const monitorable = data.filter(
          (application) => finalDecisionOf(application) === DECISION_APPROVED,
        );
        setBorrowers(monitorable);
        setFacilityChoices({ key: choiceKey, matching: register.matching, count: register.items.length,
          pinned: Boolean(selectedId && !register.items.some(item => item.id === selectedId)) });
        if (!facilityId && monitorable.length && !formRef.current.borrower_id) {
          if (onFacilityChange) onFacilityChange(monitorable[0].id);
          else resetSelection(monitorable[0].id, null);
        }
      })
      .catch(failure => { if (!cancelled) setBorrowerError(apiErrorMessage(failure, 'Could not load approved facilities.')); })
      .finally(() => { if (!cancelled) setBorrowersLoading(false); });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [facilityId, borrowerRevision, facilitySearch, facilityPage, choiceKey]);

  useEffect(() => {
    if (!facilityId) return;
    const link = `${facilityId}:${initialMonth ?? ''}`;
    if (lastLink.current === link) return;
    lastLink.current = link;
    if (formRef.current.borrower_id !== String(facilityId)) resetSelection(facilityId, initialMonth);
    else if (initialMonth && Number(formRef.current.month_number) !== initialMonth) requestMonth(initialMonth);
  }, [facilityId, initialMonth]);

  const selectedBorrower =
    borrowers.find((borrower) => String(borrower.id) === String(form.borrower_id)) ?? null;

  useEffect(() => {
    if (borrowersLoading || (facilityId && Number(form.borrower_id) !== facilityId)) return;
    if (!borrowerError && selectedBorrower && (coverage.facilityId !== form.borrower_id ||
      !['ready', 'error'].includes(coverage.state))) return;
    onReady?.(facilityId || Number(form.borrower_id) || null);
  }, [borrowersLoading, borrowerError, facilityId, form.borrower_id,
    selectedBorrower?.id, coverage.facilityId, coverage.state, onReady]);

  useEffect(() => {
    const id = form.borrower_id;
    if (!id || !selectedBorrower) {
      setCoverage({ facilityId: id, state: 'waiting', data: null, error: null });
      return;
    }
    const controller = new AbortController();
    setCoverage({ facilityId: id, state: 'loading', data: null, error: null });
    fetchFacilityObservations(Number(id), {}, { signal: controller.signal })
      .then(rows => {
        if (controller.signal.aborted) return;
        const data = monitoringCoverage(rows, selectedBorrower.tenure_months, Number(id));
        setCoverage({ facilityId: id, state: 'ready', data, error: null });
        if (formRef.current.borrower_id === id && !dirtyRef.current) {
          const requested = preferred.current?.id === id ? preferred.current.month : null;
          const valid = Number.isInteger(requested) && requested >= 1 && requested <= selectedBorrower.tenure_months;
          if (requested && !valid) setError('The linked month is outside this facility term. Choose a valid reporting month.');
          setForm(previous => ({ ...previous, month_number: String(valid ? requested : data.nextMonth ?? 1) }));
        }
      })
      .catch(failure => { if (!controller.signal.aborted) setCoverage({ facilityId: id, state: 'error', data: null,
        error: failure.response || failure.code ? apiErrorMessage(failure, 'Could not load monitoring history.') : failure.message }); }) ;
    return () => controller.abort();
  }, [form.borrower_id, selectedBorrower?.tenure_months, historyRevision, refreshToken]);

  const historyReady = coverage.state === 'ready' && coverage.facilityId === form.borrower_id;
  const selectedMonth = historyReady ? coverage.data.months.find(month => month.number === Number(form.month_number)) : null;
  const selectedRecord = selectedMonth?.record ?? null;
  const editingCorrection = Boolean(conflict && selectedRecord && conflict.id === selectedRecord.id);

  function requestMonth(month) {
    if (isSubmitting || month === Number(formRef.current.month_number)) return;
    if (!Number.isInteger(month) || month < 1 || month > (selectedBorrower?.tenure_months ?? 84)) return;
    if (dirtyRef.current) setPendingMonth(month);
    else resetSelection(formRef.current.borrower_id, month);
  }

  const prepareCorrection = () => {
    if (!canManage || !historyReady || !selectedRecord || isSubmitting) return;
    setForm({ ...initialForm(), ...observationForm(selectedRecord) });
    setConflict(selectedRecord);
    setCorrectionReason('');
    setError(null);
  };

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    if (name === 'borrower_id') {
      if (onFacilityChange) onFacilityChange(Number(value));
      else resetSelection(value, null);
      return;
    }
    if (name === 'month_number') { requestMonth(Number(value)); return; }
    setForm((previous) => ({ ...previous, [name]: type === "checkbox" ? checked : value }));
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

  const finish = (response, corrected = false) => {
    setResult(response);
    baseline.current = initialForm();
    preferred.current = { id: String(response.borrower_id), month: corrected ? response.month_number : null };
    setForm({ ...baseline.current, borrower_id: String(response.borrower_id), month_number: String(response.month_number) });
    setConflict(null);
    setCorrectionReason("");
    setHistoryRevision(value => value + 1);
    onMonitored?.(response);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!historyReady || !selectedMonth || selectedRecord || isSubmitting) {
      setError(selectedRecord ? 'This month is already recorded. Use Prepare correction to amend it.' : 'Verify the monitoring history before recording a month.');
      return;
    }
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
      setError(requestError.response ? apiErrorMessage(requestError, "The month could not be recorded.") : 'The save could not be confirmed. Check the refreshed history before retrying.');
      if (!requestError.response || requestError.response.status === 409) {
        // Another officer may have saved it since this snapshot. Keep the typed
        // figures, refresh history, then require an explicit correction action.
        setHistoryRevision(value => value + 1);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCorrection = async () => {
    if (!canManage || !historyReady || !editingCorrection || isSubmitting || correctionReason.trim().length < REASON_MIN) return;
    if (!editorElement.current?.reportValidity()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      finish(
        await correctObservation(conflict.id, {
          ...figures(),
          correction_reason: correctionReason.trim(),
        }), true,
      );
    } catch (requestError) {
      setError(requestError.response ? apiErrorMessage(requestError, "The correction was not saved.") : 'The save could not be confirmed. Check the refreshed history before retrying.');
      if (!requestError.response || requestError.response.status === 409) setHistoryRevision(value => value + 1);
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

      {borrowerError ? <ErrorState message={borrowerError} onRetry={() => setBorrowerRevision(value => value + 1)} /> : null}
      {error ? <p role="alert" className="px-5 py-3 text-sm font-medium text-rose-700">{error}</p> : null}
      {coverage.state === 'error' && coverage.facilityId === form.borrower_id ? <ErrorState message={coverage.error} onRetry={() => setHistoryRevision(value => value + 1)} /> : null}
      {form.borrower_id && !historyReady && coverage.state !== 'error' ? <p role="status" className="px-5 py-4 text-sm text-slate-500">Verifying this facility’s monitoring history…</p> : null}
      {historyReady ? <MonitoringCalendar coverage={coverage.data} selectedMonth={form.month_number}
        onSelect={requestMonth} disabled={isSubmitting} onRefresh={() => setHistoryRevision(value => value + 1)} /> : null}
      {selectedRecord ? <RecordedMonth month={selectedMonth} canManage={canManage} editing={editingCorrection}
        disabled={isSubmitting} onPrepare={prepareCorrection} /> : null}
      {pendingMonth ? <div role="alert" className="border-b border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-950" data-testid="unsaved-month">
        <p>Month {form.month_number} has unsubmitted figures. Switching to month {pendingMonth} clears this form; nothing has been saved.</p>
        <div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary" onClick={() => setPendingMonth(null)}>Keep editing this month</button><button type="button" className="btn-primary" onClick={() => resetSelection(form.borrower_id, pendingMonth)}>Switch month and clear figures</button></div>
      </div> : null}

      <div className="border-b border-slate-200 px-5 py-3">
        <label className="field-label" htmlFor="monitoring-facility-search">Find an approved facility</label>
        <input id="monitoring-facility-search" type="search" maxLength={120} className="field-input"
          value={facilitySearch} disabled={isSubmitting}
          onChange={event => { setFacilitySearch(event.target.value); setFacilityPage(0); }}
          placeholder="Search every approved case by business, applicant or case #" />
        {choicesReady ? <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <p role="status">{facilityChoices.matching ? `${facilityPage * 25 + 1}–${facilityPage * 25 + facilityChoices.count} of ${facilityChoices.matching} matching facilities` : 'No approved facilities match this search.'}
            {facilityChoices.pinned ? ' Your selected facility remains available below.' : ''}</p>
          <nav aria-label="Approved facility pages" className="flex gap-2">
            <button type="button" className="btn-secondary" disabled={isSubmitting || facilityPage === 0} onClick={() => setFacilityPage(value => value - 1)}>Previous facilities</button>
            <button type="button" className="btn-secondary" disabled={isSubmitting || (facilityPage + 1) * 25 >= facilityChoices.matching} onClick={() => setFacilityPage(value => value + 1)}>Next facilities</button>
          </nav>
        </div> : !borrowerError ? <p role="status" className="mt-2 text-xs text-slate-500">Searching approved facilities…</p> : null}
      </div>
      <form ref={editorElement} onSubmit={handleSubmit} className="grid gap-4 px-5 py-5 md:grid-cols-3">
        <div className="md:col-span-1">
          <label className="field-label" htmlFor="borrower_id">
            Facility
          </label>
          <select
            id="borrower_id"
            name="borrower_id"
            value={form.borrower_id}
            onChange={handleChange}
            disabled={isSubmitting || !choicesReady}
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
          {borrowers.length === 0 && choicesReady && !facilitySearch.trim() ? (
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
          <select
            id="month_number"
            name="month_number"
            value={form.month_number}
            onChange={handleChange}
            disabled={!historyReady || isSubmitting}
            required
            className="field-input"
          >
            {Array.from({ length: selectedBorrower?.tenure_months ?? 1 }, (_, index) => <option key={index + 1} value={index + 1}>Month {index + 1}</option>)}
          </select>
        </div>

        {(!selectedRecord || editingCorrection) ? <fieldset disabled={!historyReady || isSubmitting} className="grid min-w-0 gap-4 border-0 p-0 md:col-span-3 md:grid-cols-3">
        <div>
          <label className="field-label" htmlFor="observation_date">
            Observation date
          </label>
          <input
            id="observation_date"
            name="observation_date"
            type="date"
            max={today}
            aria-describedby="observation-date-help"
            value={form.observation_date}
            onChange={handleChange}
            className="field-input"
          />
          <p id="observation-date-help" className="mt-1 text-xs text-slate-500">Pakistan calendar date (PKT). Today: {today}.</p>
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
            <p className="text-xs text-slate-500">
              The EWS assesses the facility's recorded history and opens or updates its alert.
              The thresholds are listed under Methodology on this page.
            </p>
          <button type="submit" className="btn-primary" disabled={isSubmitting || overrideIncomplete || !historyReady || Boolean(selectedRecord)}>
            {isSubmitting ? (
              <>
                <Spinner className="h-4 w-4 text-white" />
                Saving…
              </>
            ) : (
              editingCorrection ? "Use the correction action below" : "Record month"
            )}
          </button>
        </div>
        </fieldset> : null}
      </form>

      {editingCorrection ? (
        <div className="border-t border-amber-200 bg-amber-50 px-5 py-4 text-sm" data-testid="correction-offer">
          <p className="font-semibold text-amber-900">
            Month {conflict.month_number} is already recorded (observation #{conflict.id}, score{" "}
            {conflict.monthly_score.toFixed(1)}, {conflict.installment_status}).
          </p>
          {canManage ? (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <label className="min-w-0 flex-1 basis-64 text-xs text-slate-700">
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
                disabled={isSubmitting || !historyReady || correctionReason.trim().length < REASON_MIN || overrideIncomplete}
                className="btn-primary py-1.5 text-xs"
              >
                Save as a correction of month {conflict.month_number}
              </button>
              <button type="button" className="btn-secondary text-xs" disabled={isSubmitting} onClick={() => resetSelection(form.borrower_id, Number(form.month_number))}>Cancel correction</button>
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
