import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { fetchHealth, fetchMe, logout } from "./api/client.js";
import {
  clearSession,
  getStoredRole,
  getStoredUsername,
  isLoggedIn,
  updateStoredAccount,
} from "./api/auth.js";
import { LoadingState } from "./components/common/States.jsx";
import PageBoundary from "./components/common/PageBoundary.jsx";
import WorkspaceFinder from "./components/WorkspaceFinder.jsx";
import { containDialogFocus } from "./lib/dialogFocus.js";
import { UnsavedWorkProvider, useGuardedExit } from "./components/UnsavedWork.jsx";

const AlertsPage = lazy(() => import("./pages/AlertsPage.jsx"));
const ActionDeskPage = lazy(() => import("./pages/ActionDeskPage.jsx"));
const ApplicationsPage = lazy(() => import("./pages/ApplicationsPage.jsx"));
const DashboardPage = lazy(() => import("./pages/DashboardPage.jsx"));
const LoginPage = lazy(() => import("./pages/LoginPage.jsx"));
const MemoPage = lazy(() => import("./pages/MemoPage.jsx"));
const ModelPage = lazy(() => import("./pages/ModelPage.jsx"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage.jsx"));
const RemindersPage = lazy(() => import("./pages/RemindersPage.jsx"));
const PolicyPage = lazy(() => import("./pages/PolicyPage.jsx"));
const TeamPage = lazy(() => import("./pages/TeamPage.jsx"));
const ScoringPage = lazy(() => import("./pages/ScoringPage.jsx"));
const CashflowPage = lazy(() => import("./pages/CashflowPage.jsx"));
const ShapReportsPage = lazy(() => import("./pages/ShapReportsPage.jsx"));

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", description: "Your portfolio at a glance", group: "Your workday", icon: GridIcon, end: true },
  { to: "/action-desk", label: "Action Desk", description: "Prioritised reviews and follow-ups", group: "Your workday", keywords: "tasks next urgent", icon: ListIcon },
  { to: "/scoring", label: "Credit Scoring", description: "Start a new business assessment", group: "Lending", keywords: "loan applicant new", icon: GaugeIcon },
  { to: "/applications", label: "Applications", description: "Find cases and review decisions", group: "Lending", keywords: "borrower register search", icon: ListIcon },
  { to: "/shap", label: "SHAP Reports", description: "Understand the reasons behind a score", group: "Lending", keywords: "explain rationale", icon: ChartIcon },
  { to: "/alerts", label: "EWS Alerts", description: "Monitor facilities and record a month", group: "Monitoring", keywords: "early warning calendar payments history", icon: BellIcon },
  { to: "/cashflow", label: "Cash-flow Intelligence", description: "Analyse statement trends and test receipt estimates", group: "Monitoring", keywords: "statement forecast forecasting cashflow cash flow receipts trend csv technology", icon: ChartIcon },
  { to: "/reminders", label: "Reminders", description: "Prepare payment follow-ups", group: "Monitoring", keywords: "collection message", icon: MessageIcon },
  { to: "/model", label: "Model Performance", description: "Inspect model evidence and limitations", group: "Governance", icon: CurveIcon },
  { to: "/policy", label: "Credit Policy", description: "Review score bands and approval limits", group: "Governance", icon: ListIcon },
  { to: "/team", label: "Team & Roles", description: "View account access and responsibilities", group: "Governance", keywords: "users staff", icon: UsersIcon },
];

/**
 * Application shell: persistent sidebar navigation, a status header and the
 * routed workspaces used by credit officers.
 */
export default function App() {
  return (
    <PageBoundary>
    <UnsavedWorkProvider>
    <Suspense fallback={<LoadingState label="Loading ForiFlow…" />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <OfficerShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/action-desk" element={<ActionDeskPage />} />
        <Route path="/scoring" element={<ScoringPage />} />
        <Route path="/cashflow" element={<CashflowPage />} />
        <Route path="/shap" element={<ShapReportsPage />} />
        <Route path="/shap/:applicationId" element={<ShapReportsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/applications" element={<ApplicationsPage />} />
        <Route path="/memo/:applicationId" element={<MemoPage />} />
        <Route path="/model" element={<ModelPage />} />
        <Route path="/reminders" element={<RemindersPage />} />
        <Route path="/policy" element={<PolicyPage />} />
        <Route path="/team" element={<TeamPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
    </Suspense>
    </UnsavedWorkProvider>
    </PageBoundary>
  );
}

function RequireAuth({ children }) {
  const location = useLocation();
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}

function OfficerShell() {
  const requestExit = useGuardedExit();
  const navigate = useNavigate();
  const location = useLocation();
  const [account, setAccount] = useState({
    username: getStoredUsername(),
    role: getStoredRole(),
  });
  const { username, role } = account;
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [finderOpen, setFinderOpen] = useState(false);
  const menu = useRef(null);
  const menuTrigger = useRef(null);
  const main = useRef(null);
  const currentPage = NAV_ITEMS.find(item => item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to));
  const [health, setHealth] = useState({ state: "checking", detail: null });

  useEffect(() => {
    if (!isSidebarOpen) return;
    menu.current.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const media = window.matchMedia("(min-width: 1024px)");
    const resize = () => { if (media.matches) setIsSidebarOpen(false); };
    media.addEventListener("change", resize);
    return () => { menu.current?.close(); document.body.style.overflow = previousOverflow; media.removeEventListener("change", resize); menuTrigger.current?.focus(); };
  }, [isSidebarOpen]);

  useEffect(() => {
    const shortcut = event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setIsSidebarOpen(false);
        setFinderOpen(value => !value);
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);

  useEffect(() => {
    document.title = `${currentPage?.label ?? "Credit memo"} · ForiFlow`;
    main.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  // The stored role is only a display hint; ask the server who this is. A
  // disabled or signed-out account gets a 401 here and the client sends it
  // back to the sign-in page.
  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const controller = new AbortController();
    const refresh = () => {
      if (inFlight || document.hidden) return;
      inFlight = true;
      fetchMe({ signal: controller.signal })
        .then((me) => {
          if (cancelled) return;
          updateStoredAccount(me);
          setAccount({ username: me.username, role: me.role });
        })
        .catch(() => {})
        .finally(() => { inFlight = false; });
    };
    const reflect = () => setAccount({ username: getStoredUsername(), role: getStoredRole() });
    refresh();
    const timer = setInterval(refresh, 60000);
    window.addEventListener('focus', refresh);
    window.addEventListener('storage', refresh);
    window.addEventListener('foriflow:account-updated', reflect);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      cancelled = true;
      controller.abort(); clearInterval(timer);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('storage', refresh);
      window.removeEventListener('foriflow:account-updated', reflect);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [location.pathname]);

  const signOut = useCallback(async () => {
    try {
      await logout();
    } catch {
      // Already expired or the API is down: the local session goes regardless.
    }
    clearSession();
    navigate("/login", { replace: true });
  }, [navigate]);

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
      <a href="#main-content" className="skip-link">Skip to content</a>
      <WorkspaceFinder items={NAV_ITEMS} open={finderOpen} onClose={() => setFinderOpen(false)} />
      <dialog ref={menu} className="mobile-navigation" aria-label="Navigation" onCancel={() => setIsSidebarOpen(false)}
        onKeyDown={containDialogFocus}
        onClick={event => { if (event.target === menu.current) setIsSidebarOpen(false); }}>
        <div className="flex items-center justify-between border-b border-brand-800 p-5"><span className="text-lg font-bold">ForiFlow</span><button type="button" className="rounded-lg px-3 py-2 text-sm hover:bg-brand-800" onClick={() => setIsSidebarOpen(false)} aria-label="Close navigation">Close ×</button></div>
        <WorkspaceNavigation onSelect={() => setIsSidebarOpen(false)} />
        <div className="border-t border-brand-800 p-5 text-sm"><p className="font-semibold">{username || "Officer"}</p><p className="mt-1 text-brand-200 capitalize">{role || "Signed in"}</p></div>
      </dialog>

      <aside
        className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col overflow-y-auto bg-brand-900 text-brand-50 lg:flex print:hidden"
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

        <WorkspaceNavigation />

        <div className="border-t border-brand-800 px-5 py-4 text-xs text-brand-200">
          <p className="font-semibold text-brand-100">Evidence before decisions</p>
          <p className="mt-1 leading-relaxed">
            Review the assessment, its explanation and recorded evidence before making a credit decision.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur print:hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-3 sm:gap-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                ref={menuTrigger}
                aria-label="Open navigation"
                aria-expanded={isSidebarOpen}
                className="btn-secondary px-2.5 py-1.5 lg:hidden"
              >
                ☰
              </button>
              <div className="min-w-0">
                <p className="mb-0.5 hidden text-[10px] font-semibold tracking-[0.18em] text-slate-500 uppercase sm:block">Officer workspace</p>
                <p className="truncate text-base font-bold text-slate-900 sm:text-lg">
                  {currentPage?.label ?? "Credit memo"}
                </p>
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2 sm:gap-4">
              <button type="button" aria-label="Find a workspace" aria-keyshortcuts="Control+k Meta+k" onClick={() => setFinderOpen(true)} className="btn-secondary gap-2 px-3 text-xs">
                <SearchIcon className="h-4 w-4" /><span className="hidden md:inline">Find workspace</span><kbd className="hidden rounded border border-slate-200 px-1 text-[10px] text-slate-500 xl:inline">Ctrl K</kbd>
              </button>
              <div className="hidden xl:block"><HealthPill state={health.state} onRetry={checkHealth} /></div>
              <div className="hidden text-right sm:block">
                <p className="text-sm font-semibold text-slate-900">
                  {username || "Officer"}
                </p>
                <p className="text-xs text-slate-500 capitalize">{role || "signed in"}</p>
              </div>
              <button
                type="button"
                className="btn-secondary px-3 py-1.5 text-xs"
                onClick={() => requestExit(signOut)}
              >
                Sign out
              </button>
            </div>
          </div>
        </header>

        <main id="main-content" ref={main} tabIndex={-1} className="mx-auto w-full max-w-[1680px] flex-1 px-4 py-6 outline-none sm:px-6 lg:p-8">
          <h1 className="sr-only">{currentPage?.label ?? "Credit memo"} workspace</h1>
          <PageBoundary key={location.pathname}>
          <Suspense fallback={<LoadingState label="Loading workspace…" />}>
            <Outlet />
          </Suspense>
          </PageBoundary>
        </main>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 bg-white px-6 py-3 text-xs text-slate-500 print:hidden">
          <span>ForiFlow · Amounts in PKR · Dates and times in PKT (UTC+05:00)</span><HealthPill state={health.state} onRetry={checkHealth} />
        </footer>
      </div>
    </div>
  );
}

function WorkspaceNavigation({ onSelect }) {
  return <nav className="flex-1 space-y-5 px-3 py-5" aria-label="Main navigation">
    {["Your workday", "Lending", "Monitoring", "Governance"].map(group => <div key={group}>
      <p className="mb-2 px-3 text-[10px] font-semibold tracking-[0.16em] text-brand-200 uppercase">{group}</p>
      <div className="space-y-1">{NAV_ITEMS.filter(item => item.group === group).map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={onSelect}
        className={({ isActive }) => `flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${isActive ? "bg-brand-700 text-white shadow-sm ring-1 ring-brand-500/40" : "text-brand-100 hover:bg-brand-800 hover:text-white"}`}>
        <Icon className="h-5 w-5 shrink-0" /><span className="flex-1">{label}</span>
      </NavLink>)}</div>
    </div>)}
  </nav>;
}

function SearchIcon({ className }) {
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" strokeLinecap="round" /></svg>;
}

function HealthPill({ state, onRetry }) {
  const styles = {
    checking: { dot: "bg-slate-400", text: "text-slate-600", label: "Checking service…" },
    online: { dot: "bg-emerald-500", text: "text-emerald-700", label: "Service online" },
    degraded: { dot: "bg-amber-500", text: "text-amber-700", label: "Service limited" },
    offline: { dot: "bg-rose-500", text: "text-rose-700", label: "Service unavailable" },
  }[state];

  return (
    <button
      type="button"
      onClick={onRetry}
      title="Check the ForiFlow service again"
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

function CurveIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 4v16h16" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 20c2-9 6-13 16-15" strokeLinecap="round" />
    </svg>
  );
}

function MessageIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 5h16v11H9l-5 4V5z" strokeLinejoin="round" />
      <path d="M8 9h8M8 12h5" strokeLinecap="round" />
    </svg>
  );
}

function UsersIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 19c0-3 2.7-5 6-5s6 2 6 5" strokeLinecap="round" />
      <path d="M16 5.2a3 3 0 010 5.6M17.5 14.3c2 .6 3.5 2.2 3.5 4.7" strokeLinecap="round" />
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
