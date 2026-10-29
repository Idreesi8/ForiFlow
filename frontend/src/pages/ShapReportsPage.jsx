import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { apiErrorMessage, fetchApplication, fetchApplications } from "../api/client.js";
import ReviewPanel from "../components/ReviewPanel.jsx";
import WorklistReturn from "../components/WorklistReturn.jsx";
import ShapWaterfall from "../components/ShapWaterfall.jsx";
import { EmptyState, ErrorState, LoadingState } from "../components/common/States.jsx";
import { bandForDecision } from "../lib/decisions.js";
import { formatDate, formatPKRCompact } from "../lib/format.js";
import { worklistReturnState } from "../lib/actionDesk.js";

/** Explainability workspace: pick an application, read its SHAP attribution. */
export default function ShapReportsPage() {
  const { applicationId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const returnState = worklistReturnState(location.state);
  const [applications, setApplications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [focused, setFocused] = useState(null);
  const selectedId = applicationId ? Number(applicationId) : null;

  useEffect(() => {
    if (!Number.isSafeInteger(selectedId) || selectedId < 1 || applications.some(item => item.id === selectedId)) {
      setFocused(null);
      return;
    }
    let cancelled = false;
    fetchApplication(selectedId).then(data => { if (!cancelled && data.id === selectedId) setFocused(data); }).catch(() => { if (!cancelled) setFocused(null); });
    return () => { cancelled = true; };
  }, [selectedId, applications]);

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
    const includeFocused = focused?.id === selectedId && !applications.some(item => item.id === selectedId);
    const sorted = [...(includeFocused ? [...applications, focused] : applications)].sort((a, b) => b.id - a.id);
    if (!term) return sorted;
    return sorted.filter(
      (application) =>
        String(application.id).includes(term) ||
        application.applicant_name.toLowerCase().includes(term) ||
        application.business_name.toLowerCase().includes(term),
    );
  }, [applications, search, focused, selectedId]);

  return (
    <div className="space-y-6">
      <WorklistReturn />
      <header>
        <h2 className="text-xl font-bold text-slate-900">SHAP Reports</h2>
        <p className="mt-1 text-sm text-slate-500">
          Feature attributions are additive: the model reference baseline plus every
          contribution reconstructs the score, so a bank can file an SBP-oriented
          adverse-action note. The baseline is the score the model gives its reference
          sample (SMOTE-balanced training rows), not the average of a bank portfolio.
          SHAP explains the raw model probability; any calibrated probability shown is
          display only. ForiFlow is not SBP-certified.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="card h-fit">
          <div className="card-header">
            <h3 className="card-title">Select application</h3>
            <p className="text-xs leading-relaxed text-slate-500">Recent assessments and the open case. <Link className="font-semibold text-brand-700 underline" to="/applications">Search the full register</Link></p>
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
              placeholder="Filter this recent-case list"
              className="field-input py-1.5"
            />
          </div>

          {isLoading ? (
            <LoadingState label="Loading…" />
          ) : error ? (
            <ErrorState message={error} onRetry={loadApplications} />
          ) : filtered.length === 0 ? (
            <EmptyState
              title={applications.length ? "No recent cases match" : "No recent assessments"}
              description="Search the full register to find an older assessment, or clear this filter."
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
                      onClick={() => navigate(`/shap/${application.id}`, { state: returnState })}
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

        <div className="min-w-0 space-y-6">
          <section className="card">
            <div className="card-header">
              <h3 className="card-title">Feature attribution</h3>
              {selectedId ? (
                <span className="text-xs text-slate-500">Case #{selectedId}</span>
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
          {selectedId ? <ReviewPanel key={selectedId} applicationId={selectedId} /> : null}
        </div>
      </div>
    </div>
  );
}
