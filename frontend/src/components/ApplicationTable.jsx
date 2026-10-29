import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { canDecideCredit } from "../api/auth.js";
import { apiErrorMessage, fetchApplications } from "../api/client.js";
import {
  bandForDecision,
  decisionStatusOf,
  finalDecisionOf,
  isPendingReview,
} from "../lib/decisions.js";
import { formatDateTime, formatPKRCompact, parseApiDate } from "../lib/format.js";
import { FinalDecisionBadge, RecommendationBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState } from "./common/States.jsx";

const COLUMNS = [
  { key: "id", label: "ID", type: "number", align: "left" },
  { key: "applicant_name", label: "Applicant", type: "string", align: "left" },
  { key: "business_name", label: "Business", type: "string", align: "left" },
  { key: "loan_amount_pkr", label: "Facility", type: "number", align: "right" },
  { key: "tenure_months", label: "Tenure", type: "number", align: "right" },
  { key: "risk_score", label: "Score", type: "number", align: "right" },
  { key: "decision", label: "Recommendation", type: "string", align: "left" },
  { key: "final", label: "Officer decision", type: "string", align: "left" },
  { key: "created_at", label: "Assessed", type: "date", align: "left" },
];

// Filters on the officer's decision; the Recommendation column shows what the
// policy recommended, which is never a decision.
const DECISION_FILTERS = ["All", "Pending decision", "Approved", "Rejected"];

function sortValue(application, key) {
  return key === "final" ? decisionStatusOf(application) : application[key];
}

function compareValues(a, b, column) {
  if (column.type === "number") return Number(a) - Number(b);
  if (column.type === "date") {
    return (parseApiDate(a)?.getTime() ?? 0) - (parseApiDate(b)?.getTime() ?? 0);
  }
  return String(a ?? "").localeCompare(String(b ?? ""), "en");
}

/**
 * Sortable register of every scored application.
 *
 * Loads `GET /score/applications` unless a list is supplied by the parent, and
 * routes to the SHAP report for a row through the "View SHAP" action.
 */
