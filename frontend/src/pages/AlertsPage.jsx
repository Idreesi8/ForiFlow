import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { apiErrorMessage, fetchEwsOverview } from "../api/client.js";
import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import EWSFacilityDetail from "../components/EWSFacilityDetail.jsx";
import EWSOverview from "../components/EWSOverview.jsx";
import MonitoringPanel from "../components/MonitoringPanel.jsx";
import WorklistReturn from "../components/WorklistReturn.jsx";
import { ErrorState, LoadingState } from "../components/common/States.jsx";
import { positiveInteger, worklistReturnState } from "../lib/actionDesk.js";
import { reminderReturnState } from '../lib/reminderReview.js';

/**
 * Early Warning System workspace: the portfolio position, one facility's
 * history, the month entry form and the alert queue.
 */
export default function AlertsPage() {
  const location = useLocation();
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

  const commitFacility = id => {
    setMonitoringDirty(false);
    setPendingFacility(null);
    setSelectedId(id);
    if (requestedFacility) setSearchParams({ facility: String(id) }, { state: returnState });
  };
  const requestFacility = id => {
    if (monitoringBusy || id === selectedId) return;
    if (monitoringDirty) setPendingFacility(id);
    else commitFacility(id);
  };

  useEffect(() => {
    if (!requestedFacility || requestedFacility === selectedId) return;
    if ((monitoringDirty || monitoringBusy) && selectedId) {
      setPendingFacility(requestedFacility);
      setSearchParams({ facility: String(selectedId) }, { replace: true, state: returnState });
    } else setSelectedId(requestedFacility);
  }, [requestedFacility, selectedId, monitoringDirty, monitoringBusy, setSearchParams]);

  useEffect(() => {
    const anchor = location.hash.slice(1);
    if (!requestedFacility || !["monitoring", "alert-queue"].includes(anchor)) return;
    const frame = requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [location.hash, requestedFacility, overview]);

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

      {requestedFacility ? <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900"><span>Focused on case #{selectedId}. {!returnState ? <Link className="font-semibold underline" to="/action-desk">Back to action desk</Link> : null}</span><button type="button" className="btn-secondary" onClick={() => { setSearchParams({}, { state: returnState }); setPendingFacility(null); }}>Show all alerts</button></div> : null}
      {pendingFacility ? <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950" data-testid="unsaved-facility"><p>There are unsubmitted figures for case #{selectedId}. Switching to case #{pendingFacility} clears those figures.</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" className="btn-secondary" onClick={() => setPendingFacility(null)}>Keep editing this facility</button><button type="button" className="btn-primary" disabled={monitoringBusy} onClick={() => commitFacility(pendingFacility)}>Switch facility and clear figures</button></div></div> : null}

      {error ? (
        <ErrorState message={error} onRetry={loadOverview} />
      ) : !overview ? (
        <LoadingState label="Loading the EWS overview…" />
      ) : (
        <EWSOverview overview={overview} selectedId={selectedId} onSelect={requestFacility} />
      )}

      {selectedId ? <EWSFacilityDetail facilityId={selectedId} refreshToken={refreshToken} /> : null}

      <div id="monitoring" className="scroll-mt-24"><MonitoringPanel
        facilityId={selectedId}
        initialMonth={requestedFacility === selectedId && requestedMonth <= 84 ? requestedMonth : null}
        refreshToken={refreshToken}
        onFacilityChange={requestFacility}
        onDirtyChange={setMonitoringDirty}
        onBusyChange={setMonitoringBusy}
        onMonitored={(response) => {
          setSelectedId(response.borrower_id);
          refresh();
        }}
      /></div>

      <div id="alert-queue" className="scroll-mt-24"><EWSAlertFeed facilityId={requestedFacility ? selectedId : null} refreshToken={refreshToken} onChanged={refresh} /></div>

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
