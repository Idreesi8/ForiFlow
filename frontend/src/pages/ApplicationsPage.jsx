import { useNavigate } from "react-router-dom";

import ApplicationTable from "../components/ApplicationTable.jsx";

/** Full register of scored applications. */
export default function ApplicationsPage() {
  const navigate = useNavigate();

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Applications</h2>
          <p className="mt-1 text-sm text-slate-500">
            Every assessment on file. Sort any column, then open the SHAP report used
            for the credit decision.
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => navigate("/scoring")}>
          New assessment
        </button>
      </header>

      <ApplicationTable title="Application register" limit={200} />
    </div>
  );
}
