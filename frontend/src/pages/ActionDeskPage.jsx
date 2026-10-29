import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiErrorMessage, fetchActionDesk } from "../api/client.js";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States.jsx";
import { briefingText, DESK_PAGE_SIZE, deskQuery, KINDS, PRIORITIES, readDeskQuery, ROLE_LABELS, snapshotLabel, taskPath, updateDeskQuery } from "../lib/actionDesk.js";
import { formatDate } from "../lib/format.js";

const PAGE_SIZE = DESK_PAGE_SIZE;

export default function ActionDeskPage() {
  const [params, setParams] = useSearchParams();
  const view = readDeskQuery(params);
  const { kind, priority, actionableOnly, search, page } = view;
  const offset = (page - 1) * PAGE_SIZE;
  const [draft, setDraft] = useState(search);
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const [copyStatus, setCopyStatus] = useState("");
  const requestKey = JSON.stringify([kind, priority, actionableOnly, search, page, refresh]);
  const returnState = { worklistSearch: deskQuery(view) };
  const update = (changes, replace = false) => setParams(current => updateDeskQuery(current, changes), { replace });

  useEffect(() => { setDraft(search); }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    setCopyStatus("");
    fetchActionDesk({ limit: PAGE_SIZE, offset, kind: kind || undefined, priority: priority || undefined, search: search || undefined, actionable_only: actionableOnly || undefined }, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        if (offset > 0 && offset >= data.matching_tasks) {
          update({ page: Math.max(1, Math.ceil(data.matching_tasks / PAGE_SIZE)) }, true);
          return;
        }
        setResult({ key: requestKey, data, error: null });
      })
      .catch(failure => { if (!controller.signal.aborted) setResult({ key: requestKey, data: null, error: apiErrorMessage(failure, "Could not load officer tasks.") }); });
    return () => controller.abort();
  }, [requestKey]);

  const loading = result.key !== requestKey;
  const snapshot = loading ? null : result.data;
  const error = loading ? null : result.error;
  const copy = async () => {
    try { await navigator.clipboard.writeText(briefingText(snapshot)); setCopyStatus("This page’s briefing copied."); }
    catch { setCopyStatus("Could not copy. You can select the task details on this page."); }
  };
  const ready = snapshot && !loading && !error;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-xs font-bold uppercase tracking-widest text-brand-700">Officer worklist</p>
          <h2 className="text-2xl font-bold text-slate-900">Action desk</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">Credit reviews, EWS follow-ups and incomplete monitoring records, with the evidence behind each task.</p>
        </div>
        <div className="flex flex-wrap gap-2 print:hidden">
          <button type="button" className="btn-secondary" onClick={() => setRefresh(value => value + 1)}>Refresh tasks</button>
          <button type="button" className="btn-secondary" disabled={!ready} onClick={copy}>Copy this briefing</button>
        </div>
      </header>

      <div role="status" className="text-sm text-brand-800">{copyStatus}</div>

      <form className="card flex flex-wrap items-end gap-3 px-5 py-4 print:hidden" onSubmit={event => { event.preventDefault(); update({ search: draft }); }}>
        <label className="min-w-0 flex-1 basis-52 text-xs font-semibold text-slate-600">Find a case or owner
          <input type="search" maxLength={100} className="field-input mt-1" value={draft} onChange={event => setDraft(event.target.value)} placeholder="Business, case number or assigned officer" />
        </label>
        <div className="text-xs font-semibold text-slate-600">
          <label htmlFor="desk-kind">Task type</label>
          <select id="desk-kind" className="field-input mt-1" value={kind} onChange={event => update({ kind: event.target.value })}><option value="">All tasks</option>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </div>
        <div className="text-xs font-semibold text-slate-600">
          <label htmlFor="desk-priority">Priority</label>
          <select id="desk-priority" className="field-input mt-1" value={priority} onChange={event => update({ priority: event.target.value })}><option value="">All priorities</option>{Object.entries(PRIORITIES).map(([value, item]) => <option key={value} value={value}>{item.label}</option>)}</select>
        </div>
        <button className="btn-primary" type="submit">Search</button>
        <label className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700">
          <input type="checkbox" className="h-4 w-4 accent-brand-700" checked={actionableOnly} onChange={event => update({ actionableOnly: event.target.checked })} />
          Tasks my role can act on
        </label>
        {(kind || priority || search || draft || actionableOnly) ? <button type="button" className="btn-secondary" onClick={() => { setDraft(""); setParams({}); }}>Clear filters</button> : null}
      </form>

      <p className="text-xs text-slate-500">Applied filters and page stay in this view when you refresh or return from a case.</p>

      {loading ? <LoadingState label="Checking recorded officer tasks…" /> : error ? <ErrorState message={error} onRetry={() => setRefresh(value => value + 1)} /> : snapshot ? <>
        <section className="overflow-hidden rounded-2xl bg-brand-900 text-white shadow-sm">
          <div className="grid gap-6 px-6 py-6 md:grid-cols-[minmax(0,1fr)_auto]">
            <div>
              <p className="text-sm text-brand-200">Complete portfolio · {snapshotLabel(snapshot.as_of)}</p>
              <h3 className="mt-2 text-2xl font-bold">{snapshot.total_tasks} tasks. {snapshot.application_count} cases.</h3>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-brand-100">Start with overdue actions and critical alerts, then work through reviews and gaps in the record. Every task opens the relevant case.</p>
            </div>
            <dl className="grid grid-cols-3 items-center gap-5 text-center">
              {Object.entries(PRIORITIES).map(([key, item]) => <div key={key}><dt className="text-xs text-brand-100">{item.label}</dt><dd className="mt-1 text-2xl font-bold tabular-nums">{snapshot.counts_by_priority[key]}</dd></div>)}
            </dl>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 border-t border-brand-800 bg-brand-950/30 px-6 py-3 text-xs text-brand-100">
            {Object.entries(KINDS).map(([key, label]) => <span key={key}>{label}: <strong className="text-white">{snapshot.counts_by_kind[key]}</strong></span>)}
            <span>Counts cover all tasks, including those outside this view.</span>
          </div>
        </section>

        <div className="space-y-2 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-950">
          {snapshot.officer_role ? <p><strong>{snapshot.actionable_tasks} tasks match your {snapshot.officer_role} role</strong> across the complete portfolio. {snapshot.actionable_only ? "The list is filtered to your role." : "The list includes all roles."} This is role eligibility, not personal assignment. Case-specific approval limits still apply.</p> : null}
          <p>A missing record is a reason to verify information. It does not prove a missed payment. This desk changes no decisions or records.</p>
        </div>

        <section aria-label="Officer task list" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-600">{snapshot.matching_tasks ? `${offset + 1}–${offset + snapshot.items.length} of ${snapshot.matching_tasks} matching tasks` : "No matching tasks"}</p>
            {snapshot.items[0] ? <Link className="text-sm font-semibold text-brand-700 hover:underline" to={taskPath(snapshot.items[0])} state={returnState}>Open next task in this view →</Link> : null}
          </div>
          {!snapshot.items.length ? <div className="card"><EmptyState title={snapshot.total_tasks ? "No tasks match these filters" : "No tasks from the recorded workflow"} description={snapshot.total_tasks ? "Try another task type, priority or search, or clear the role filter to see all recorded tasks." : "New pending assessments, open alerts and monitoring gaps will appear here. This does not certify the portfolio’s health."} /></div> : snapshot.items.map(item => <article key={item.id} className="card px-5 py-5" data-task-id={item.id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1 basis-64">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2.5 py-1 font-semibold ring-1 ${PRIORITIES[item.priority].style}`}>{PRIORITIES[item.priority].label}</span><span className="text-slate-500">{KINDS[item.kind]} · Case #{item.application_id}</span></div>
                <h3 className="break-words font-bold text-slate-900">{item.business_name}</h3>
                <p className="mt-1 text-sm font-semibold text-brand-800">{item.title}</p>
                <p className="mt-1 text-sm text-slate-600">{item.reason}</p>
              </div>
              <Link className="btn-primary shrink-0 print:hidden" to={taskPath(item)} state={returnState}>Open case →</Link>
            </div>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500"><span>{ROLE_LABELS[item.required_role]}</span>{item.due_date ? <span>Action deadline: {formatDate(item.due_date)}</span> : null}{item.assigned_to ? <span>Owner: {item.assigned_to}</span> : null}</div>
            <details className="mt-3 border-t border-slate-100 pt-3"><summary className="cursor-pointer text-xs font-semibold text-slate-700">Recorded evidence</summary><ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-600">{item.evidence.map(fact => <li key={fact}>{fact}</li>)}</ul></details>
          </article>)}
        </section>

        <nav aria-label="Task pages" className="flex items-center justify-between gap-3 print:hidden">
          <button type="button" className="btn-secondary" disabled={page === 1} onClick={() => update({ page: page - 1 })}>Previous</button>
          <span className="text-xs text-slate-500">Page {Math.floor(offset / PAGE_SIZE) + 1}</span>
          <button type="button" className="btn-secondary" disabled={offset + PAGE_SIZE >= snapshot.matching_tasks} onClick={() => update({ page: page + 1 })}>Next</button>
        </nav>
        <details className="card px-5 py-4"><summary className="cursor-pointer text-sm font-semibold text-slate-800">How tasks are ordered</summary><ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-slate-600">{snapshot.ordering.map(rule => <li key={rule}>{rule}</li>)}</ol><div className="mt-4 space-y-2 text-xs leading-relaxed text-slate-500">{snapshot.notes.map(note => <p key={note}>{note}</p>)}</div></details>
      </> : null}
    </div>
  );
}
