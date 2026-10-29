/** Read the stored server calculation; never derive credit policy from scenarios. */
export function resilienceView(evidence, compact = false) {
  const report = evidence?.resilience;
  if (report?.method_version !== "principal-stress-v1") return null;
  if (!Number.isFinite(report.monthly_principal_pkr) || report.monthly_principal_pkr < 0) return null;
  if (!Array.isArray(report.scenarios) || report.scenarios.length === 0) return null;
  const valid = report.scenarios.every((row) =>
    Number.isFinite(row.inflow_decline_percent) &&
    row.inflow_decline_percent >= 0 && row.inflow_decline_percent <= 100 &&
    Number.isInteger(row.months_observed) && row.months_observed > 0 &&
    Number.isInteger(row.months_covering_principal) && row.months_covering_principal >= 0 &&
    row.months_covering_principal <= row.months_observed &&
    Number.isFinite(row.median_remainder_pkr) && Number.isFinite(row.lowest_remainder_pkr),
  );
  if (!valid) return null;
  return {
    ...report,
    scenarios: compact
      ? report.scenarios.filter((row) => [0, 20].includes(row.inflow_decline_percent))
      : report.scenarios,
    matchesStatement: evidence.matches_statement === true,
    sourceFingerprint: typeof evidence.source_sha256 === "string" ? evidence.source_sha256 : null,
  };
}
