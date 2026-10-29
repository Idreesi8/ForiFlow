import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiErrorMessage, fetchActionDesk } from "../api/client.js";
import { deskPath, deskQuery, PRIORITIES, ROLE_LABELS, taskPath } from "../lib/actionDesk.js";

export default function ActionDeskPreview() {
  const [actionableOnly, setActionableOnly] = useState(true);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const key = `${actionableOnly}:${revision}`;
  useEffect(() => {
    const controller = new AbortController();
    fetchActionDesk({ limit: 3, actionable_only: actionableOnly || undefined }, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setResult({ key, data, error: null }); })
      .catch(error => { if (!controller.signal.aborted) setResult({ key, data: null, error: apiErrorMessage(error, "Could not load next actions.") }); });
    return () => controller.abort();
  }, [key]);
  const loading = result.key !== key;
  const snapshot = loading ? null : result.data;
  const error = loading ? null : result.error;
  const first = snapshot?.items[0];
  const returnState = { worklistSearch: deskQuery({ actionableOnly }) };

  return <section className="card" aria-label="Next actions" aria-busy={loading}>
    <div className="card-header flex-wrap gap-3">
      <div><h2 className="card-title">Next actions</h2><p role="status" className="mt-1 text-xs text-slate-500">{snapshot
        ? actionableOnly
          ? `${snapshot.actionable_tasks} tasks match your ${snapshot.officer_role} role · ${snapshot.total_tasks} in the complete portfolio`
          : `${snapshot.total_tasks} tasks across ${snapshot.application_count} cases · all roles`
        : error ? "Task preview unavailable." : "Checking recorded officer tasks…"}</p></div>
      <Link className="text-sm font-semibold text-brand-700 hover:underline" to={deskPath({ actionableOnly })}>Open action desk →</Link>
    </div>
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
      <div role="group" aria-label="Task preview scope" className="flex gap-2">
        {[[true, "Your role"], [false, "All roles"]].map(([value, label]) => <button key={label} type="button" aria-pressed={actionableOnly === value} onClick={() => setActionableOnly(value)}
          className={`min-h-9 rounded-lg border px-3 py-1.5 text-xs font-semibold ${actionableOnly === value ? "border-brand-600 bg-brand-50 text-brand-900" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>{label}</button>)}
      </div>
      <button type="button" className="btn-ghost min-h-9 text-xs" onClick={() => setRevision(value => value + 1)}>Refresh next actions</button>
    </div>
    {loading ? <p className="px-5 py-5 text-sm text-slate-500">Finding the next tasks in this view…</p> : error ? <div className="px-5 py-5"><p role="alert" className="text-sm text-rose-800">{error}</p><button type="button" className="btn-secondary mt-3 text-xs" onClick={() => setRevision(value => value + 1)}>Retry next actions</button></div> : snapshot ? <>
      {snapshot.items.length ? <div className="divide-y divide-slate-100">{snapshot.items.map(item => <Link key={item.id} to={taskPath(item)} state={returnState}
        className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 hover:bg-slate-50"><div className="min-w-0 flex-1 basis-52"><p className="break-words text-sm font-semibold text-slate-900">{item.business_name}</p><p className="mt-1 text-xs font-medium text-slate-700">{item.title} · Case #{item.application_id}</p><p className="mt-1 text-xs text-slate-500">{ROLE_LABELS[item.required_role]}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${PRIORITIES[item.priority].style}`}>{PRIORITIES[item.priority].label}</span></Link>)}</div>
        : <div className="px-5 py-5"><p className="text-sm font-semibold text-slate-800">{actionableOnly && snapshot.total_tasks ? "No recorded tasks match your role" : "No tasks from the recorded workflow"}</p><p className="mt-2 text-xs text-slate-500">{actionableOnly && snapshot.total_tasks ? "Other roles have tasks. You can still open the full worklist to inspect them." : "This is based on saved records; it does not certify the portfolio’s health."}</p>{actionableOnly && snapshot.total_tasks ? <button type="button" className="btn-secondary mt-3 text-xs" onClick={() => setActionableOnly(false)}>Show tasks for all roles</button> : null}</div>}
      {first ? <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-4"><Link className="btn-primary text-sm" to={taskPath(first)} state={returnState}>Open next task →</Link><p className="max-w-lg text-xs text-slate-500">Ordered by recorded workflow priority. Role eligibility is not personal assignment; case-specific approval limits still apply.</p></div> : null}
    </> : null}
  </section>;
}
