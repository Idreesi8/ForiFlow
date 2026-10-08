import {
  baselineRows,
  ensembleVerdict,
  performanceTiles,
  shortHash,
  subgroupStatus,
  thresholdComparison,
} from "../lib/modelView.js";
import { formatCount, formatPercent } from "../lib/format.js";

/**
 * The first things the Model page answers, from `GET /model/card`: what model,
 * on what data, how good on a set it never saw, against what baselines, and
 * what it must not be used for.
 */

const lowerFirst = (text) => text.charAt(0).toLowerCase() + text.slice(1);

export function DemoModelNotice({ card }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="note">
      <p className="font-semibold">Demonstration model</p>
      <p className="mt-1">
        Trained on {lowerFirst(card?.status?.dataset_type ?? "Public consumer credit data")}. It is not
        validated for Pakistani SME lending and must not be used for autonomous credit
        decisions. An officer decides every application.
      </p>
    </div>
  );
}

export function ModelStatusCard({ card }) {
  const status = card.status ?? {};
  const split = status.split?.rows;
  const rows = [
    ["Active model version", card.serving_model_version],
    ["Serving engine", card.serving_engine === "ml" ? "Trained ensemble" : `Fallback formula (${card.serving_fallback_reason ?? "pinned"})`],
    ["Dataset type", status.dataset_type],
    ["Training dataset", status.dataset_identifier],
    ["Dataset SHA-256", shortHash(status.dataset_sha256)],
    ["Training date", status.trained_at ? status.trained_at.replace("T", " ") : "—"],
    ["Artifact fingerprint", shortHash(card.serving_artifact_sha256)],
    [
      "Split (seed)",
      split
        ? `${formatCount(split.train)} train · ${formatCount(split.validation)} validation · ${formatCount(split.final_test)} final test (seed ${status.random_seed})`
        : "—",
    ],
  ];
  return (
    <section className="card min-w-0" data-testid="model-status">
      <div className="card-header">
        <h3 className="card-title">Model status</h3>
        <span className="text-xs text-slate-500">protocol {status.training_protocol_version ?? "pre-2.2"}</span>
      </div>
      <dl className="grid gap-x-6 gap-y-2 px-5 py-4 text-sm sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3 border-b border-slate-100 pb-1">
            <dt className="text-slate-500">{label}</dt>
            <dd className="text-right font-medium break-all text-slate-900">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {card.serving_engine !== "ml" ? (
        <p className="border-t border-slate-200 px-5 py-3 text-xs text-amber-800">
          The fallback formula is scoring right now; the figures below describe the trained model on file.
        </p>
      ) : null}
    </section>
  );
}

