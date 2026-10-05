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

import {
  apiErrorMessage,
  fetchDrift,
  fetchEarlyWarningModel,
  fetchFairness,
  fetchModelComparison,
  fetchModelEvaluation,
} from "../api/client.js";
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
  const [earlyWarning, setEarlyWarning] = useState(null);
  const [drift, setDrift] = useState(null);
  const [fairness, setFairness] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [
        evaluationData,
        comparisonData,
        earlyWarningData,
        driftData,
        fairnessData,
      ] = await Promise.all([
        fetchModelEvaluation(),
        // The rest are optional: the page still works without them.
        fetchModelComparison().catch(() => null),
        fetchEarlyWarningModel().catch(() => null),
        fetchDrift().catch(() => null),
        fetchFairness().catch(() => null),
      ]);
      setFairness(fairnessData);
      setDrift(driftData);
      setEvaluation(evaluationData);
      setComparison(comparisonData);
      setEarlyWarning(earlyWarningData);
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

      {fairness ? <FairnessSection audit={fairness} /> : null}

      {drift ? <DriftSection drift={drift} /> : null}

      {earlyWarning ? <EarlyWarningSection chain={earlyWarning} /> : null}
    </div>
  );
}

/** How the model's default probability for a group compares with what happened. */
function pricingOf(row) {
  if (row.small_group) return { label: "too few loans", tone: "bg-slate-100 text-slate-600 ring-1 ring-slate-200" };
  if (!row.gap_beyond_noise) return { label: "in line", tone: "bg-slate-100 text-slate-700 ring-1 ring-slate-200" };
  return row.calibration_gap > 0
    ? { label: "too harsh", tone: "bg-amber-50 text-amber-900 ring-1 ring-amber-200" }
    : { label: "too lenient", tone: "bg-violet-50 text-violet-900 ring-1 ring-violet-200" };
}

