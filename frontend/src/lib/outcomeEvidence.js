export const EVIDENCE_STATUSES = {
  needs_approval_record: 'Approval record needed',
  shorter_term: 'Shorter than window',
  collecting: 'Window still open',
  needs_evidence: 'Records need attention',
  covered: 'Window covered',
};

/** Navigation carries only bounded view controls, never case facts or URLs. */
export function evidenceReturnState(state) {
  const query = state?.evidenceQuery;
  if (!query || Array.isArray(query) || ![3, 6, 12].includes(query.horizon) ||
      query.limit !== 10 || !Number.isSafeInteger(query.offset) || query.offset < 0 ||
      query.offset > 1_000_000 || query.offset % 10 !== 0 ||
      !(query.status_filter === '' || Object.hasOwn(EVIDENCE_STATUSES, query.status_filter))) return null;
  return { evidenceQuery: { horizon: query.horizon, limit: 10, offset: query.offset, status_filter: query.status_filter } };
}

/** Withhold impossible totals rather than turn missing evidence into success. */
export function validOutcomeEvidence(data, expected) {
  if (!data || data.training_ready !== false || data.horizon_months !== expected.horizon ||
      data.offset !== expected.offset || data.limit !== expected.limit ||
      data.status_filter !== (expected.status_filter || null)) return false;
  const counts = data.counts;
  const integer = n => Number.isSafeInteger(n) && n >= 0;
  if (!counts || !Object.values(counts).every(integer) || !integer(counts.covered_with_30_plus) || !integer(data.total) ||
      !Object.keys(EVIDENCE_STATUSES).every(key => integer(counts[key])) ||
      counts.approved_facilities !== Object.keys(EVIDENCE_STATUSES).reduce((sum, key) => sum + counts[key], 0) ||
      counts.covered_with_30_plus > counts.covered ||
      counts.distinct_linked_borrowers + counts.additional_repeat_facilities + counts.unlinked_facilities !== counts.approved_facilities ||
      data.total !== (expected.status_filter ? counts[expected.status_filter] : counts.approved_facilities)) return false;
  if (!Array.isArray(data.rows) || data.rows.length !== Math.min(expected.limit, Math.max(0, data.total - expected.offset)) ||
      !Array.isArray(data.limits) || !data.limits.every(note => typeof note === 'string') ||
      typeof data.basis !== 'string' || typeof data.captured_at !== 'string') return false;
  const ids = new Set();
  return data.rows.every(row => {
    if (!Number.isSafeInteger(row.application_id) || row.application_id <= 0 || ids.has(row.application_id)) return false;
    ids.add(row.application_id);
    return Object.hasOwn(EVIDENCE_STATUSES, row.status) &&
      (!expected.status_filter || row.status === expected.status_filter) &&
      typeof row.business_name === 'string' && integer(row.recorded_months) &&
      integer(row.usable_months) && row.usable_months <= row.recorded_months &&
      row.recorded_months <= expected.horizon && Array.isArray(row.reasons) &&
      row.reasons.every(note => typeof note === 'string') && typeof row.recorded_30_plus === 'boolean';
  });
}
