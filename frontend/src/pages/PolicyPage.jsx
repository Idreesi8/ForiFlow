import { useCallback, useEffect, useState } from "react";

import { canManageTeam } from "../api/auth.js";
import {
  activatePolicyVersion,
  apiErrorMessage,
  createPolicyVersion,
  fetchPolicyVersions,
} from "../api/client.js";
import { ErrorState, LoadingState, Spinner } from "../components/common/States.jsx";
import { formatCount, formatDateTime, formatPKR } from "../lib/format.js";
import { refreshActivePolicy } from "../lib/useActivePolicy.js";

const EMPTY = {
  version: "",
  name: "",
  decline_max_score: "40",
  manual_review_max_score: "70",
  manager_approval_limit_pkr: "2000000",
  decline_override_admin_only: true,
};

const STATUS_TONE = {
  active: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
  draft: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
  retired: "bg-white text-slate-500 ring-1 ring-slate-300",
};

/**
 * The credit policy: the cut-offs that turn a score into a recommendation and
 * the limits on who may approve. Everyone can read it; only an admin can add a
 * version or activate one. A version is never edited or deleted.
 */
export default function PolicyPage() {
  const isAdmin = canManageTeam();
  const [versions, setVersions] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setVersions(await fetchPolicyVersions());
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the credit policy."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (key, action) => {
    setBusy(key);
    setActionError(null);
    try {
      await action();
      await load();
    } catch (requestError) {
      setActionError(apiErrorMessage(requestError, "The policy was not changed."));
    } finally {
      setBusy(null);
    }
  };

  const create = (event) => {
    event.preventDefault();
    run("create", async () => {
      await createPolicyVersion({
        version: form.version.trim(),
        name: form.name.trim(),
        decline_max_score: Number(form.decline_max_score),
        manual_review_max_score: Number(form.manual_review_max_score),
        manager_approval_limit_pkr: Number(form.manager_approval_limit_pkr),
        decline_override_admin_only: form.decline_override_admin_only,
      });
      setForm(EMPTY);
    });
  };

  if (isLoading) return <LoadingState label="Loading credit policy…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const active = versions.find((version) => version.is_active);

  return (
    <div className="min-w-0 space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Credit policy</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          The model gives a risk score. The policy turns that score into a recommendation
          and sets who may approve. An officer makes the decision. A policy version is
          never edited: a change is a new version, and each application keeps the version
          it was assessed under.
        </p>
      </div>

      {active ? (
        <section className="card px-5 py-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="card-title">
              In force: {active.name} v{active.version}
            </h3>
            <span className={`badge ${STATUS_TONE.active}`}>active</span>
          </div>
          <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
            <Figure label="Recommend Decline" value={`score ${active.decline_max_score} or below`} />
            <Figure
              label="Recommend Manual Review"
              value={`above ${active.decline_max_score}, up to ${active.manual_review_max_score}`}
            />
            <Figure label="Recommend Approve" value={`above ${active.approve_above_score}`} />
            <Figure
              label="Manager approval limit"
              value={formatPKR(active.manager_approval_limit_pkr)}
            />
          </dl>
          <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            {active.notice}
          </p>
        </section>
      ) : null}

      <section className="card min-w-0">
        <div className="card-header">
          <h3 className="card-title">Versions</h3>
          <span className="text-xs text-slate-500">none is ever deleted</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-[11px] tracking-wide text-slate-500 uppercase">
                <th className="px-5 py-2 font-medium">Version</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 text-right font-medium">Decline ≤</th>
                <th className="px-3 py-2 text-right font-medium">Review ≤</th>
                <th className="px-3 py-2 text-right font-medium">Manager limit</th>
                <th className="px-3 py-2 text-right font-medium">Assessed</th>
                <th className="px-3 py-2 font-medium">Created</th>
                <th className="px-5 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {versions.map((version) => (
                <tr key={version.id}>
                  <td className="px-5 py-3">
                    <span className="font-semibold text-slate-900">v{version.version}</span>
                    <span className="block text-xs text-slate-500">{version.name}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`badge ${STATUS_TONE[version.status] ?? STATUS_TONE.draft}`}>
                      {version.status}
                    </span>
                  </td>
                  <td className="tabular px-3 py-3 text-right">{version.decline_max_score}</td>
                  <td className="tabular px-3 py-3 text-right">{version.manual_review_max_score}</td>
                  <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                    {formatPKR(version.manager_approval_limit_pkr)}
                  </td>
                  <td className="tabular px-3 py-3 text-right">
                    {formatCount(version.applications_assessed)}
                  </td>
                  <td className="px-3 py-3 text-xs whitespace-nowrap text-slate-600">
                    {formatDateTime(version.created_at)} · {version.created_by}
                  </td>
                  <td className="px-5 py-3 text-right">
                    {isAdmin && !version.is_active ? (
                      <button
                        type="button"
                        className="btn border border-slate-300 bg-white text-slate-800 hover:bg-slate-50"
                        disabled={busy !== null}
                        onClick={() =>
                          run(`activate-${version.id}`, async () => {
                            await activatePolicyVersion(version.id);
                            refreshActivePolicy();
                          })
                        }
                      >
                        {busy === `activate-${version.id}` ? <Spinner className="h-4 w-4" /> : null}
                        Activate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {actionError ? (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800" role="alert">
          {actionError}
        </p>
      ) : null}

      {isAdmin ? (
        <section className="card px-5 py-5">
          <h3 className="card-title">New version</h3>
          <p className="mt-1 text-xs text-slate-500">
            Saved as a draft. It changes nothing until you activate it, and only for
            assessments made after that.
          </p>
          <form onSubmit={create} className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <Input label="Version" value={form.version} placeholder="e.g. 1.1" required
              onChange={(value) => setForm({ ...form, version: value })} />
            <Input label="Name" value={form.name} placeholder="e.g. Pilot Credit Policy" required
              onChange={(value) => setForm({ ...form, name: value })} />
            <Input label="Manager approval limit (PKR)" type="number" min="0" required
              value={form.manager_approval_limit_pkr}
              onChange={(value) => setForm({ ...form, manager_approval_limit_pkr: value })} />
            <Input label="Recommend Decline at or below" type="number" min="0" max="99" step="0.01"
              required value={form.decline_max_score}
              onChange={(value) => setForm({ ...form, decline_max_score: value })} />
            <Input label="Recommend Manual Review up to" type="number" min="1" max="100" step="0.01"
              required value={form.manual_review_max_score}
              onChange={(value) => setForm({ ...form, manual_review_max_score: value })} />
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.decline_override_admin_only}
                onChange={(event) =>
                  setForm({ ...form, decline_override_admin_only: event.target.checked })
                }
              />
              Only an admin may approve against a Decline recommendation
            </label>
            <div className="sm:col-span-2 xl:col-span-3">
              <button type="submit" className="btn-primary" disabled={busy !== null}>
                {busy === "create" ? <Spinner className="h-4 w-4 text-white" /> : null}
                Save draft
              </button>
            </div>
          </form>
        </section>
      ) : (
        <p className="text-sm text-slate-500">Only an admin can add or activate a policy version.</p>
      )}
    </div>
  );
}

function Figure({ label, value }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</dt>
      <dd className="mt-1 font-semibold text-slate-900">{value}</dd>
    </div>
  );
}

function Input({ label, onChange, ...props }) {
  return (
    <label className="block min-w-0">
      <span className="field-label">{label}</span>
      <input className="field-input" onChange={(event) => onChange(event.target.value)} {...props} />
    </label>
  );
}