function FairnessSection({ audit }) {
  const worst = audit.attributes.reduce((a, b) => (b.largest_gap > a.largest_gap ? b : a));
  return (
    <div className="space-y-4 border-t border-slate-200 pt-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Group audit</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          The model never reads age, income, housing or loan purpose. This checks whether
          it still treats those groups differently, on the same{" "}
          {formatCount(audit.rows)} hold-out loans. Two tests: is a group approved at under{" "}
          {formatPercent(audit.four_fifths, 0)} of the best group's rate, and does the
          default probability the model gives a group match the default rate the group
          really had? The second is the one that shows unfair treatment. "Too harsh"
          means the model overstates the group's risk; "too lenient" means it understates
          it.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {audit.attributes.map((block) => (
          <div key={block.attribute} className="card min-w-0">
            <div className="card-header">
              <h3 className="card-title">{block.attribute}</h3>
              <span className="text-xs text-slate-500">
                approval compared with: {block.reference_group}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-xs">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-[11px] tracking-wide text-slate-500 uppercase">
                    <th className="px-4 py-2 font-medium">Group</th>
                    <th className="px-2 py-2 text-right font-medium">Loans</th>
                    <th className="px-2 py-2 text-right font-medium">Approved</th>
                    <th className="px-2 py-2 text-right font-medium">Model PD</th>
                    <th className="px-2 py-2 text-right font-medium">Defaulted</th>
                    <th className="px-4 py-2 font-medium">Pricing</th>
                  </tr>
                </thead>
                <tbody>
                  {block.groups.map((row) => {
                    const pricing = pricingOf(row);
                    return (
                      <tr key={row.group} className="border-b border-slate-100 last:border-0">
                        <td className="px-4 py-2 font-medium text-slate-900">{row.group}</td>
                        <td className="tabular px-2 py-2 text-right text-slate-600">
                          {formatCount(row.rows)}
                        </td>
                        <td className="tabular px-2 py-2 text-right whitespace-nowrap">
                          {formatPercent(row.approval_rate)}
                          <span
                            className={`ml-1 ${
                              row.below_four_fifths ? "font-semibold text-rose-700" : "text-slate-500"
                            }`}
                          >
                            ({row.approval_ratio.toFixed(2)})
                          </span>
                        </td>
                        <td className="tabular px-2 py-2 text-right">
                          {formatPercent(row.predicted_default_rate)}
                        </td>
                        <td className="tabular px-2 py-2 text-right font-semibold text-slate-900">
                          {formatPercent(row.observed_default_rate)}
                        </td>
                        <td className="px-4 py-2">
                          <span className={`badge ${pricing.tone}`}>{pricing.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
              {block.note}
            </p>
          </div>
        ))}
      </div>

      <div className="card px-5 py-4 text-sm text-slate-700">
        <p className="font-semibold text-slate-900">How to read this</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            The figure in brackets is the group's approval rate divided by the best group's.
            Below {audit.four_fifths.toFixed(2)} it is shown in red. A low ratio is a reason
            to look, not proof of unfairness: a group that defaults more should be approved
            less.
          </li>
          <li>
            Where "Model PD" and "Defaulted" differ by more than the group's size explains,
            the model is missing something that matters for that group. {worst.attribute}{" "}
            shows it most, with a gap of up to {formatPercent(worst.largest_gap)}.
          </li>
          <li>
            A group under {audit.min_group_rows} loans gets no verdict.
          </li>
        </ul>
        <p className="mt-3 font-semibold text-slate-900">Not audited</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {audit.not_audited.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

const DRIFT_VERDICT = {
  stable: "bg-emerald-100 text-emerald-800 ring-1 ring-emerald-200",
  watch: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
  shifted: "bg-rose-100 text-rose-800 ring-1 ring-rose-200",
};

/**
 * Population drift: live applications against what the model was trained on.
 * Each quantity gets a PSI, the PSI chance alone would give at this sample
 * size, and a row of paired bars (training above, live below) per bin.
 */
function DriftSection({ drift }) {
  return (
    <div className="space-y-4 border-t border-slate-200 pt-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Population drift</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Are the {formatCount(drift.live_applications)} applications scored here still like
          the loans the model learned from? PSI below {drift.thresholds.watch.toFixed(2)} is
          stable, above {drift.thresholds.shift.toFixed(2)} a material shift. A shift means
          the model needs re-validating, not that the applicants are worse. With fewer than{" "}
          {drift.min_rows_for_verdict} applications no verdict is given, because chance alone
          moves PSI that much.
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        {drift.quantities.map((row) => (
          <div key={row.name} className="card min-w-0 px-5 py-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-slate-900">{row.label}</p>
              <span className="flex items-center gap-2 text-xs text-slate-500">
                {row.psi !== null ? (
                  <span className="tabular">
                    PSI <span className="font-semibold text-slate-900">{row.psi.toFixed(3)}</span>
                    {" · "}chance alone ≈ {row.noise_floor.toFixed(3)}
                  </span>
                ) : null}
                <span
                  className={`badge ${
                    DRIFT_VERDICT[row.verdict] ?? "bg-slate-100 text-slate-700 ring-1 ring-slate-200"
                  }`}
                >
                  {row.verdict}
                </span>
              </span>
            </div>
            <table className="mt-3 w-full text-xs">
              <tbody>
                {row.bins.map((bin, index) => (
                  <tr key={bin}>
                    <td className="w-24 py-1 pr-2 whitespace-nowrap text-slate-600">{bin}</td>
                    <td className="py-1">
                      <ShareBar share={row.reference_shares[index]} color={MODEL_COLOR} />
                      <ShareBar share={row.live_shares[index]} color={RAW_COLOR} />
                    </td>
                    <td className="tabular w-28 py-1 pl-2 text-right whitespace-nowrap text-slate-600">
                      {formatPercent(row.reference_shares[index], 0)} →{" "}
                      <span className="font-semibold text-slate-900">
                        {row.psi !== null ? formatPercent(row.live_shares[index], 0) : "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: MODEL_COLOR }} /> Training data
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm" style={{ background: RAW_COLOR }} /> Applications
          scored here
        </span>
        <span>Share of each group in every bin; the figures read training → live.</span>
      </p>
    </div>
  );
}

function ShareBar({ share, color }) {
  return (
    <div className="my-0.5 h-2 w-full rounded-sm bg-slate-100">
      <div
        className="h-2 rounded-sm"
        style={{ width: `${Math.min(100, share * 100)}%`, background: color }}
      />
    </div>
  );
}

const EWS_MODEL_LABELS = {
  markov_first_order: "Markov chain, this month only (served)",
  markov_second_order: "Markov chain, this and last month",
  logistic_hazard: "Logistic hazard model",
  gradient_boosting_hazard: "Gradient boosting hazard model",
};

function EarlyWarningSection({ chain }) {
  const alternatives = chain.alternatives;
  const rows = Object.entries(alternatives.models).sort(
    ([, a], [, b]) => b.auc_roc - a.auc_roc,
  );

  return (
    <div className="space-y-6 border-t border-slate-200 pt-6">
      <div>
        <h2 className="text-xl font-bold text-slate-900">Early-warning model</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          A Markov chain: how often an account moves from one repayment state to
          another in a month. Fitted on {formatCount(chain.clients.train)} accounts and
          checked on {formatCount(chain.clients.holdout)} others. {chain.source}
        </p>
      </div>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Monthly transition matrix</h3>
            <span className="text-xs text-slate-500">from this month's state to next month's</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">From</th>
                  {chain.states.map((state) => (
                    <th key={state} className="px-3 py-3 text-right font-medium whitespace-nowrap">
                      {state}
                    </th>
                  ))}
                  <th className="px-5 py-3 text-right font-medium">Months seen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {chain.states.slice(0, -1).map((state, index) => (
                  <tr key={state}>
                    <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">{state}</td>
                    {chain.transition_matrix[index].map((value, column) => (
                      <td
                        key={chain.states[column]}
                        className={`tabular px-3 py-3 text-right ${
                          column === index ? "font-semibold text-slate-900" : ""
                        }`}
                      >
                        {formatPercent(value)}
                      </td>
                    ))}
                    <td className="tabular px-5 py-3 text-right text-slate-500">
                      {formatCount(
                        chain.transition_counts[index].reduce((sum, count) => sum + count, 0),
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            {chain.state_definition} ForiFlow's "Late 1-29" and "Late 30-59" both map to
            Late 1-59, because the data does not separate them.
          </p>
        </div>

        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">What monitoring reports</h3>
            <span className="text-xs text-slate-500">by the state of the latest month</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">State</th>
                  <th className="px-3 py-3 text-right font-medium">Default in 3 months</th>
                  <th className="px-3 py-3 text-right font-medium">In 12 months</th>
                  <th className="px-5 py-3 text-right font-medium">Days to default</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {chain.state_outlook.slice(0, -1).map((row) => (
                  <tr key={row.state}>
                    <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">
                      {row.state}
                    </td>
                    <td className="tabular px-3 py-3 text-right font-semibold text-slate-900">
                      {formatPercent(row.default_within_3_months)}
                    </td>
                    <td className="tabular px-3 py-3 text-right">
                      {formatPercent(row.default_within_12_months)}
                    </td>
                    <td className="tabular px-5 py-3 text-right">
                      {row.expected_days_to_default}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            "Days to default" is the average time to default for accounts that do default
            within {chain.outlook_months} months. An alert is raised at 10% or more in 3
            months, or when the score drops more than 15 points.
          </p>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-2">
        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Check on unseen accounts</h3>
            <span className="text-xs text-slate-500">default within 5 months of April</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">State in April</th>
                  <th className="px-3 py-3 text-right font-medium">Accounts</th>
                  <th className="px-3 py-3 text-right font-medium">Predicted</th>
                  <th className="px-5 py-3 text-right font-medium">Actual</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {chain.holdout_check.map((row) => (
                  <tr key={row.april_state}>
                    <td className="px-5 py-3 font-medium whitespace-nowrap text-slate-900">
                      {row.april_state}
                    </td>
                    <td className="tabular px-3 py-3 text-right">{formatCount(row.clients)}</td>
                    <td className="tabular px-3 py-3 text-right">
                      {formatPercent(row.predicted_default, 2)}
                    </td>
                    <td className="tabular px-5 py-3 text-right font-semibold text-slate-900">
                      {formatPercent(row.actual_default, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            The chain is close where it has many accounts. It under-predicts for accounts
            already 60-89 days late in April, a group of only{" "}
            {formatCount(chain.holdout_check[chain.holdout_check.length - 1].clients)}, so
            treat that row with care.
          </p>
        </div>

        <div className="card min-w-0">
          <div className="card-header">
            <h3 className="card-title">Alternatives we tested</h3>
            <span className="text-xs text-slate-500">
              {alternatives.target.toLowerCase()}, {formatCount(alternatives.holdout_defaults)}{" "}
              defaults in {formatCount(alternatives.holdout_client_months)} account-months
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
                  <th className="px-5 py-3 font-medium">Model</th>
                  <th className="px-3 py-3 text-right font-medium">AUC-ROC</th>
                  <th className="px-3 py-3 text-right font-medium">Brier</th>
                  <th className="px-5 py-3 text-right font-medium">AUC gap to served (95%)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map(([key, row]) => (
                  <tr key={key} className={key === "markov_first_order" ? "bg-brand-50" : undefined}>
                    <td className="px-5 py-3 font-medium text-slate-900">
                      {EWS_MODEL_LABELS[key] ?? key}
                    </td>
                    <td className="tabular px-3 py-3 text-right">{row.auc_roc.toFixed(4)}</td>
                    <td className="tabular px-3 py-3 text-right">{row.brier.toFixed(5)}</td>
                    <td className="tabular px-5 py-3 text-right whitespace-nowrap">
                      {key === "markov_first_order"
                        ? "—"
                        : `${formatSigned(row.auc_gap_to_served_95[0], 3)} to ${formatSigned(
                            row.auc_gap_to_served_95[1],
                            3,
                          )}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
            The hazard models rank accounts better than the served chain. They also need
            card utilisation and the share of the bill paid, which have no clean
            counterpart on a term loan, so they are measured here but not served. The
            old rule-based penalties rank accounts exactly like the chain, but give no
            probability.
          </p>
        </div>
      </section>
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
