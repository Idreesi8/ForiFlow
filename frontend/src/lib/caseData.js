import { isoDate } from './repaymentCalendar.js';

export const SOURCE_KINDS = { bank_statement: 'Bank statement', wallet_statement: 'Wallet statement', pos: 'POS records', accounting: 'Accounting or invoices', bureau_extract: 'Bureau extract', applicant_declaration: 'Applicant declaration', other: 'Other source' };
export const PURPOSES = { credit_assessment: 'Credit assessment', loan_monitoring: 'Loan monitoring', model_research: 'Model research / training' };
export const BASES = { not_recorded: 'Permission evidence not recorded', consent_record: 'Referenced consent record', lender_authority_record: 'Referenced lender authority record' };
export const STATES = { recorded: 'Dated permission reference recorded', recorded_no_expiry: 'Expiry date not recorded', missing: 'Permission evidence missing', expired: 'Recorded expiry has passed', withdrawn: 'Withdrawal recorded' };
const FIELDS = ['loan_amount_pkr', 'tenure_months', 'monthly_digital_payments', 'payment_history_score', 'inventory_turnover', 'order_consistency', 'existing_debt_pkr', 'cash_flow_proxy', 'years_in_operation', 'num_employees'];
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const uniqueMembers = (values, allowed) => Array.isArray(values) && values.length > 0 && new Set(values).size === values.length && values.every(v => allowed.includes(v));

export function blankEvidence() {
  return { source_kind: '', source_reference: '', captured_on: '', period_from: '', period_to: '', input_fields: [],
    permission_basis: 'not_recorded', permission_reference: '', permission_on: '', permission_expires_on: '', purposes: ['credit_assessment'], note: '' };
}

export function evidenceDraft(row) {
  return Object.fromEntries(Object.keys(blankEvidence()).map(key => [key, row[key] ?? '']));
}

export function evidencePayload(form) {
  return { ...form, input_fields: [...form.input_fields].sort(), purposes: [...form.purposes].sort(),
    source_reference: form.source_reference.trim(), note: form.note.trim(), period_from: form.period_from || null, period_to: form.period_to || null,
    permission_reference: form.permission_basis === 'not_recorded' ? null : form.permission_reference.trim(),
    permission_on: form.permission_basis === 'not_recorded' ? null : form.permission_on || null,
    permission_expires_on: form.permission_basis === 'not_recorded' ? null : form.permission_expires_on || null };
}

export function validEvidenceRow(row, applicationId) {
  if (!row || row.application_id !== Number(applicationId) || !Number.isSafeInteger(row.id) || row.id < 1 ||
      !Number.isSafeInteger(row.revision) || row.revision < 1 || !uuid(row.stream_key) ||
      !Object.hasOwn(SOURCE_KINDS, row.source_kind) || !Object.hasOwn(BASES, row.permission_basis) || !Object.hasOwn(STATES, row.status) ||
      !['recorded', 'withdrawn'].includes(row.event_kind) || (row.event_kind === 'withdrawn') !== (row.status === 'withdrawn') ||
      typeof row.source_reference !== 'string' || typeof row.note !== 'string' || typeof row.created_by !== 'string' ||
      !isoDate(row.captured_on) || !uniqueMembers(row.input_fields, FIELDS) || !uniqueMembers(row.purposes, Object.keys(PURPOSES)) ||
      !Array.isArray(row.flags) || row.flags.some(flag => typeof flag !== 'string') || !row.input_snapshot ||
      Object.keys(row.input_snapshot).length !== row.input_fields.length ||
      row.input_fields.some(field => !Number.isFinite(row.input_snapshot[field]))) return false;
  if (row.permission_basis !== 'not_recorded' && (!isoDate(row.permission_on) || typeof row.permission_reference !== 'string')) return false;
  if (row.event_kind === 'recorded') {
    if (row.permission_basis === 'not_recorded' && row.status !== 'missing') return false;
    if (row.permission_basis !== 'not_recorded' && (row.status === 'missing' ||
      (!row.permission_expires_on && row.status !== 'recorded_no_expiry') || (row.permission_expires_on && row.status === 'recorded_no_expiry'))) return false;
  }
  return !row.permission_expires_on || isoDate(row.permission_expires_on);
}

export function validEvidenceReport(data, applicationId) {
  return Boolean(data && data.application_id === Number(applicationId) && data.training_authorised === false && data.data_access_granted === false &&
    isoDate(data.as_of_date) && Array.isArray(data.limits) && data.limits.every(l => typeof l === 'string') &&
    Number.isSafeInteger(data.total) && data.total >= 0 && data.total <= 50 && Number.isSafeInteger(data.offset) && data.offset >= 0 &&
    Array.isArray(data.rows) && data.rows.length <= 10 && data.rows.every(row => validEvidenceRow(row, applicationId)) &&
    new Set(data.rows.map(row => row.stream_key)).size === data.rows.length &&
    data.counts && Object.keys(STATES).every(state => Number.isSafeInteger(data.counts[state]) && data.counts[state] >= 0) &&
    Object.values(data.counts).reduce((a, b) => a + b, 0) === data.total &&
    Array.isArray(data.field_coverage) && data.field_coverage.length === FIELDS.length &&
    new Set(data.field_coverage.map(f => f.field)).size === FIELDS.length && data.field_coverage.every(f => FIELDS.includes(f.field) &&
      typeof f.label === 'string' && Number.isFinite(f.saved_value) && Number.isSafeInteger(f.source_records) && f.source_records >= 0 && f.source_records <= data.total &&
      Number.isSafeInteger(f.dated_permission_record_count) && f.dated_permission_record_count >= 0 && f.dated_permission_record_count <= f.source_records));
}

export function validEvidenceHistory(data, applicationId, streamKey) {
  return Boolean(data && data.application_id === applicationId && data.stream_key === streamKey && isoDate(data.as_of_date) &&
    Number.isSafeInteger(data.total) && data.total > 0 && Number.isSafeInteger(data.offset) && data.offset >= 0 &&
    Array.isArray(data.rows) && data.rows.length > 0 && data.rows.length <= 20 &&
    data.rows.every(row => row.stream_key === streamKey && validEvidenceRow(row, applicationId)) &&
    new Set(data.rows.map(row => row.id)).size === data.rows.length);
}
