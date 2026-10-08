// Run with `npm test` (Node's built-in test runner; no extra packages).
import assert from "node:assert/strict";
import { test } from "node:test";

import { contractSummary, unusedFieldNames } from "./featureContract.js";
import {
  baselineRows,
  ensembleVerdict,
  performanceTiles,
  shortHash,
  subgroupStatus,
  thresholdComparison,
} from "./modelView.js";

const metrics = (auc, extra = {}) => ({
  rows: 1000, positives: 220, auc_roc: auc, pr_auc: 0.56, precision: 0.48, recall: 0.62,
  f1: 0.55, brier: 0.18, threshold: 0.5, ...extra,
});

const CARD = {
  performance: { final_test_raw: metrics(0.7748), final_test_calibrated: metrics(0.7746, { brier: 0.13 }) },
  evaluation_thresholds: {
    raw_probability: 0.5,
    band_cutoffs: { decline_max_score: 40, manual_review_max_score: 70 },
    note: "Fixed in advance.",
  },
  policy_note: "Policy is separate.",
  baselines: {
    logistic_regression: { label: "Logistic regression", final_test: metrics(0.763), auc_gap_to_ensemble: -0.0118 },
    xgboost: { label: "XGBoost alone", final_test: metrics(0.7744), auc_gap_to_ensemble: -0.0004 },
    random_forest: { label: "Random forest alone", final_test: metrics(0.7732), auc_gap_to_ensemble: -0.0016 },
    ensemble: { label: "Served ensemble", final_test: metrics(0.7748), auc_gap_to_ensemble: 0 },
  },
  baseline_cross_validation: {
    logistic_regression: { auc_roc_mean: 0.7619, auc_roc_std: 0.006, vs_served: { paired_t_test_p: 0.001 } },
    xgboost: { auc_roc_mean: 0.7737, auc_roc_std: 0.007, vs_served: { paired_t_test_p: 0.4 } },
    random_forest: { auc_roc_mean: 0.7719, auc_roc_std: 0.008, vs_served: { paired_t_test_p: 0.02 } },
    served_ensemble_xgb_rf: { auc_roc_mean: 0.7743, auc_roc_std: 0.007, vs_served: null },
  },
};

test("performance tiles come from the final test set and name the threshold", () => {
  const tiles = performanceTiles(CARD);
  assert.deepEqual(tiles.map((t) => t.label), ["ROC-AUC", "PR-AUC", "Precision", "Recall", "F1", "Brier score"]);
  assert.equal(tiles[0].value, "0.7748");
  assert.match(tiles[2].hint, /raw PD ≥ 0.5/);
  assert.equal(tiles[5].value, "0.1300");
  assert.match(tiles[5].hint, /raw 0.1800/);
  assert.deepEqual(performanceTiles({}), []);
});

test("model evaluation thresholds are shown apart from the credit policy", () => {
  const policy = { name: "Pilot Credit Policy", version: "1.1", decline_max_score: 45, manual_review_max_score: 74 };
  const view = thresholdComparison(CARD, policy);
  assert.equal(view.model.title, "Model Evaluation Thresholds");
  assert.equal(view.policy.title, "Current Credit Policy Thresholds");
  assert.deepEqual(view.model.rows[1], ["Score bands used in evaluation tables", "40 / 70"]);
  assert.deepEqual(view.policy.rows[1], ["Decline at or below score", 45]);
  assert.equal(thresholdComparison(CARD, null).policy.rows[0][1], "not loaded");
});

test("baselines keep their order and the ensemble's verdict is honest", () => {
  const rows = baselineRows(CARD);
  assert.deepEqual(rows.map((r) => r.name), ["logistic_regression", "xgboost", "random_forest", "ensemble"]);
  assert.equal(rows[3].isServed, true);
  const verdict = ensembleVerdict(rows);
  const byName = Object.fromEntries(verdict.lines.map((l) => [l.name, l]));
  assert.equal(byName.logistic_regression.meaningful, true);
  assert.equal(byName.xgboost.meaningful, false); // p = 0.4: a tie
  assert.match(byName.xgboost.text, /\+0.0004 AUC/);
  assert.match(verdict.summary, /some baselines and not over others/);

  const allTies = ensembleVerdict(rows.map((r) => ({ ...r, pairedP: r.isServed ? null : 0.6 })));
  assert.match(allTies.summary, /no statistically clear gain/);
});

test("subgroup status falls back to insufficient", () => {
  assert.equal(subgroupStatus({ sample_status: "Sufficient" }), "Sufficient");
  assert.equal(subgroupStatus({ sample_status: "Insufficient sample size" }), "Insufficient sample size");
  assert.equal(subgroupStatus({}), "Insufficient sample size");
});

test("hashes are shortened, not invented", () => {
  assert.equal(shortHash("a".repeat(64)), `${"a".repeat(12)}…`);
  assert.equal(shortHash(null), "—");
});

test("the form marks unused fields from the serving model's contract", () => {
  const fallback = ["tenure_months", "num_employees"];
  assert.deepEqual([...unusedFieldNames(null, fallback)], fallback);
  const ml = {
    engine: "ml",
    model_features: [{ label: "Facility size vs annual turnover" }, { label: "Years in operation" }],
    collected_unused: [{ name: "inventory_turnover" }, { name: "existing_debt_pkr" }],
  };
  assert.deepEqual([...unusedFieldNames(ml, fallback)], ["inventory_turnover", "existing_debt_pkr"]);
  assert.deepEqual([...unusedFieldNames({ engine: "surrogate", collected_unused: [] }, fallback)], []);
  assert.match(contractSummary(ml), /reads 2 features/);
  assert.match(contractSummary({ engine: "surrogate" }), /fallback formula/);
});
