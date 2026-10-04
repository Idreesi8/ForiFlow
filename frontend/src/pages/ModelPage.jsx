import { useCallback, useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiErrorMessage, fetchModelComparison, fetchModelEvaluation } from "../api/client.js";
import { bandForDecision } from "../lib/decisions.js";
import { formatCount, formatPercent, formatSigned } from "../lib/format.js";
import { ErrorState, LoadingState } from "../components/common/States.jsx";

// Series colours, checked for colour-blind separation. The red / amber / green
// of the policy bands are status colours and are not reused for series.
const MODEL_COLOR = "#2d8560";
const RAW_COLOR = "#7c3aed";
const AXIS_TICK = { fontSize: 11, fill: "#64748b" };
const TOOLTIP_STYLE = { fontSize: 12, borderRadius: 8 };

const MODEL_LABELS = {
  served_ensemble_xgb_rf: "XGBoost + Random Forest (served)",
  xgboost_only: "XGBoost alone",
  lightgbm: "LightGBM",
  random_forest_only: "Random Forest alone",
  mlp_neural_network: "Neural network (MLP)",
  logistic_regression: "Logistic regression",
};

/**
 * How the served model performs on loans it never saw, and against the models
 * it was chosen over. Every figure comes from `ml.evaluate_model` and
 * `ml.compare_models`; nothing here is computed from the live portfolio.
 */
