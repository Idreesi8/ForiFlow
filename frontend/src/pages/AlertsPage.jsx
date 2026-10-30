import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { apiErrorMessage, fetchEwsOverview } from "../api/client.js";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import EWSFacilityDetail from "../components/EWSFacilityDetail.jsx";
import EWSOverview from "../components/EWSOverview.jsx";
import FacilitySwitchDialog from "../components/FacilitySwitchDialog.jsx";
import MonitoringPanel from "../components/MonitoringPanel.jsx";
import MonitoringWorkspaceNav from "../components/MonitoringWorkspaceNav.jsx";
import WorklistReturn from "../components/WorklistReturn.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { positiveInteger, worklistReturnState } from "../lib/actionDesk.js";
import { reminderReturnState } from '../lib/reminderReview.js';
import { MONITORING_SECTIONS, revealMonitoringSection } from '../lib/monitoringWorkspace.js';

/**
 * Early Warning System workspace: the portfolio position, one facility's
 * history, the month entry form and the alert queue.
 */
export default function AlertsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const returnState = worklistReturnState(location.state) ?? reminderReturnState(location.state);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedFacility = positiveInteger(searchParams.get("facility"));
  const requestedMonth = positiveInteger(searchParams.get("month"));
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);
  const [selectedId, setSelectedId] = useState(requestedFacility);
  const [refreshToken, setRefreshToken] = useState(0);
  const [monitoringDirty, setMonitoringDirty] = useState(false);
  const [monitoringBusy, setMonitoringBusy] = useState(false);
  const [pendingFacility, setPendingFacility] = useState(null);
  const overviewRequestSequence = useRef(0);
  const pendingSection = useRef(null);
  const scrolledLocation = useRef(null);
  const [historyReadyId, setHistoryReadyId] = useState();
  const [monitoringReadyId, setMonitoringReadyId] = useState();

  const commitFacility = id => {
    setMonitoringDirty(false);
    setPendingFacility(null);
    setHistoryReadyId(undefined);
    setMonitoringReadyId(undefined);
    setSelectedId(id);
    const section = pendingSection.current;
    if (requestedFacility || section) navigate({ pathname: location.pathname,
      search: requestedFacility ? `?facility=${id}` : location.search,
      hash: section ? `#${section}` : location.hash }, { state: returnState ?? location.state, preventScrollReset: true });
    if (section) revealMonitoringSection(section);
    pendingSection.current = null;
  };
  const requestFacility = (id, section = null) => {
    if (monitoringBusy) return;
    if (id === selectedId) {
      if (section) {
        navigate({ pathname: location.pathname, search: location.search, hash: `#${section}` },
          { state: location.state, preventScrollReset: true });
        revealMonitoringSection(section);
      }
      return;
    }
    pendingSection.current = section;
    if (monitoringDirty) setPendingFacility(id);
    else commitFacility(id);
  };

  useEffect(() => {
    if (!requestedFacility || requestedFacility === selectedId) return;
    if ((monitoringDirty || monitoringBusy) && selectedId) {
      pendingSection.current = MONITORING_SECTIONS.some(section => `#${section.id}` === location.hash) ? location.hash.slice(1) : null;
      setPendingFacility(requestedFacility);
      setSearchParams({ facility: String(selectedId) }, { replace: true, state: returnState });
    } else {
      setHistoryReadyId(undefined);
      setMonitoringReadyId(undefined);
      setSelectedId(requestedFacility);
    }
  }, [requestedFacility, selectedId, monitoringDirty, monitoringBusy, setSearchParams]);

  useEffect(() => {
    const anchor = location.hash.slice(1);
    if ((!overview && !error) || pendingFacility ||
      (requestedFacility && requestedFacility !== selectedId) || scrolledLocation.current === location.key ||
      !MONITORING_SECTIONS.some(section => section.id === anchor)) return;
    // Loading history above the editor changes its position. Finish the jump
    // once the selected history and calendar have settled, including errors.
    if (['monitoring', 'alert-queue'].includes(anchor) &&
      (monitoringReadyId !== selectedId || (selectedId && historyReadyId !== selectedId))) return;
    scrolledLocation.current = location.key;
    revealMonitoringSection(anchor);
  }, [location.key, location.hash, overview, error, requestedFacility, pendingFacility, selectedId, historyReadyId, monitoringReadyId]);

  const loadOverview = useCallback(async () => {
    const request = ++overviewRequestSequence.current;
    setError(null);
    try {
      const data = await fetchEwsOverview();
      if (request !== overviewRequestSequence.current) return;
      setOverview(data);
      setSelectedId((current) => current ?? data.rows[0]?.facility_id ?? null);
    } catch (requestError) {
      if (request === overviewRequestSequence.current) setError(apiErrorMessage(requestError, "Could not load the EWS overview."));
    }
  }, []);

  useEffect(() => {
    loadOverview();
    return () => { overviewRequestSequence.current += 1; };
  }, [loadOverview, refreshToken]);

  const refresh = () => setRefreshToken((token) => token + 1);
  const method = overview?.methodology;

  return (
    <div className="space-y-6">
      <WorklistReturn />
      <header>
        <h2 className="text-xl font-bold text-slate-900">Early Warning System</h2>
        <p className="mt-1 max-w-4xl text-sm text-slate-500">
          Monitoring of approved facilities from officer-recorded months. The EWS is rule- and
          trend-based: it is not a model that predicts default, and it recommends follow-up
          without changing any facility or credit decision. There is no live ECIB connector.
        </p>
      </header>

      <MonitoringWorkspaceNav selectedId={selectedId} overview={overview} dirty={monitoringDirty} busy={monitoringBusy} />

      {requestedFacility ? <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900"><span>Focused on case #{selectedId}. {!returnState ? <Link className="font-semibold underline" to="/action-desk">Back to action desk</Link> : null}</span><button type="button" className="btn-secondary" onClick={() => { setSearchParams({}, { state: returnState }); setPendingFacility(null); }}>Show all alerts</button></div> : null}
      {pendingFacility ? <FacilitySwitchDialog fromId={selectedId} toId={pendingFacility} busy={monitoringBusy}
        onCancel={() => { setPendingFacility(null); pendingSection.current = null; }}
        onConfirm={() => commitFacility(pendingFacility)} /> : null}

      <div id="portfolio-monitoring" role="region" aria-label="Portfolio monitoring" tabIndex={-1} className="monitoring-section">
      {error ? (
        <ErrorState message={error} onRetry={loadOverview} />
      ) : !overview ? (
        <LoadingState label="Loading the EWS overview…" />
      ) : (
        <EWSOverview overview={overview} selectedId={selectedId} disabled={monitoringBusy}
          onSelect={id => requestFacility(id, 'facility-history')}
          onRecord={id => requestFacility(id, 'monitoring')} />
      )}
      </div>

      <div id="facility-history" role="region" aria-label="Selected facility history" tabIndex={-1} className="monitoring-section">
        {selectedId ? <EWSFacilityDetail facilityId={selectedId} refreshToken={refreshToken} onReady={setHistoryReadyId} /> : <div className="card p-5 text-sm text-slate-500"><h2 className="card-title">Choose a facility to review</h2><p className="mt-2">Select a monitored facility above, or find an approved facility under Record a month.</p></div>}
      </div>

      <div id="monitoring" role="region" aria-label="Monitoring month editor" tabIndex={-1} className="monitoring-section"><MonitoringPanel
        facilityId={selectedId}
        initialMonth={requestedFacility === selectedId && requestedMonth <= 84 ? requestedMonth : null}
        refreshToken={refreshToken}
        onFacilityChange={id => requestFacility(id, selectedId ? 'monitoring' : null)}
        onDirtyChange={setMonitoringDirty}
        onBusyChange={setMonitoringBusy}
        onReady={setMonitoringReadyId}
        onMonitored={(response) => {
          setSelectedId(response.borrower_id);
          refresh();
        }}
      /></div>

      <div id="alert-queue" role="region" aria-label="Alert queue" tabIndex={-1} className="monitoring-section"><EWSAlertFeed facilityId={requestedFacility ? selectedId : null} refreshToken={refreshToken} onChanged={refresh} /></div>

      {method ? (
        <section className="card" data-testid="ews-methodology">
          <div className="card-header">
            <h2 className="card-title">Methodology</h2>
          </div>
          <div className="grid gap-4 px-5 py-4 text-sm text-slate-700 md:grid-cols-2">
            <ul className="list-disc space-y-1 pl-5">
              <li>
                WARNING when the monitored score is more than {method.score_drop_warning} points below
                the origination baseline; CRITICAL from {method.score_drop_critical} points, or when
                the latest month is {method.critical_statuses.join(" or ")}.
              </li>
              <li>
                A trend direction needs {method.trend_min_observations} recorded months; it is the
                least-squares slope, with ±{method.trend_slope_points_per_month} points a month as
                the line between Stable and a direction.
              </li>
              <li>
                Signals: bureau balance up more than {method.balance_increase_pct}%, POS inflow down
                more than {method.pos_decline_pct}%, repayment later than the month before.
              </li>
              <li>Alerts are raised at {method.alert_states.join(" and ")}; one open alert per facility.</li>
            </ul>
            <ul className="list-disc space-y-1 pl-5">
              {method.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}
    </div>
  );
}
