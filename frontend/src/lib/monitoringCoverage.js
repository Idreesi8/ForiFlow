/** Coverage describes recorded evidence, never whether a payment was due or made. */
export function monitoringCoverage(rows, tenure, facilityId) {
  if (!Array.isArray(rows) || !Number.isInteger(tenure) || tenure < 1 || tenure > 84) {
    throw new Error("The facility term or monitoring history could not be verified.");
  }
  const active = new Map(), versions = new Map(), ids = new Set();
  for (const row of rows) {
    if (row.borrower_id !== Number(facilityId) || !Number.isInteger(row.id) || row.id < 1 || ids.has(row.id) ||
        !Number.isInteger(row.month_number) || row.month_number < 1 || row.month_number > tenure ||
        !["active", "superseded"].includes(row.record_status)) {
      throw new Error("Monitoring history contains inconsistent case or month references. Verify the history before adding records.");
    }
    if (row.amount_paid_pkr != null && (typeof row.amount_paid_pkr !== "number" || !Number.isFinite(row.amount_paid_pkr) || row.amount_paid_pkr < 0)) {
      throw new Error("A recorded payment amount is invalid. Verify the history before adding records.");
    }
    ids.add(row.id);
    versions.set(row.month_number, (versions.get(row.month_number) ?? 0) + 1);
    if (row.record_status === "active") {
      if (active.has(row.month_number)) throw new Error("More than one active observation exists for a month. Refresh and verify the history.");
      active.set(row.month_number, row);
    }
  }
  const latest = Math.max(0, ...active.keys());
  const months = Array.from({ length: tenure }, (_, index) => {
    const number = index + 1, record = active.get(number) ?? null;
    const state = record ? record.amount_paid_pkr == null ? "unknown" : "recorded" : number < latest ? "gap" : "unrecorded";
    return { number, state, record, priorVersions: Math.max(0, (versions.get(number) ?? 0) - (record ? 1 : 0)) };
  });
  return { months, latest, recorded: active.size,
    gaps: months.filter(month => month.state === "gap").length,
    unknown: months.filter(month => month.state === "unknown").length,
    nextMonth: months.find(month => !month.record)?.number ?? null };
}

export function observationForm(row) {
  return {
    borrower_id: String(row.borrower_id), month_number: String(row.month_number),
    observation_date: row.observation_date ?? "", installment_status: row.installment_status,
    days_late: row.days_late == null ? "" : String(row.days_late),
    bureau_balance: String(row.bureau_balance), pos_cash_balance: String(row.pos_cash_balance),
    amount_paid_pkr: row.amount_paid_pkr == null ? "" : String(row.amount_paid_pkr),
    data_source_primary: row.data_source_primary, override: row.score_source === "officer_override",
    current_score: row.score_source === "officer_override" ? String(row.monthly_score) : "",
    override_reason: row.score_source === "officer_override" ? row.override_reason ?? "" : "",
  };
}

export function monitoringFormDirty(form, initial) {
  return Object.keys(initial).some(key => !["borrower_id", "month_number"].includes(key) && form[key] !== initial[key]);
}