export default function ApplicationTable({
  applications: providedApplications = null,
  limit = 100,
  showFilters = true,
  title = "Applications",
  refreshToken = 0,
  sort: controlledSort = null,
  onSortChange,
  summary,
  mobileCards = false,
}) {
  const navigate = useNavigate();
  const canDecide = canDecideCredit();
  const [applications, setApplications] = useState(providedApplications ?? []);
  const [isLoading, setIsLoading] = useState(!providedApplications);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("All");
  const [localSort, setSort] = useState({ key: "created_at", direction: "desc" });
  const sort = controlledSort ?? localSort;

  const loadApplications = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      setApplications(await fetchApplications({ limit }));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load applications."));
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    if (providedApplications) {
      setApplications(providedApplications);
      setIsLoading(false);
      return;
    }
    loadApplications();
  }, [providedApplications, loadApplications, refreshToken]);

  const visibleApplications = useMemo(() => {
    if (controlledSort) return applications;
    const term = search.trim().toLowerCase();
    const column = COLUMNS.find((item) => item.key === sort.key) ?? COLUMNS[0];

    return applications
      .filter((application) => {
        if (decisionFilter === "Pending decision" && !isPendingReview(application)) {
          return false;
        }
        if (
          (decisionFilter === "Approved" || decisionFilter === "Rejected") &&
          finalDecisionOf(application) !== decisionFilter
        ) {
          return false;
        }
        if (!term) return true;
        return (
          String(application.id).includes(term) ||
          application.applicant_name.toLowerCase().includes(term) ||
          application.business_name.toLowerCase().includes(term)
        );
      })
      .sort((a, b) => {
        const result = compareValues(sortValue(a, sort.key), sortValue(b, sort.key), column);
        return sort.direction === "asc" ? result : -result;
      });
  }, [applications, search, decisionFilter, sort, controlledSort]);

  const toggleSort = (key) => {
    if (onSortChange) {
      onSortChange({ key, direction: sort.key === key ? (sort.direction === 'asc' ? 'desc' : 'asc') :
        (['created_at', 'risk_score', 'id', 'loan_amount_pkr'].includes(key) ? 'desc' : 'asc') });
      return;
    }
    setSort((previous) =>
      previous.key === key
        ? { key, direction: previous.direction === "asc" ? "desc" : "asc" }
        : { key, direction: key === "created_at" || key === "risk_score" ? "desc" : "asc" },
    );
  };

  return (
    <section className="card">
      <div className="card-header">
        <div>
          <h2 className="card-title">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {summary ?? `${visibleApplications.length} of ${applications.length} assessments`}
          </p>
        </div>

        {showFilters ? (
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="application-search">
              Search applications
            </label>
            <input
              id="application-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search name, business or ID"
              className="field-input w-56 py-1.5"
            />
            {DECISION_FILTERS.map((decision) => (
              <button
                key={decision}
                type="button"
                onClick={() => setDecisionFilter(decision)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                  decisionFilter === decision
                    ? "bg-brand-600 text-white"
                    : "border border-slate-300 text-slate-600 hover:bg-slate-50"
                }`}
              >
                {decision}
              </button>
            ))}
            {providedApplications ? null : (
              <button
                type="button"
                onClick={loadApplications}
                className="btn-secondary py-1.5"
              >
                Refresh
              </button>
            )}
          </div>
        ) : null}
      </div>

      {isLoading ? (
        <LoadingState label="Loading applications…" />
      ) : error ? (
        <ErrorState message={error} onRetry={loadApplications} />
      ) : visibleApplications.length === 0 ? (
        <EmptyState
          title="No applications found"
          description="Score an SME through Credit Scoring to populate the register."
          action={
            <button
              type="button"
              className="btn-primary"
              onClick={() => navigate("/scoring")}
            >
              Score an application
            </button>
          }
        />
      ) : (
        <div>
        {mobileCards ? <ul className="divide-y divide-slate-200 md:hidden" aria-label="Application cases">
          {visibleApplications.map(application => <li key={application.id} className="space-y-4 px-5 py-5">
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="text-xs font-semibold text-brand-700">Case #{application.id}{application.borrower_public_id ? ` · ${application.borrower_public_id}` : ''}</p><h3 className="mt-1 break-words text-base font-bold text-slate-900">{application.business_name}</h3><p className="mt-1 break-words text-sm text-slate-500">{application.applicant_name}</p></div><span className={`tabular text-lg font-bold ${bandForDecision(application.decision).textClass}`}>{application.risk_score.toFixed(1)}<span className="block text-[10px] font-normal text-slate-500">out of 100</span></span></div>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm"><span className="font-semibold text-slate-800">{formatPKRCompact(application.loan_amount_pkr)}</span><span className="text-slate-500">{application.tenure_months} months</span></div>
            <div className="flex flex-wrap gap-x-6 gap-y-3"><div><p className="mb-1 text-[11px] text-slate-500">Recommendation</p><RecommendationBadge decision={application.decision} /></div><div><p className="mb-1 text-[11px] text-slate-500">Officer decision</p><FinalDecisionBadge application={application} /></div></div>
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-slate-500">{formatDateTime(application.created_at)}</p><button type="button" className="btn-secondary text-xs" onClick={() => navigate(`/shap/${application.id}`)} aria-label={`Open case ${application.id}`}>Open case →</button></div>
          </li>)}
        </ul> : null}
        <div className={`overflow-x-auto ${mobileCards ? 'hidden md:block' : ''}`}>
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="table-head">
              <tr>
                {COLUMNS.map((column) => {
                  const isSorted = sort.key === column.key;
                  return (
                    <th
                      key={column.key}
                      scope="col"
                      aria-sort={
                        isSorted
                          ? sort.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                      className={`px-5 py-3 whitespace-nowrap ${
                        column.align === "right" ? "text-right" : "text-left"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(column.key)}
                        className={`inline-flex items-center gap-1 transition hover:text-brand-700 ${
                          isSorted ? "text-brand-700" : ""
                        }`}
                      >
                        {column.label}
                        <span aria-hidden="true" className="text-[10px]">
                          {isSorted ? (sort.direction === "asc" ? "▲" : "▼") : "↕"}
                        </span>
                      </button>
                    </th>
                  );
                })}
                <th scope="col" className="px-5 py-3 text-right">
                  Report
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {visibleApplications.map((application) => {
                const band = bandForDecision(application.decision);
                return (
                  <tr key={application.id} className="hover:bg-slate-50">
                    <td className="tabular px-5 py-3 font-medium whitespace-nowrap text-slate-500">
                      #{application.id}
                    </td>
                    <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">
                      {application.applicant_name}
                    </td>
                    {/* The only wrapping column, so it needs a floor to stop
                        the nowrap columns from squeezing it. */}
                    <td className="min-w-[190px] px-5 py-3 text-slate-600">
                      <Link to={`/shap/${application.id}`} className="font-semibold text-brand-700 hover:underline">{application.business_name}</Link>
                      {application.borrower_public_id ? <p className="mt-1 text-xs text-slate-500">{application.borrower_public_id}</p> : null}
                    </td>
                    <td className="tabular px-5 py-3 text-right whitespace-nowrap text-slate-900">
                      {formatPKRCompact(application.loan_amount_pkr)}
                    </td>
                    <td className="tabular px-5 py-3 text-right whitespace-nowrap text-slate-600">
                      {application.tenure_months} mo
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      <span className={`tabular font-bold ${band.textClass}`}>
                        {application.risk_score.toFixed(1)}
                      </span>
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap">
                      <RecommendationBadge decision={application.decision} />
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap">
                      <FinalDecisionBadge application={application} />
                      {application.reviewed_by ? (
                        <p className="mt-1 text-xs text-slate-500">
                          by {application.reviewed_by}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-5 py-3 whitespace-nowrap text-slate-600">
                      {formatDateTime(application.created_at)}
                    </td>
                    <td className="px-5 py-3 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => navigate(`/shap/${application.id}`)}
                        className={
                          canDecide && isPendingReview(application)
                            ? "btn-primary py-1.5 text-xs"
                            : "btn-ghost py-1.5 text-xs"
                        }
                      >
                        {canDecide && isPendingReview(application) ? "Review" : "View SHAP"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        </div>
      )}
    </section>
  );
}
