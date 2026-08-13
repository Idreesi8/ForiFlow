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
          Post-disbursement surveillance. Each borrower is re-scored monthly from
          repayment behaviour, ECIB balances and POS settlements.
        </p>
      </header>

      <MonitoringPanel onMonitored={() => setRefreshToken((token) => token + 1)} />

      <EWSAlertFeed refreshToken={refreshToken} />
    </div>
  );
}
