import test from 'node:test';
import assert from 'node:assert/strict';
import { validFeatureStudy } from './featureStudy.js';

const ids = ['ensemble_smote', 'ensemble_smotenc', 'logistic_smotenc', 'engineered_logistic_smotenc'];
const report = { version: 'feature-research-v1', status: 'research_only', folds: 5, training_rows: 100,
  excluded_validation_rows: 20, excluded_final_test_rows: 20, credit_artifact_sha256: 'a'.repeat(64), protocol_sha256: 'b'.repeat(64), completed_at: '2026-10-28T09:00:00Z',
  candidates: ids.map(id => ({ id, label: id, auc_roc_mean: .75, auc_roc_std: .01, pr_auc_mean: .55, brier_mean: .18, paired_auc_delta: 0 })),
  permutation: ['loan_to_income', 'payment_history_score', 'years_in_operation'].map(name => ({ name, mean_auc_drop: .01 })),
  sampling: ids.slice(0, 2).map(id => ({ id, synthetic_rows: 80, non_category_history_rows: 0 })),
  engineered_features: ['one', 'two', 'three', 'four', 'five'], rows_in_conflicting_vectors: 10, unique_model_vectors: 50, limitations: ['Research only'] };

test('complete measured research is accepted', () => assert.equal(validFeatureStudy(report), true));
test('different scope, incomplete or repeated candidates are withheld', () => {
  for (const change of [r => r.status = 'promoted', r => r.candidates.pop(), r => r.candidates[1] = r.candidates[0], r => r.permutation.reverse(), r => r.folds = 4]) {
    const altered = structuredClone(report); change(altered); assert.equal(validFeatureStudy(altered), false);
  }
});
test('nonfinite and out of range metrics cannot be displayed', () => {
  for (const value of [NaN, Infinity, -1, 1.01, null, '0.75']) {
    const altered = structuredClone(report); altered.candidates[0].auc_roc_mean = value;
    assert.equal(validFeatureStudy(altered), false);
  }
});
test('invalid references and impossible counts are withheld', () => {
  for (const change of [r => r.credit_artifact_sha256 = 'wrong', r => r.completed_at = 'wrong', r => r.training_rows = 0,
    r => r.rows_in_conflicting_vectors = 101, r => r.sampling[0].non_category_history_rows = 81, r => r.unique_model_vectors = 0]) {
    const altered = structuredClone(report); change(altered); assert.equal(validFeatureStudy(altered), false);
  }
});
