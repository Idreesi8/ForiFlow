import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiErrorMessage, fetchApplications } from "../api/client.js";
import ShapWaterfall from "../components/ShapWaterfall.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States.jsx";
import { bandForDecision } from "../lib/decisions.js";
import { formatDate, formatPKRCompact } from "../lib/format.js";

/** Explainability workspace: pick an application, read its SHAP attribution. */
export default function ShapReportsPage() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const [applications, setApplications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");

  const loadApplications = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setApplications(await fetchApplications({ limit: 200 }));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load applications."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApplications();
  }, [loadApplications]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    const sorted = [...applications].sort((a, b) => b.id - a.id);
    if (!term) return sorted;
    return sorted.filter(
      (application) =>
        String(application.id).includes(term) ||
        application.applicant_name.toLowerCase().includes(term) ||
        application.business_name.toLowerCase().includes(term),
    );
  }, [applications, search]);

  const selectedId = applicationId ? Number(applicationId) : null;

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">SHAP Reports</h2>
        <p className="mt-1 text-sm text-slate-500">
          Feature attributions are additive: the base value plus every contribution
          reconstructs the score, which is what makes the decision defensible under SBP
          adverse-action requirements.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="card h-fit">
          <div className="card-header">
            <h3 className="card-title">Select application</h3>
          </div>
          <div className="px-4 py-3">
            <label className="sr-only" htmlFor="shap-search">
              Search applications
            </label>
            <input
              id="shap-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search name, business or ID"
              className="field-input py-1.5"
            />
          </div>

          {isLoading ? (
            <LoadingState label="Loading…" />
          ) : error ? (
            <ErrorState message={error} onRetry={loadApplications} />
          ) : filtered.length === 0 ? (
            <EmptyState
              title="Nothing to explain yet"
              description="Score an application first."
            />
          ) : (
            <ul className="max-h-[560px] divide-y divide-slate-100 overflow-y-auto">
              {filtered.map((application) => {
                const band = bandForDecision(application.decision);
                const isSelected = application.id === selectedId;

                return (
                  <li key={application.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/shap/${application.id}`)}
                      className={`flex w-full items-start justify-between gap-3 px-4 py-3 text-left transition ${
                        isSelected ? "bg-brand-50" : "hover:bg-slate-50"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold text-slate-900">
                          {application.business_name}
                        </span>
                        <span className="block truncate text-xs text-slate-500">
                          #{application.id} · {application.applicant_name}
                        </span>
                        <span className="mt-0.5 block text-xs text-slate-400">
                          {formatPKRCompact(application.loan_amount_pkr)} ·{" "}
                          {formatDate(application.created_at)}
                        </span>
                      </span>
                      <span className={`tabular text-sm font-bold ${band.textClass}`}>
                        {application.risk_score.toFixed(1)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        <section className="card">
          <div className="card-header">
            <h3 className="card-title">Feature attribution</h3>
            {selectedId ? (
              <span className="text-xs text-slate-500">POST /explain/{selectedId}</span>
            ) : null}
          </div>
          <div className="px-5 py-5">
            {selectedId ? (
              <ShapWaterfall applicationId={selectedId} />
            ) : (
              <EmptyState
                title="Select an application"
                description="Choose an assessment on the left to see which factors drove its score."
              />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
