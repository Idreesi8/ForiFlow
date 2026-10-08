/**
 * Model page helpers (no React, so `npm test` can run them).
 *
 * Every number comes from the API (`GET /model/card`); nothing here decides a
 * threshold. Model evaluation thresholds and the credit policy thresholds are
 * kept apart on purpose: the first describe how the model was measured, the
 * second are a configurable lending policy.
 */

export function shortHash(sha, length = 12) {
  return typeof sha === "string" && sha.length > length ? `${sha.slice(0, length)}…` : sha ?? "—";
}

const fixed = (value, digits = 4) =>
  value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);

/** The headline metrics of the final test set, raw model unless stated. */
export function performanceTiles(card) {
  const raw = card?.performance?.final_test_raw;
  if (!raw) return [];
  const calibrated = card.performance.final_test_calibrated;
  const threshold = raw.threshold;
  return [
    { key: "auc_roc", label: "ROC-AUC", value: fixed(raw.auc_roc), hint: "ranking; 0.5 is a coin toss" },
    { key: "pr_auc", label: "PR-AUC", value: fixed(raw.pr_auc), hint: `default rate ${fixed(raw.positives / raw.rows, 3)} is the no-skill level` },
    { key: "precision", label: "Precision", value: fixed(raw.precision, 3), hint: `flagged at raw PD ≥ ${threshold}` },
    { key: "recall", label: "Recall", value: fixed(raw.recall, 3), hint: `defaulters flagged at raw PD ≥ ${threshold}` },
    { key: "f1", label: "F1", value: fixed(raw.f1, 3), hint: `at raw PD ≥ ${threshold}` },
    {
      key: "brier",
      label: "Brier score",
      value: fixed(calibrated?.brier ?? raw.brier),
      hint: calibrated ? `calibrated; raw ${fixed(raw.brier)}` : "raw model",
    },
  ];
}

/** "Model Evaluation Thresholds" next to "Current Credit Policy Thresholds". */
export function thresholdComparison(card, policy) {
  const evaluation = card?.evaluation_thresholds ?? {};
  const bands = evaluation.band_cutoffs ?? {};
  return {
    model: {
      title: "Model Evaluation Thresholds",
      rows: [
        ["Raw probability for precision / recall / F1", evaluation.raw_probability ?? "—"],
        [
          "Score bands used in evaluation tables",
          bands.decline_max_score !== undefined
            ? `${bands.decline_max_score} / ${bands.manual_review_max_score}`
            : "—",
        ],
      ],
      note:
        evaluation.note ??
        "Fixed before the results were seen; not optimised, and not a lending decision rule.",
    },
    policy: {
      title: "Current Credit Policy Thresholds",
      rows: policy
        ? [
            ["Policy version", `${policy.name ?? "Policy"} v${policy.version}`],
            ["Decline at or below score", policy.decline_max_score],
            ["Manual review at or below score", policy.manual_review_max_score],
          ]
        : [["Policy", "not loaded"]],
      note: card?.policy_note ?? "Configured on the Credit Policy page.",
    },
  };
}

const MODEL_ORDER = ["logistic_regression", "xgboost", "random_forest", "ensemble"];

/** Baselines against the served ensemble, on the final test set and in CV. */
export function baselineRows(card) {
  const baselines = card?.baselines ?? {};
  const cv = card?.baseline_cross_validation ?? {};
  const cvKey = (name) => (name === "ensemble" ? "served_ensemble_xgb_rf" : name);
  return MODEL_ORDER.filter((name) => baselines[name]).map((name) => {
    const row = baselines[name];
    const folds = cv[cvKey(name)] ?? {};
    return {
      name,
      label: row.label ?? name,
      isServed: name === "ensemble",
      finalTest: row.final_test,
      gap: row.auc_gap_to_ensemble,
      cvAuc: folds.auc_roc_mean ?? null,
      cvAucStd: folds.auc_roc_std ?? null,
      pairedP: folds.vs_served?.paired_t_test_p ?? null,
    };
  });
}

/**
 * Does the ensemble add anything over its simplest rivals? Read from the CV
 * paired test (p < 0.05) and the final-test AUC gap. Wording only.
 */
export function ensembleVerdict(rows) {
  const lines = rows
    .filter((row) => !row.isServed)
    .map((row) => {
      const gain = row.gap === null || row.gap === undefined ? null : -row.gap;
      const tie = row.pairedP !== null && row.pairedP >= 0.05;
      const sign = gain === null ? "" : gain >= 0 ? "+" : "−";
      const amount = gain === null ? "—" : `${sign}${Math.abs(gain).toFixed(4)}`;
      return {
        name: row.name,
        text: `vs ${row.label}: ${amount} AUC on the final test set${
          row.pairedP === null ? "" : `; cross-validation p = ${row.pairedP.toFixed(3)}`
        }`,
        meaningful: !tie && gain !== null && gain > 0,
      };
    });
  return {
    lines,
    summary: lines.every((line) => !line.meaningful)
      ? "The ensemble shows no statistically clear gain over these baselines."
      : lines.some((line) => !line.meaningful)
        ? "The ensemble's gain is clear over some baselines and not over others."
        : "The ensemble is ahead of every baseline in cross-validation.",
  };
}

/** Subgroup row status, as the API marked it. */
export function subgroupStatus(row) {
  return row?.sample_status === "Sufficient" ? "Sufficient" : "Insufficient sample size";
}
