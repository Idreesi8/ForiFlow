import { useCallback, useEffect, useState } from "react";

import { canManageTeam, getStoredUsername } from "../api/auth.js";
import { apiErrorMessage, createUser, fetchUsers, setUserStatus } from "../api/client.js";
import { ErrorState, LoadingState, Spinner } from "../components/common/States.jsx";
import { formatDate } from "../lib/format.js";

const ROLES = [
  {
    value: "admin",
    label: "Admin",
    can: "Everything a manager can, plus approving above the manager limit or against a Decline recommendation, deciding escalated cases, setting the credit policy, reading the audit trail, and creating, disabling and re-enabling officer accounts.",
  },
  {
    value: "manager",
    label: "Manager",
    can: "Everything an analyst can, plus approving (up to the policy's manager limit), rejecting or escalating applications, and resolving alerts.",
  },
  {
    value: "analyst",
    label: "Analyst",
    can: "Scores applications, records monthly monitoring, takes alerts for review.",
  },
];

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
  const [statusError, setStatusError] = useState(null);
  const [changingId, setChangingId] = useState(null);

  const toggleStatus = async (user) => {
    const enable = !user.is_active;
    const verb = enable ? "Re-enable" : "Disable";
    const reason = window.prompt(
      `${verb} ${user.username}? ${
        enable ? "They can sign in again." : "They are signed out at once and cannot sign in."
      }\n\nReason (recorded in the audit trail, optional):`,
      "",
    );
    if (reason === null) return;
    setChangingId(user.id);
    setStatusError(null);
    try {
      await setUserStatus(user.id, enable, reason.trim());
      await load();
    } catch (requestError) {
      setStatusError(apiErrorMessage(requestError, `Could not ${verb.toLowerCase()} the account.`));
    } finally {
      setChangingId(null);
    }
  };

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((previous) => ({ ...previous, [name]: value }));
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
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
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">Team and roles</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          Three roles, each including everything below it. The role is read from the
          database on every request, so changing it takes effect at once.
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
          Only an admin can see or create officer accounts.
        </p>
      ) : (
        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="card min-w-0">
            <div className="card-header">
              <h3 className="card-title">Officer accounts</h3>
              <span className="text-xs text-slate-500">{users.length} accounts</span>
            </div>
            {isLoading ? (
              <LoadingState label="Loading accounts…" />
            ) : error ? (
              <ErrorState message={error} onRetry={load} />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                      <th className="px-5 py-3 font-medium">Username</th>
                      <th className="px-3 py-3 font-medium">Role</th>
                      <th className="px-3 py-3 font-medium">Status</th>
                      <th className="px-3 py-3 font-medium">Created</th>
                      <th className="px-5 py-3 font-medium">
                        <span className="sr-only">Action</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {users.map((user) => {
                      const active = user.is_active !== false;
                      const isMe = user.username === me;
                      return (
                        <tr key={user.id}>
                          <td className="px-5 py-3 font-medium text-slate-900">{user.username}</td>
                          <td className="px-3 py-3 capitalize">{user.role}</td>
                          <td className="px-3 py-3">
                            <span
                              className={`badge ${
                                active
                                  ? "bg-emerald-50 text-emerald-700"
                                  : "bg-slate-100 text-slate-600"
                              }`}
                            >
                              {active ? "Enabled" : "Disabled"}
                            </span>
                          </td>
                          <td className="px-3 py-3 text-slate-500">{formatDate(user.created_at)}</td>
                          <td className="px-5 py-3 text-right">
                            {isMe ? (
                              <span className="text-xs text-slate-400">You</span>
                            ) : (
                              <button
                                type="button"
                                className="btn-secondary px-2.5 py-1 text-xs"
                                disabled={changingId === user.id}
                                onClick={() => toggleStatus(user)}
                              >
                                {active ? "Disable" : "Re-enable"}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {statusError ? (
                  <p role="alert" className="mx-5 my-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                    {statusError}
                  </p>
                ) : null}
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
    </div>
  );
}
