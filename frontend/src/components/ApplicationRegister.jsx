import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { apiErrorMessage, fetchApplicationRegister } from "../api/client.js";
import ApplicationTable from "./ApplicationTable.jsx";
import { EmptyState, ErrorState, LoadingState } from "./common/States.jsx";

const STATUSES = ['All', 'Awaiting decision', 'Pending', 'Escalated', 'Approved', 'Rejected', 'Superseded'];
const SORTS = { created_at: 'Assessment date', id: 'Case ID', applicant_name: 'Applicant name', business_name: 'Business name',
  loan_amount_pkr: 'Facility amount', tenure_months: 'Tenure', risk_score: 'Risk score', decision: 'Recommendation', final: 'Officer decision' };
const PAGE_SIZES = [10, 25, 50];

export default function ApplicationRegister() {
  const [params, setParams] = useSearchParams();
  const search = (params.get('search') ?? '').slice(0, 120);
  const status = STATUSES.includes(params.get('status')) ? params.get('status') : 'All';
  const sort = Object.hasOwn(SORTS, params.get('sort')) ? params.get('sort') : 'created_at';
  const direction = params.get('direction') === 'asc' ? 'asc' : 'desc';
  const limit = PAGE_SIZES.includes(Number(params.get('limit'))) ? Number(params.get('limit')) : 25;
  const rawPage = Number(params.get('page') ?? 1);
  const page = Number.isSafeInteger(rawPage) && rawPage >= 1 && rawPage <= 20_000_001 ? rawPage : 1;
  const offset = (page - 1) * limit;
  const [draft, setDraft] = useState(search);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const request = useMemo(() => ({ search: search.trim(), ...(status !== 'All' ? { status } : {}), sort, direction, limit, offset }),
    [search, status, sort, direction, limit, offset]);
  const key = JSON.stringify(request) + ':' + revision;
  const update = (changes, replace = false) => {
    setParams(current => {
      const next = new URLSearchParams(current);
      next.delete('page');
      for (const [name, value] of Object.entries(changes)) {
        if (value === '' || value == null || value === 'All') next.delete(name);
        else next.set(name, String(value));
      }
      return next;
    }, { replace });
  };
  useEffect(() => { setDraft(search); }, [search]);
  useEffect(() => {
    if (draft === search) return;
    const timer = setTimeout(() => update({ search: draft.trim() }, true), 300);
    return () => clearTimeout(timer);
  }, [draft, search]);
  useEffect(() => {
    const controller = new AbortController();
    fetchApplicationRegister(request, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return;
      if (data.matching > 0 && offset >= data.matching) {
        update({ page: Math.ceil(data.matching / limit) }, true);
        return;
      }
      setResult({ key, data, error: null });
    }).catch(error => {
      if (!controller.signal.aborted) setResult({ key, data: null, error: apiErrorMessage(error, 'Could not load the application register.') });
    });
    return () => controller.abort();
  }, [key]);
  const searching = draft.trim() !== search.trim();
  const ready = !searching && result.key === key;
  const snapshot = ready ? result.data : null;
  const clear = () => { setDraft(''); setParams({}); };

  return <div className="space-y-4" data-testid="application-register">
    <section className="card p-5" aria-label="Find an application">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-bold text-slate-900">Find the right case</h3><p className="mt-1 text-xs text-slate-500">Search every saved assessment, including older and superseded records.</p></div><button type="button" className="btn-secondary text-xs" onClick={() => setRevision(value => value + 1)}>Refresh register</button></div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="sm:col-span-2"><label htmlFor="register-search" className="field-label">Search all assessments</label><input id="register-search" className="field-input" type="search" autoComplete="off" maxLength={120} value={draft} onChange={event => setDraft(event.target.value)} placeholder="Applicant, business, case # or BRW reference" /><p className="mt-1.5 text-xs text-slate-500">Names and borrower references match text. A numeric case ID matches that exact case.</p></div>
        <div><label htmlFor="register-status" className="field-label">Officer decision</label><select id="register-status" className="field-input" value={status} onChange={event => update({ status: event.target.value })}>{STATUSES.map(value => <option key={value}>{value}</option>)}</select></div>
        <div><label htmlFor="register-size" className="field-label">Assessments per page</label><select id="register-size" className="field-input" value={limit} onChange={event => update({ limit: event.target.value })}>{PAGE_SIZES.map(value => <option key={value}>{value}</option>)}</select></div>
      </div>
      <div className="mt-4 flex flex-wrap items-end gap-3"><div className="min-w-40 flex-1 sm:flex-none"><label htmlFor="register-sort" className="field-label text-xs">Sort by</label><select id="register-sort" className="field-input text-xs" value={sort} onChange={event => update({ sort: event.target.value })}>{Object.entries(SORTS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><div><label htmlFor="register-direction" className="field-label text-xs">Order</label><select id="register-direction" className="field-input text-xs" value={direction} onChange={event => update({ direction: event.target.value })}><option value="desc">Descending</option><option value="asc">Ascending</option></select></div><button type="button" className="btn-ghost text-xs" onClick={clear}>Reset filters</button></div>
      <p className="mt-4 text-xs leading-relaxed text-slate-500">Awaiting decision includes Pending and Escalated cases. Model recommendations remain separate from officer decisions. Superseded assessments are retained history.</p>
    </section>
    <div aria-live="polite" aria-atomic="true" className="text-sm text-slate-600">{snapshot ? `${snapshot.matching} matching assessments · ${snapshot.total} saved in total` : !ready ? 'Searching the register…' : 'Register unavailable'}</div>
    {!ready ? <LoadingState label="Loading matching assessments…" /> : result.error ? <ErrorState message={result.error} onRetry={() => setRevision(value => value + 1)} /> : !snapshot.items.length ? <section className="card"><EmptyState title={snapshot.total ? 'No assessments match these filters' : 'No assessments on file yet'} description={snapshot.total ? 'Try another name, case ID or officer decision. You can also reset the filters.' : 'Start a new assessment to add the first case.'} action={snapshot.total ? <button type="button" className="btn-secondary" onClick={clear}>Show all assessments</button> : <Link className="btn-primary" to="/scoring">New assessment</Link>} /></section> : <>
      <ApplicationTable title="Application register" applications={snapshot.items} showFilters={false} mobileCards
        sort={{ key: sort, direction }} onSortChange={next => update({ sort: next.key, direction: next.direction })}
        summary={`${offset + 1}–${offset + snapshot.items.length} of ${snapshot.matching} matching assessments`} />
      <nav aria-label="Register pages" className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">Page {page} of {Math.ceil(snapshot.matching / limit)} · Sorted across all matching cases</p><div className="flex gap-2"><button type="button" className="btn-secondary text-xs" disabled={page <= 1} onClick={() => update({ page: page - 1 })}>Previous page</button><button type="button" className="btn-secondary text-xs" disabled={offset + snapshot.items.length >= snapshot.matching} onClick={() => update({ page: page + 1 })}>Next page</button></div></nav>
    </>}
  </div>;
}
