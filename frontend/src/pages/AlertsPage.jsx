import { useState } from "react";

import EWSAlertFeed from "../components/EWSAlertFeed.jsx";
import MonitoringPanel from "../components/MonitoringPanel.jsx";

/** Surveillance workspace: record a monitored month and work the alert queue. */
export default function AlertsPage() {
  const [refreshToken, setRefreshToken] = useState(0);

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-bold text-slate-900">EWS Alerts</h2>
        <p className="mt-1 text-sm text-slate-500">
          Post-disbursement surveillance for approved facilities. Each month an
          officer records the repayment status, a typed bureau balance and POS
          figures. An alert is raised when the score drops more than 15 points, or
          when a Markov chain fitted on real repayment histories puts default within
          three months at 10% or more. There is no live ECIB connector.
        </p>
      </header>

      <MonitoringPanel onMonitored={() => setRefreshToken((token) => token + 1)} />

      <EWSAlertFeed refreshToken={refreshToken} />
    </div>
  );
}
