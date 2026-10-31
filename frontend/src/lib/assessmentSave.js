import { assessmentPayload } from './assessmentIntake.js';

/** Numeric spelling and surrounding whitespace do not make a new assessment. */
export function assessmentIntent(values, statement) {
  return JSON.stringify([assessmentPayload(values), statement?.csv ?? null]);
}

/** Verify the save receipt belongs to the figures reviewed in this tab. */
export function assessmentReceiptMatches(receipt, payload) {
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt)) return false;
  const explanation = receipt.explanation;
  return Number.isSafeInteger(receipt.application_id) && receipt.application_id > 0 &&
    receipt.applicant_name === payload.applicant_name && receipt.business_name === payload.business_name &&
    receipt.loan_amount_pkr === payload.loan_amount_pkr && receipt.tenure_months === payload.tenure_months &&
    Number.isFinite(receipt.risk_score) && receipt.risk_score >= 0 && receipt.risk_score <= 100 &&
    Number.isFinite(receipt.monthly_installment_pkr) && receipt.monthly_installment_pkr > 0 &&
    ['Approved', 'Manual Review', 'Rejected'].includes(receipt.decision) &&
    ['Low Risk', 'Medium Risk', 'High Risk'].includes(receipt.risk_band) &&
    Boolean(explanation && explanation.application_id === receipt.application_id &&
      Number.isFinite(explanation.base_value) && typeof explanation.narrative === 'string' &&
      Array.isArray(explanation.feature_contributions) && explanation.feature_contributions.every(item =>
        item && typeof item.feature === 'string' && typeof item.label === 'string' && Number.isFinite(item.contribution)));
}

export function assessmentSaveUncertain(error) {
  const status = error?.response?.status;
  return !status || status === 408 || status >= 500;
}
