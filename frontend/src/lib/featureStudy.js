const candidates = ['ensemble_smote', 'ensemble_smotenc', 'logistic_smotenc', 'engineered_logistic_smotenc'];
const features = ['loan_to_income', 'payment_history_score', 'years_in_operation'];
const finite = (value, lower, upper) => typeof value === 'number' && Number.isFinite(value) && value >= lower && value <= upper;
const count = value => Number.isInteger(value) && value >= 0;
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);

/** Withhold incomplete, nonfinite or differently scoped research responses. */
export function validFeatureStudy(data) {
  if (data?.version !== 'feature-research-v1' || data.status !== 'research_only' || data.folds !== 5
    || !count(data.training_rows) || data.training_rows === 0
    || !count(data.excluded_validation_rows) || !count(data.excluded_final_test_rows)
    || !hash(data.credit_artifact_sha256) || !hash(data.protocol_sha256)
    || typeof data.completed_at !== 'string' || !Number.isFinite(Date.parse(data.completed_at))) return false;
  if (!Array.isArray(data.candidates) || data.candidates.length !== 4 || data.candidates.some((row, index) => row.id !== candidates[index]
    || typeof row.label !== 'string' || !row.label.trim()
    || !['auc_roc_mean', 'auc_roc_std', 'pr_auc_mean', 'brier_mean'].every(key => finite(row[key], 0, 1))
    || !finite(row.paired_auc_delta, -1, 1))) return false;
  if (!Array.isArray(data.permutation) || data.permutation.length !== 3 || data.permutation.some((row, index) => row.name !== features[index] || !finite(row.mean_auc_drop, -1, 1))) return false;
  if (!Array.isArray(data.sampling) || data.sampling.length !== 2 || data.sampling.some((row, index) => row.id !== candidates[index]
    || !count(row.synthetic_rows) || !count(row.non_category_history_rows) || row.non_category_history_rows > row.synthetic_rows)) return false;
  return Array.isArray(data.engineered_features) && data.engineered_features.length === 5 && data.engineered_features.every(v => typeof v === 'string')
    && count(data.rows_in_conflicting_vectors) && data.rows_in_conflicting_vectors <= data.training_rows
    && count(data.unique_model_vectors) && data.unique_model_vectors > 0 && data.unique_model_vectors <= data.training_rows
    && Array.isArray(data.limitations) && data.limitations.length > 0 && data.limitations.every(v => typeof v === 'string');
}
