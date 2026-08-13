import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { API_BASE_URL, fetchHealth } from "./api/client.js";
import AlertsPage from "./pages/AlertsPage.jsx";
import ApplicationsPage from "./pages/ApplicationsPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import NotFoundPage from "./pages/NotFoundPage.jsx";
import ScoringPage from "./pages/ScoringPage.jsx";
import ShapReportsPage from "./pages/ShapReportsPage.jsx";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: GridIcon, end: true },
  { to: "/scoring", label: "Credit Scoring", icon: GaugeIcon },
  { to: "/shap", label: "SHAP Reports", icon: ChartIcon },
  { to: "/alerts", label: "EWS Alerts", icon: BellIcon },
  { to: "/applications", label: "Applications", icon: ListIcon },
];

/**
 * Application shell: persistent sidebar navigation, a status header and the
 * five routed workspaces used by credit officers.
 */
export default function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [health, setHealth] = useState({ state: "checking", detail: null });

  const checkHealth = useCallback(async () => {
    try {
      const data = await fetchHealth();
      setHealth({ state: data.status === "ok" ? "online" : "degraded", detail: data });
    } catch {
      setHealth({ state: "offline", detail: null });
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const timer = setInterval(checkHealth, 60000);
    return () => clearInterval(timer);
  }, [checkHealth]);

  return (
    <div className="min-h-screen lg:flex">
      {isSidebarOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 z-20 bg-slate-900/50 lg:hidden"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-64 flex-col bg-brand-900 text-brand-50 transition-transform lg:static lg:translate-x-0 ${
          isSidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-3 border-b border-brand-800 px-5 py-5">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500 text-lg font-black text-white">
            F
          </span>
          <div>
            <p className="text-base leading-tight font-bold text-white">ForiFlow</p>
            <p className="text-xs text-brand-200">SME Credit Intelligence</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-4" aria-label="Main navigation">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setIsSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? "bg-brand-700 text-white shadow-sm"
                    : "text-brand-100 hover:bg-brand-800 hover:text-white"
                }`
              }
            >
              <Icon className="h-5 w-5 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-brand-800 px-5 py-4 text-xs text-brand-200">
          <p className="font-semibold text-brand-100">SBP compliance mode</p>
          <p className="mt-1 leading-relaxed">
            Every decision stores its SHAP rationale for audit. Bureau data via ECIB.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
          <div className="flex items-center justify-between gap-4 px-5 py-3.5">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                aria-label="Open navigation"
                className="btn-secondary px-2.5 py-1.5 lg:hidden"
              >
                ☰
              </button>
              <div>
                <h1 className="text-lg font-bold text-slate-900">
                  Credit Officer Workspace
                </h1>
                <p className="text-xs text-slate-500">
                  Alternative-data underwriting and portfolio surveillance
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <HealthPill state={health.state} onRetry={checkHealth} />
              <div className="hidden text-right sm:block">
                <p className="text-sm font-semibold text-slate-900">Risk Desk</p>
                <p className="text-xs text-slate-500">Commercial Banking Group</p>
              </div>
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-sm font-bold text-brand-800">
                RD
              </span>
            </div>
          </div>
        </header>

        <main className="flex-1 px-5 py-6">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/scoring" element={<ScoringPage />} />
            <Route path="/shap" element={<ShapReportsPage />} />
            <Route path="/shap/:applicationId" element={<ShapReportsPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/applications" element={<ApplicationsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </main>

        <footer className="border-t border-slate-200 bg-white px-5 py-3 text-xs text-slate-500">
          ForiFlow v1.0 · API {API_BASE_URL} · All amounts in PKR
        </footer>
      </div>
    </div>
  );
}

function HealthPill({ state, onRetry }) {
  const styles = {
    checking: { dot: "bg-slate-400", text: "text-slate-600", label: "Checking API…" },
    online: { dot: "bg-emerald-500", text: "text-emerald-700", label: "API online" },
    degraded: { dot: "bg-amber-500", text: "text-amber-700", label: "API degraded" },
    offline: { dot: "bg-rose-500", text: "text-rose-700", label: "API offline" },
  }[state];

  return (
    <button
      type="button"
      onClick={onRetry}
      title={`Backend: ${API_BASE_URL}`}
      className={`badge border border-slate-200 bg-white ${styles.text}`}
    >
      <span className={`h-2 w-2 rounded-full ${styles.dot}`} aria-hidden="true" />
      {styles.label}
    </button>
  );
}

function GridIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function GaugeIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 18a8 8 0 1116 0" strokeLinecap="round" />
      <path d="M12 18l4.5-5" strokeLinecap="round" />
      <circle cx="12" cy="18" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

function ChartIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 5h10M4 12h14M4 19h7" strokeLinecap="round" />
    </svg>
  );
}

function BellIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M6 9a6 6 0 1112 0c0 4 1.5 5.5 1.5 5.5h-15S6 13 6 9z" strokeLinejoin="round" />
      <path d="M10 18a2 2 0 004 0" strokeLinecap="round" />
    </svg>
  );
}

function ListIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M8 9h8M8 13h8M8 17h5" strokeLinecap="round" />
    </svg>
  );
}
