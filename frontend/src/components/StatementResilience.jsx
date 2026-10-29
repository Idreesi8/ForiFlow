import { formatPKRExact } from "../lib/format.js";
import { resilienceView } from "../lib/statementView.js";

/** Stored historical replay, kept apart from the model assessment and policy. */
export default function StatementResilience({ evidence, compact = false }) {
  const report = resilienceView(evidence, compact);
  if (!report) return null;
  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3" aria-label="Statement cash-flow resilience">
      <h3 className="text-sm font-semibold text-slate-900">Cash-flow resilience</h3>
      <p className="mt-1 text-xs text-slate-600">
        Replay the statement months against a new principal-only payment of{" "}
        <strong>{formatPKRExact(report.monthly_principal_pkr)}</strong> per month.
        Interest and fees are excluded.
      </p>
      {!report.matchesStatement ? (
        <p className="mt-2 text-xs font-medium text-amber-800">
          This check uses the statement. The figures submitted for scoring differ from it.
        </p>
      ) : null}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">Recorded and lower-inflow scenarios with outflows held constant</caption>
          <thead className="border-b border-slate-300 text-slate-600">
            <tr>
              <th className="py-2 pr-3 font-medium">Receipts</th>
              <th className="py-2 pr-3 font-medium">Months covering principal</th>
              <th className="py-2 text-right font-medium">Median left after payment</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {report.scenarios.map((row) => (
              <tr key={row.inflow_decline_percent}>
                <td className="whitespace-nowrap py-2 pr-3">
                  {row.inflow_decline_percent === 0 ? "Recorded" : `${row.inflow_decline_percent}% lower`}
                </td>
                <td className="tabular py-2 pr-3">
                  {row.months_covering_principal} of {row.months_observed}
                </td>
                <td className={`tabular whitespace-nowrap py-2 text-right font-semibold ${row.median_remainder_pkr < 0 ? "text-rose-700" : "text-slate-900"}`}>
                  {formatPKRExact(row.median_remainder_pkr)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-slate-500">
        Recorded outflows stay constant. Transfers and existing repayments may be
        included. This is a sensitivity check, not a forecast or an approval.
        Verify actual repayment terms and complete business cash flows.
      </p>
      {report.sourceFingerprint && !compact ? (
        <p className="mt-2 text-[11px] text-slate-500" title={report.sourceFingerprint}>
          Statement fingerprint: {report.sourceFingerprint.slice(0, 16)}…
        </p>
      ) : null}
    </section>
  );
}
