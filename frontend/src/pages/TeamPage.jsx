import { useCallback, useEffect, useRef, useState } from "react";

import { canManageTeam, getStoredUsername } from "../api/auth.js";
import { apiErrorMessage, createUser, fetchUsers } from "../api/client.js";
import { ErrorState, LoadingState, Spinner } from "../components/common/States.jsx";
import { formatDate } from "../lib/format.js";
import TeamAccessDialog from '../components/TeamAccessDialog.jsx';
import { useUnsavedWork } from '../components/UnsavedWork.jsx';
import { filterTeam, roleLabel, TEAM_ROLES as ROLES } from '../lib/teamAccess.js';

const EMPTY = { username: "", password: "", role: "analyst" };

/**
 * Officer accounts and the three-level role hierarchy. Only an admin sees the
 * list and the form; the API enforces the same rule (403 otherwise).
 */
export default function TeamPage() {
  const isAdmin = canManageTeam();
  const [users, setUsers] = useState([]);
  const [isLoading, setIsLoading] = useState(isAdmin);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [submitError, setSubmitError] = useState(null);
  const [created, setCreated] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const creating = useRef(false);
  const [, setAccountRevision] = useState(0);
  const [filters, setFilters] = useState({search:'',role:'all',status:'all'});
  const [candidate, setCandidate] = useState(null), [saved, setSaved] = useState(null);
  const accountHeading = useRef(null);
  useEffect(() => {if(saved)accountHeading.current?.focus();},[saved]);
  useUnsavedWork({label:'New officer account',dirty:isAdmin && Boolean(form.username || form.password || form.role !== 'analyst'),busy:isSubmitting});
  useEffect(() => {
    const changed = () => setAccountRevision(value => value+1);
    window.addEventListener('foriflow:account-updated',changed);
    return () => window.removeEventListener('foriflow:account-updated',changed);
  },[]);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setIsLoading(true);
    setError(null);
    try {
      setUsers(await fetchUsers());
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the officer accounts."));
    } finally {
      setIsLoading(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  const me = getStoredUsername();
  const visibleUsers = filterTeam(users,filters);
  const enabledAdmins = users.filter(user=>user.role==='admin'&&user.is_active!==false).length;
  const openChange = (user,mode) => {setSaved(null);setCandidate({user,mode});};
  const accessSaved = (user,mode) => {
    setUsers(previous=>previous.map(item=>item.id===user.id?user:item));
    setCandidate(null);
    setSaved(`${user.username}: ${mode==='role'?`role changed to ${roleLabel(user.role)}`:user.is_active?'account re-enabled':'account disabled'}. Recorded in access history.`);
  };

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (creating.current) return;
    creating.current = true;
    setIsSubmitting(true);
    setSubmitError(null);
    setCreated(null);
    try {
      const user = await createUser(form);
      setCreated(user);
      setForm(EMPTY);
      await load();
    } catch (requestError) {
      setSubmitError(apiErrorMessage(requestError, "The account was not created."));
    } finally {
      creating.current = false;
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">Team and roles</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Three roles, each including everything below it. The role is read from the
          database on every request. Review a change before saving; its reason and history stay on file.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-3">
        {ROLES.map((role) => (
          <div key={role.value} className="card px-5 py-4">
            <p className="text-sm font-semibold text-slate-900">{role.label}</p>
            <p className="mt-1 text-sm text-slate-600">{role.can}</p>
          </div>
        ))}
      </section>

      {!isAdmin ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Only an enabled admin can see or manage officer accounts. Ask your admin for access changes.
        </p>
      ) : (
        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="card min-w-0 h-fit" data-testid="team-accounts">
            <div className="card-header">
              <h3 ref={accountHeading} tabIndex={-1} className="card-title outline-none">Officer accounts</h3>
              <button type="button" className="btn-secondary text-xs" disabled={isLoading} onClick={load}>Refresh accounts</button>
            </div>
            {saved ? <p role="status" className="mx-5 mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900">{saved}</p> : null}
            {isLoading ? (
              <LoadingState label="Loading accounts…" />
            ) : error ? (
              <ErrorState message={error} onRetry={load} />
            ) : (
              <div>
                <div className="space-y-3 border-b border-slate-200 px-5 py-4">
                  <p className="text-xs text-slate-500">{visibleUsers.length} of {users.length} accounts · {enabledAdmins} enabled admin{enabledAdmins===1?'':'s'}</p>
                  {enabledAdmins===1 ? <p className="text-xs text-amber-900">One enabled admin remains. Your own role and status are protected; another enabled admin is needed to change them.</p> : null}
                  <div><label className="field-label" htmlFor="team-search">Find an officer</label><input id="team-search" type="search" className="field-input" value={filters.search} onChange={event=>setFilters({...filters,search:event.target.value})} placeholder="Search username"/></div>
                  <div className="grid gap-3 sm:grid-cols-2"><div><label className="field-label" htmlFor="team-filter-role">Filter role</label><select id="team-filter-role" className="field-input" value={filters.role} onChange={event=>setFilters({...filters,role:event.target.value})}><option value="all">All roles</option>{ROLES.map(role=><option key={role.value} value={role.value}>{role.label}</option>)}</select></div><div><label className="field-label" htmlFor="team-filter-status">Filter status</label><select id="team-filter-status" className="field-input" value={filters.status} onChange={event=>setFilters({...filters,status:event.target.value})}><option value="all">All statuses</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></div></div>
                  {filters.search||filters.role!=='all'||filters.status!=='all' ? <button type="button" className="btn-ghost text-xs" onClick={()=>setFilters({search:'',role:'all',status:'all'})}>Clear filters</button> : null}
                </div>
                <ul className="divide-y divide-slate-100" aria-label="Officer accounts">
                    {visibleUsers.map((user) => {
                      const active = user.is_active !== false;
                      const isMe = user.username === me;
                      return (
                        <li key={user.id} className="space-y-3 px-5 py-4" data-testid={`team-account-${user.id}`}>
                          <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="break-all font-semibold text-slate-900">{user.username}{isMe?' · You':''}</p><p className="mt-1 text-xs text-slate-500">{roleLabel(user.role)} · Created {formatDate(user.created_at)}</p></div>
                            <span
                              className={`badge ${
                                active
                                  ? "bg-emerald-50 text-emerald-700"
                                  : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {active ? "Enabled" : "Disabled"}
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-2"><button type="button" className="btn-secondary text-xs" disabled={isMe} onClick={()=>openChange(user,'role')} aria-label={`Change role for ${user.username}`}>Change role</button><button type="button" className="btn-secondary text-xs" disabled={isMe} onClick={()=>openChange(user,'status')} aria-label={`${active?'Disable':'Re-enable'} ${user.username}`}>{active?'Disable':'Re-enable'}</button><button type="button" className="btn-ghost text-xs" onClick={()=>openChange(user,'history')} aria-label={`Access history for ${user.username}`}>Access history</button></div>
                          {isMe ? <p className="text-xs text-slate-500">Ask another enabled admin to change your role or status.</p> : null}
                        </li>
                      );
                    })}
                </ul>
                {!visibleUsers.length ? <p className="px-5 py-6 text-sm text-slate-600">No officers match these filters. Try another username or clear the filters.</p> : null}
              </div>
            )}
          </div>

          <form onSubmit={handleSubmit} className="card h-fit">
            <div className="card-header">
              <h3 className="card-title">New officer account</h3>
            </div>
            <div className="space-y-4 px-5 py-5">
              <div>
                <label className="field-label" htmlFor="team-username">
                  Username
                </label>
                <input
                  id="team-username"
                  name="username"
                  value={form.username}
                  onChange={handleChange}
                  required
                  minLength={3}
                  maxLength={64}
                  pattern="[A-Za-z0-9_.\-]+"
                  autoComplete="off"
                  className="field-input"
                />
              </div>
              <div>
                <label className="field-label" htmlFor="team-password">
                  Password
                </label>
                <input
                  id="team-password"
                  name="password"
                  type="password"
                  value={form.password}
                  onChange={handleChange}
                  required
                  minLength={12}
                  maxLength={72}
                  autoComplete="new-password"
                  className="field-input"
                />
                <p className="mt-1 text-xs text-slate-500">
                  12 to 72 characters. A passphrase works well. Common passwords,
                  sequences and the username are refused.
                </p>
              </div>
              <div>
                <label className="field-label" htmlFor="team-role">
                  Role
                </label>
                <select
                  id="team-role"
                  name="role"
                  value={form.role}
                  onChange={handleChange}
                  className="field-input"
                >
                  {ROLES.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </div>

              {submitError ? (
                <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  {submitError}
                </p>
              ) : null}
              {created ? (
                <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                  Created {created.role} account {created.username}.
                </p>
              ) : null}

              <button type="submit" disabled={isSubmitting} className="btn-primary w-full">
                {isSubmitting ? <Spinner className="h-4 w-4 text-white" /> : null}
                Create account
              </button>
            </div>
          </form>
        </section>
      )}
      {candidate ? <TeamAccessDialog candidate={candidate} onClose={()=>setCandidate(null)} onSaved={accessSaved}/> : null}
    </div>
  );
}