export default function ModelPage() {
  const [evaluation, setEvaluation] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [evaluationData, comparisonData] = await Promise.all([
        fetchModelEvaluation(),
        // The comparison is optional: the page still works without it.
        fetchModelComparison().catch(() => null),
      ]);
      setEvaluation(evaluationData);
      setComparison(comparisonData);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the model evaluation."));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (isLoading) return <LoadingState label="Loading model evaluation…" />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const hold = evaluation.holdout;
  const matrix = hold.confusion_at_half;

  return (
    <div className="min-w-0 space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Model performance</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          The served model on the {formatCount(evaluation.rows.holdout)} hold-out loans it
          never saw during training ({formatPercent(evaluation.default_rate.holdout)} of
          them defaulted). This is the public training file, not a Pakistani SME
          portfolio, so a bank must re-measure on its own loans.
        </p>
      </div>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="AUC-ROC"
          value={hold.raw.auc_roc.toFixed(4)}
          hint="0.5 is a coin toss, 1.0 is perfect"
        />
        <StatTile
          label="Defaulters caught"
          value={formatPercent(matrix.recall_default)}
          hint={`${formatCount(matrix.true_positive)} of ${formatCount(
            matrix.true_positive + matrix.false_negative,
          )} at score 50 or below`}
        />
        <StatTile
          label="Good payers passed"
          value={formatPercent(matrix.recall_non_default)}
          hint={`${formatCount(matrix.true_negative)} of ${formatCount(
            matrix.true_negative + matrix.false_positive,
          )} above score 50`}
        />
        <StatTile
          label="Brier score, calibrated"
          value={hold.calibrated.brier.toFixed(4)}
          hint={`raw ${hold.raw.brier.toFixed(4)} · no-skill ${hold.brier_no_skill.toFixed(4)} · lower is better`}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">ROC curve</h3>
            <span className="text-xs text-slate-500">
              area under the curve {hold.raw.auc_roc.toFixed(4)}
            </span>
          </div>
          <div className="px-5 py-4" style={{ height: 340 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={hold.roc_curve} margin={{ top: 10, right: 16, bottom: 24, left: 4 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="fpr"
                  domain={[0, 1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1]}
                  tickFormatter={(value) => `${Math.round(value * 100)}%`}
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={{ stroke: "#cbd5e1" }}
                  label={{
                    value: "Good payers wrongly flagged",
                    position: "insideBottom",
                    offset: -14,
                    fontSize: 12,
                    fill: "#475569",
                  }}
                />
                <YAxis
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1]}
                  tickFormatter={(value) => `${Math.round(value * 100)}%`}
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  label={{
                    value: "Defaulters caught",
                    angle: -90,
                    position: "insideLeft",
                    offset: 8,
                    fontSize: 12,
                    fill: "#475569",
                    style: { textAnchor: "middle" },
                  }}
                />
                <ReferenceLine
                  segment={[
                    { x: 0, y: 0 },
                    { x: 1, y: 1 },
                  ]}
                  stroke="#94a3b8"
                  strokeDasharray="5 5"
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelFormatter={(value) => `Good payers wrongly flagged: ${formatPercent(value)}`}
                  formatter={(value) => [formatPercent(value), "Defaulters caught"]}
                />
                <Line
                  type="linear"
                  dataKey="tpr"
                  stroke={MODEL_COLOR}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            The dashed line is a model with no skill. The further the curve bends to
            the top left, the better the model separates defaulters from good payers.
          </p>
        </div>

        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Calibration</h3>
            <span className="text-xs text-slate-500">predicted against what happened</span>
          </div>
          <div className="px-5 py-4" style={{ height: 340 }}>
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 10, right: 16, bottom: 24, left: 4 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="predicted"
                  domain={[0, 1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1]}
                  tickFormatter={(value) => `${Math.round(value * 100)}%`}
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={{ stroke: "#cbd5e1" }}
                  label={{
                    value: "Predicted probability of default",
                    position: "insideBottom",
                    offset: -14,
                    fontSize: 12,
                    fill: "#475569",
                  }}
                />
                <YAxis
                  type="number"
                  dataKey="observed"
                  domain={[0, 1]}
                  ticks={[0, 0.25, 0.5, 0.75, 1]}
                  tickFormatter={(value) => `${Math.round(value * 100)}%`}
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  label={{
                    value: "Loans that defaulted",
                    angle: -90,
                    position: "insideLeft",
                    offset: 8,
                    fontSize: 12,
                    fill: "#475569",
                    style: { textAnchor: "middle" },
                  }}
                />
                <ReferenceLine
                  segment={[
                    { x: 0, y: 0 },
                    { x: 1, y: 1 },
                  ]}
                  stroke="#94a3b8"
                  strokeDasharray="5 5"
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  cursor={{ strokeDasharray: "3 3" }}
                  formatter={(value, name) => [
                    formatPercent(value),
                    name === "predicted" ? "Predicted" : "Defaulted",
                  ]}
                />
                <Legend verticalAlign="top" height={28} iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Scatter
                  name="Raw model"
                  data={hold.reliability_raw}
                  fill={RAW_COLOR}
                  line={{ stroke: RAW_COLOR, strokeWidth: 2 }}
                  shape="diamond"
                  isAnimationActive={false}
                />
                <Scatter
                  name="After calibration"
                  data={hold.reliability_calibrated}
                  fill={MODEL_COLOR}
                  line={{ stroke: MODEL_COLOR, strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            On the dashed line, predicted equals actual. The raw model predicts{" "}
            {formatPercent(hold.raw.mean_predicted)} on average because SMOTE trains it on
            balanced data; after calibration it predicts{" "}
            {formatPercent(hold.calibrated.mean_predicted)}, against{" "}
            {formatPercent(evaluation.default_rate.holdout)} that really defaulted.
          </p>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Confusion matrix</h3>
            <span className="text-xs text-slate-500">flagging score 50 or below</span>
          </div>
          <div className="px-5 py-5">
            <ConfusionMatrix matrix={matrix} />
          </div>
        </div>

        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Default rate by policy band</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">Band</th>
                  <th className="px-3 py-3 text-right font-medium">Loans</th>
                  <th className="px-3 py-3 text-right font-medium">Share</th>
                  <th className="px-3 py-3 text-right font-medium">Defaulted</th>
                  <th className="px-5 py-3 text-right font-medium">Calibrated PD</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {hold.bands.map((row) => (
                  <tr key={row.band}>
                    <td className="px-5 py-3">
                      <span className={`badge ${bandForDecision(row.band).badgeClass}`}>
                        {row.band}
                      </span>
                    </td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.rows)}</td>
                    <td className="tabular px-3 py-3 text-right">{formatPercent(row.share)}</td>
                    <td className="tabular px-3 py-3 text-right font-semibold text-slate-900">
                      {formatPercent(row.observed_default_rate)}
                    </td>
                    <td className="tabular px-5 py-3 text-right">
                      {formatPercent(row.calibrated_pd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            "Defaulted" is what happened in the hold-out. "Calibrated PD" is what the
            model predicted for the same loans.
          </p>
        </div>
      </section>

      <section className="card min-w-0">
        <div className="card-header">
          <h3 className="card-title">Where to set the threshold</h3>
          <span className="text-xs text-slate-500">
            each row flags every loan at or below that score
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                <th className="px-5 py-3 font-medium">Flag at or below</th>
                <th className="px-3 py-3 text-right font-medium">Defaulters caught</th>
                <th className="px-3 py-3 text-right font-medium">Good payers passed</th>
                <th className="px-3 py-3 text-right font-medium">Flags that defaulted</th>
                <th className="px-5 py-3 text-right font-medium">Accuracy</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {hold.thresholds.map((row) => (
                <tr key={row.flag_score_at_or_below}>
                  <td className="tabular px-5 py-3 font-semibold text-slate-900">
                    Score {row.flag_score_at_or_below}
                    {row.flag_score_at_or_below === 40 ? (
                      <span className="ml-2 text-xs font-normal text-slate-500">Rejected band</span>
                    ) : null}
                    {row.flag_score_at_or_below === 70 ? (
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        Rejected + Manual Review
                      </span>
                    ) : null}
                  </td>
                  <td className="tabular px-3 py-3 text-right">{formatPercent(row.recall_default)}</td>
                  <td className="tabular px-3 py-3 text-right">
                    {formatPercent(row.recall_non_default)}
                  </td>
                  <td className="tabular px-3 py-3 text-right">
                    {formatPercent(row.precision_default)}
                  </td>
                  <td className="tabular px-5 py-3 text-right">{formatPercent(row.accuracy)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
          A lower threshold misses more defaulters; a higher one turns away more good
          payers. Accuracy alone misleads here, because{" "}
          {formatPercent(1 - evaluation.default_rate.holdout)} of loans are good: a model
          that flags nobody would already be that accurate.
        </p>
      </section>

      {comparison ? <ComparisonTable comparison={comparison} /> : null}

      <p className="text-xs text-slate-500">{evaluation.protocol}</p>
    </div>
  );
}

function StatTile({ label, value, hint }) {
  return (
    <div className="card px-5 py-4">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className="tabular mt-1 text-2xl font-bold text-slate-900">{value}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

function ConfusionMatrix({ matrix }) {
  const total =
    matrix.true_positive + matrix.false_positive + matrix.false_negative + matrix.true_negative;
  const cell = (count, label, correct) => (
    <td
      className={`border border-slate-200 px-4 py-4 text-center ${
        correct ? "bg-brand-50" : "bg-white"
      }`}
    >
      <p className="tabular text-xl font-bold text-slate-900">{formatCount(count)}</p>
      <p className="text-xs text-slate-600">{label}</p>
      <p className="tabular text-xs text-slate-500">{formatPercent(count / total)} of all loans</p>
    </td>
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            <th className="w-32" />
            <th className="px-3 pb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">
              Model flagged
            </th>
            <th className="px-3 pb-2 text-xs font-medium tracking-wide text-slate-500 uppercase">
              Model passed
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="pr-3 text-right text-xs font-medium tracking-wide text-slate-500 uppercase">
              Defaulted
            </th>
            {cell(matrix.true_positive, "Caught", true)}
            {cell(matrix.false_negative, "Missed", false)}
          </tr>
          <tr>
            <th className="pr-3 text-right text-xs font-medium tracking-wide text-slate-500 uppercase">
              Paid back
            </th>
            {cell(matrix.false_positive, "Wrongly flagged", false)}
            {cell(matrix.true_negative, "Correctly passed", true)}
          </tr>
        </tbody>
      </table>
      <p className="mt-3 text-xs text-slate-500">
        Shaded cells are correct. Of the loans the model flagged,{" "}
        {formatPercent(matrix.precision_default)} really defaulted.
      </p>
    </div>
  );
}

function ComparisonTable({ comparison }) {
  const rows = Object.entries(comparison.models)
    .map(([key, model]) => ({ key, ...model }))
    .sort((a, b) => b.auc_roc_mean - a.auc_roc_mean);

  return (
    <section className="card min-w-0">
      <div className="card-header">
        <h3 className="card-title">Alternatives we tested</h3>
        <span className="text-xs text-slate-500">
          same {formatCount(comparison.rows)} loans, same 5 folds, same pipeline
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
              <th className="px-5 py-3 font-medium">Model</th>
              <th className="px-3 py-3 text-right font-medium">AUC-ROC</th>
              <th className="px-3 py-3 text-right font-medium">PR-AUC</th>
              <th className="px-3 py-3 text-right font-medium">F1</th>
              <th className="px-3 py-3 text-right font-medium">Gap to served</th>
              <th className="px-3 py-3 text-right font-medium">p-value</th>
              <th className="px-3 py-3 text-right font-medium">ms / score</th>
              <th className="px-5 py-3 font-medium">Monotone</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => {
              const isServed = row.key === "served_ensemble_xgb_rf";
              const versus = row.vs_served;
              return (
                <tr key={row.key} className={isServed ? "bg-brand-50" : undefined}>
                  <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">
                    {MODEL_LABELS[row.key] ?? row.key}
                  </td>
                  <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                    {row.auc_roc_mean.toFixed(4)}
                    <span className="text-slate-400"> ± {row.auc_roc_std.toFixed(4)}</span>
                  </td>
                  <td className="tabular px-3 py-3 text-right">{row.pr_auc_mean.toFixed(3)}</td>
                  <td className="tabular px-3 py-3 text-right">{row.f1_mean.toFixed(3)}</td>
                  <td className="tabular px-3 py-3 text-right">
                    {versus ? formatSigned(-versus.mean_auc_difference, 4) : "—"}
                  </td>
                  <td className="tabular px-3 py-3 text-right whitespace-nowrap">
                    {versus ? (
                      <>
                        {versus.paired_t_test_p.toFixed(4)}
                        <span className="ml-1 text-xs text-slate-500">
                          {versus.paired_t_test_p < 0.05 ? "real gap" : "tie"}
                        </span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="tabular px-3 py-3 text-right">
                    {row.single_row_predict_ms_median.toFixed(2)}
                  </td>
                  <td className="px-5 py-3 text-xs text-slate-600">{row.monotone}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        "Gap to served" is that model's AUC minus the served model's. The p-value is a
        paired t-test over the 5 folds: below 0.05 the gap is real, above it the two
        models tie. The folds share training rows, so treat the test as approximate.
      </p>
    </section>
  );
}