export function PerformanceTiles({ card }) {
  const tiles = performanceTiles(card);
  if (!tiles.length) return null;
  return (
    <section data-testid="model-performance">
      <p className="mb-2 text-xs text-slate-500">
        Final test set ({formatCount(card.performance.final_test_raw.rows)} loans), measured once.
        Nothing was tuned on it.
      </p>
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {tiles.map((tile) => (
          <div key={tile.key} className="card px-4 py-3">
            <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{tile.label}</p>
            <p className="tabular mt-1 text-2xl font-bold text-slate-900">{tile.value}</p>
            <p className="mt-1 text-xs text-slate-500">{tile.hint}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ThresholdsSection({ card, policy }) {
  const view = thresholdComparison(card, policy);
  return (
    <section className="grid gap-4 md:grid-cols-2" data-testid="threshold-separation">
      {[view.model, view.policy].map((block) => (
        <div key={block.title} className="card min-w-0 px-5 py-4">
          <h3 className="card-title">{block.title}</h3>
          <dl className="mt-3 space-y-1 text-sm">
            {block.rows.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3">
                <dt className="text-slate-500">{label}</dt>
                <dd className="tabular font-semibold text-slate-900">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs text-slate-500">{block.note}</p>
        </div>
      ))}
    </section>
  );
}

export function BaselineSection({ card }) {
  const rows = baselineRows(card);
  if (!rows.length) return null;
  const verdict = ensembleVerdict(rows);
  return (
    <section className="card min-w-0" data-testid="baseline-comparison">
      <div className="card-header">
        <h3 className="card-title">Baseline comparison</h3>
        <span className="text-xs text-slate-500">same split, same train-only preprocessing</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
              <th className="px-5 py-3 font-medium">Model</th>
              <th className="px-3 py-3 text-right font-medium">ROC-AUC</th>
              <th className="px-3 py-3 text-right font-medium">PR-AUC</th>
              <th className="px-3 py-3 text-right font-medium">F1</th>
              <th className="px-3 py-3 text-right font-medium">Brier (raw)</th>
              <th className="px-3 py-3 text-right font-medium">CV AUC (train)</th>
              <th className="px-5 py-3 text-right font-medium">vs ensemble</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={row.name} className={row.isServed ? "bg-brand-50" : undefined}>
                <td className="px-5 py-3 font-medium text-slate-900">{row.label}</td>
                <td className="tabular px-3 py-3 text-right">{row.finalTest.auc_roc.toFixed(4)}</td>
                <td className="tabular px-3 py-3 text-right">{row.finalTest.pr_auc.toFixed(3)}</td>
                <td className="tabular px-3 py-3 text-right">{row.finalTest.f1.toFixed(3)}</td>
                <td className="tabular px-3 py-3 text-right">{row.finalTest.brier.toFixed(3)}</td>
                <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                  {row.cvAuc !== null ? (
                    <>
                      {row.cvAuc.toFixed(4)}
                      <span className="text-slate-400"> ± {row.cvAucStd.toFixed(4)}</span>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="tabular px-5 py-3 text-right whitespace-nowrap">
                  {row.isServed ? "served" : `${row.gap >= 0 ? "+" : "−"}${Math.abs(row.gap).toFixed(4)}`}
                  {row.pairedP !== null ? (
                    <span className="ml-1 text-xs text-slate-500">p {row.pairedP.toFixed(3)}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-600">
        <p className="font-semibold text-slate-800">{verdict.summary}</p>
        <ul className="mt-1 list-disc pl-5">
          {verdict.lines.map((line) => (
            <li key={line.name}>{line.text}</li>
          ))}
        </ul>
        <p className="mt-1 text-slate-500">
          Final-test columns: one measurement. CV: 5 folds on the training split; p is a paired
          t-test over folds (approximate, folds share rows). Raw Brier is high for every model
          trained on 50/50 SMOTE data; see calibration.
        </p>
      </div>
    </section>
  );
}

export function CalibrationSummary({ card }) {
  const c = card.calibration;
  if (!c) return null;
  const briers = c.selection?.brier_out_of_fold ?? {};
  return (
    <section className="card min-w-0 px-5 py-4" data-testid="calibration-summary">
      <h3 className="card-title">Calibration (display only)</h3>
      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {[
          ["Method", c.method ?? "none"],
          ["Chosen and fitted on", c.fitted_on ? `${c.fitted_on.set} split (${formatCount(c.fitted_on.rows)} loans)` : "—"],
          ["Brier, raw (final test)", c.brier_raw_final_test?.toFixed(4)],
          ["Brier, calibrated (final test)", c.brier_calibrated_final_test?.toFixed(4)],
          ["Brier, no-skill (final test)", c.brier_no_skill_final_test?.toFixed(4)],
          ["ECE raw → calibrated", c.ece_raw_final_test !== undefined && c.ece_raw_final_test !== null
            ? `${c.ece_raw_final_test.toFixed(3)} → ${c.ece_calibrated_final_test.toFixed(3)}` : "—"],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3">
            <dt className="text-slate-500">{label}</dt>
            <dd className="tabular font-semibold text-slate-900">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-slate-500">
        Chosen by out-of-fold Brier within the validation split (
        {Object.entries(briers)
          .map(([name, value]) => `${name} ${value.toFixed(4)}`)
          .join(", ")}
        ). {c.note}
      </p>
    </section>
  );
}

export function DataQualityCard({ card }) {
  const q = card.data_quality;
  if (!q) return null;
  const missing = Object.entries(q.missing_values ?? {});
  return (
    <section className="card min-w-0 px-5 py-4" data-testid="data-quality">
      <h3 className="card-title">Training data quality</h3>
      <p className="mt-1 text-xs font-semibold text-amber-800">{q.dataset_type}</p>
      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        {[
          ["Rows in file", formatCount(q.rows_in_file)],
          ["Columns in file", q.columns_in_file],
          ["Model features", q.model_features],
          ["Default rate", formatPercent(q.target_positive_rate)],
          ["Exact duplicate rows (excluded)", formatCount(q.duplicate_rows)],
          ["Columns with missing values", missing.length],
        ].map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3">
            <dt className="text-slate-500">{label}</dt>
            <dd className="tabular font-semibold text-slate-900">{value ?? "—"}</dd>
          </div>
        ))}
      </dl>
      {missing.length ? (
        <p className="mt-2 text-xs text-slate-500">
          Missing: {missing.map(([name, row]) => `${name} ${formatPercent(row.share)}`).join(", ")}. Imputed with
          training-split medians where the model uses the column.
        </p>
      ) : null}
    </section>
  );
}

export function LimitationsCard({ card }) {
  return (
    <section className="card min-w-0 px-5 py-4" data-testid="model-limitations">
      <h3 className="card-title">Limitations</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
        {(card.limitations ?? []).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">Full model card: {card.model_card}</p>
    </section>
  );
}

export function SubgroupSection({ audit }) {
  return (
    <div className="space-y-4 border-t border-slate-200 pt-6" data-testid="subgroup-analysis">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Subgroup Performance Analysis</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          {audit.protocol} {audit.interpretation}
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        {audit.attributes.map((block) => (
          <div key={block.attribute} className="card min-w-0">
            <div className="card-header">
              <h3 className="card-title">{block.attribute}</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-[11px] tracking-wide text-slate-500 uppercase">
                    <th className="px-4 py-2 font-medium">Group</th>
                    <th className="px-2 py-2 text-right font-medium">Loans</th>
                    <th className="px-2 py-2 text-right font-medium">Default rate</th>
                    <th className="px-2 py-2 text-right font-medium">ROC-AUC</th>
                    <th className="px-2 py-2 text-right font-medium">Precision</th>
                    <th className="px-2 py-2 text-right font-medium">Recall</th>
                    <th className="px-4 py-2 font-medium">Sample</th>
                  </tr>
                </thead>
                <tbody>
                  {block.groups.map((row) => {
                    const sufficient = subgroupStatus(row) === "Sufficient";
                    return (
                      <tr key={row.group} className="border-b border-slate-100 last:border-0">
                        <td className="px-4 py-2 font-medium text-slate-900">{row.group}</td>
                        <td className="tabular px-2 py-2 text-right">{formatCount(row.rows)}</td>
                        <td className="tabular px-2 py-2 text-right">{formatPercent(row.observed_default_rate)}</td>
                        <td className="tabular px-2 py-2 text-right">{sufficient && row.auc_roc !== null ? row.auc_roc.toFixed(3) : "—"}</td>
                        <td className="tabular px-2 py-2 text-right">{sufficient && row.precision !== null ? formatPercent(row.precision) : "—"}</td>
                        <td className="tabular px-2 py-2 text-right">{sufficient && row.recall !== null ? formatPercent(row.recall) : "—"}</td>
                        <td className="px-4 py-2">
                          <span className={`badge ${sufficient ? "bg-slate-100 text-slate-700 ring-1 ring-slate-200" : "bg-amber-50 text-amber-900 ring-1 ring-amber-200"}`}>
                            {subgroupStatus(row)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500">{block.note}</p>
          </div>
        ))}
      </div>
      <div className="card px-5 py-4 text-sm text-slate-700">
        <p className="font-semibold text-slate-900">Not analysed</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {audit.not_audited.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
