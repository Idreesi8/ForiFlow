import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiErrorMessage, explainApplication } from "../api/client.js";
import { formatPKRCompact } from "../lib/format.js";
import { DecisionBadge } from "./common/Badges.jsx";
import { EmptyState, ErrorState, LoadingState } from "./common/States.jsx";

const POSITIVE_COLOR = "#059669";
const NEGATIVE_COLOR = "#e11d48";

/** Render each raw feature value in the unit a credit officer expects. */
function formatFeatureValue(feature, value) {
  const amount = Number(value);
  if (Number.isNaN(amount)) return "—";

  switch (feature) {
    case "monthly_digital_payments":
      return formatPKRCompact(amount);
    case "payment_history_score":
    case "order_consistency":
      return `${amount.toFixed(0)} / 100`;
    case "inventory_turnover":
      return `${amount.toFixed(1)}x per year`;
    case "years_in_operation":
      return `${amount.toFixed(1)} years`;
    case "num_employees":
      return `${amount.toFixed(0)} employees`;
    case "loan_affordability":
      return `${(amount * 100).toFixed(1)}% of monthly cash flow`;
    case "debt_burden":
      return `${(amount * 100).toFixed(1)}% of annual cash flow`;
    default:
      return amount.toFixed(2);
  }
}

function ContributionTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0].payload;

  return (
    <div className="max-w-xs rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold text-slate-900">{item.label}</p>
      <p className="mt-1 text-slate-600">
        Observed: <span className="font-medium">{item.formattedValue}</span>
      </p>
      <p className="text-slate-600">
        Model weight: <span className="font-medium">{(item.weight * 100).toFixed(0)}%</span>
      </p>
      <p
        className={`mt-1 font-semibold ${
          item.contribution >= 0 ? "text-emerald-700" : "text-rose-700"
        }`}
      >
        {item.contribution >= 0 ? "Adds" : "Removes"}{" "}
        {Math.abs(item.contribution).toFixed(2)} points
      </p>
    </div>
  );
}

function ValueLabel({ x, y, width, height, value }) {
  const positive = value >= 0;
  // Recharts may report a negative width for bars left of the zero line, so
  // normalise the edges before placing the label outside the bar.
  const leftEdge = Math.min(x, x + width);
  const rightEdge = Math.max(x, x + width);
  const textX = positive ? rightEdge + 6 : leftEdge - 6;

  return (
    <text
      x={textX}
      y={y + height / 2}
      dy={4}
      textAnchor={positive ? "start" : "end"}
      className="tabular text-[11px] font-semibold"
      fill={positive ? POSITIVE_COLOR : NEGATIVE_COLOR}
    >
      {`${positive ? "+" : ""}${Number(value).toFixed(2)}`}
    </text>
  );
}

/**
 * Horizontal SHAP contribution chart for one application.
 *
 * Contributions are additive: base value + every bar reconstructs the final
 * score, which is the identity the backend guarantees and asserts in tests.
 * Pass `explanation` to render a payload you already have, or `applicationId`
 * to fetch it from `POST /explain/{id}`.
 */
export default function ShapWaterfall({
  applicationId,
  explanation: providedExplanation = null,
  compact = false,
}) {
  const [explanation, setExplanation] = useState(providedExplanation);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadExplanation = useCallback(async () => {
    if (!applicationId) return;
    setIsLoading(true);
    setError(null);
    try {
      setExplanation(await explainApplication(applicationId));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the SHAP explanation."));
      setExplanation(null);
    } finally {
      setIsLoading(false);
    }
  }, [applicationId]);

  useEffect(() => {
    if (providedExplanation) {
      setExplanation(providedExplanation);
      setError(null);
      return;
    }
    loadExplanation();
  }, [providedExplanation, loadExplanation]);

  const chartData = useMemo(() => {
    if (!explanation?.feature_contributions) return [];
    return [...explanation.feature_contributions]
      .sort((a, b) => b.contribution - a.contribution)
      .map((item) => ({
        ...item,
        formattedValue: formatFeatureValue(item.feature, item.value),
      }));
  }, [explanation]);

  if (isLoading) return <LoadingState label="Generating SHAP explanation…" />;
  if (error) return <ErrorState message={error} onRetry={loadExplanation} />;

  if (!explanation) {
    return (
      <EmptyState
        title="No explanation selected"
        description="Pick an application to see which factors drove its credit decision."
      />
    );
  }

  const positiveTotal = chartData
    .filter((item) => item.contribution > 0)
    .reduce((sum, item) => sum + item.contribution, 0);
  const negativeTotal = chartData
    .filter((item) => item.contribution < 0)
    .reduce((sum, item) => sum + item.contribution, 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-slate-900">
            {explanation.business_name}
          </p>
          <p className="text-xs text-slate-500">
            Application #{explanation.application_id}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DecisionBadge decision={explanation.decision} />
          <div className="text-right">
            <p className="tabular text-2xl leading-none font-bold text-slate-900">
              {Number(explanation.risk_score).toFixed(1)}
            </p>
            <p className="text-[11px] tracking-wide text-slate-500 uppercase">Score</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <SummaryTile label="Base value" value={Number(explanation.base_value).toFixed(1)} />
        <SummaryTile
          label="Positive impact"
          value={`+${positiveTotal.toFixed(1)}`}
          tone="positive"
        />
        <SummaryTile
          label="Negative impact"
          value={negativeTotal.toFixed(1)}
          tone="negative"
        />
        <SummaryTile
          label="Final score"
          value={Number(explanation.risk_score).toFixed(1)}
          emphasis
        />
      </div>

      <div style={{ height: Math.max(240, chartData.length * (compact ? 34 : 42) + 48) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 8, right: 52, bottom: 8, left: 52 }}
            barCategoryGap={compact ? 6 : 10}
          >
            <CartesianGrid horizontal={false} stroke="#e2e8f0" strokeDasharray="3 3" />
            <XAxis
              type="number"
              // Always keep zero in view so every bar grows from the reference
              // line, even when all contributions share one sign. Whole-number
              // bounds keep the generated ticks free of floating point noise.
              domain={[
                (dataMin) => Math.floor(Math.min(0, dataMin * 1.25)),
                (dataMax) => Math.ceil(Math.max(0, dataMax * 1.25)),
              ]}
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickLine={false}
              axisLine={{ stroke: "#cbd5e1" }}
              label={{
                value: "Impact on score (points)",
                position: "insideBottom",
                offset: -4,
                style: { fontSize: 11, fill: "#94a3b8" },
              }}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={compact ? 170 : 210}
              tick={{ fontSize: 11, fill: "#334155" }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<ContributionTooltip />} cursor={{ fill: "#f1f5f9" }} />
            <ReferenceLine x={0} stroke="#0f172a" strokeWidth={1.5} />
            <Bar dataKey="contribution" radius={[3, 3, 3, 3]} maxBarSize={22}>
              {chartData.map((item) => (
                <Cell
                  key={item.feature}
                  fill={item.contribution >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR}
                />
              ))}
              <LabelList dataKey="contribution" content={<ValueLabel />} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <FactorList
          title="Strengths"
          factors={explanation.top_positive_factors}
          tone="positive"
        />
        <FactorList
          title="Concerns"
          factors={explanation.top_negative_factors}
          tone="negative"
        />
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
        <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
          Credit file narrative
        </p>
        <p className="mt-1 text-sm text-slate-700">{explanation.narrative}</p>
        <p className="mt-2 text-xs text-slate-500 italic">{explanation.compliance_note}</p>
      </div>
    </div>
  );
}

function SummaryTile({ label, value, tone, emphasis = false }) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-700"
      : tone === "negative"
        ? "text-rose-700"
        : "text-slate-900";

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        emphasis ? "border-brand-200 bg-brand-50" : "border-slate-200 bg-white"
      }`}
    >
      <p className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">
        {label}
      </p>
      <p className={`tabular mt-0.5 text-lg font-bold ${toneClass}`}>{value}</p>
    </div>
  );
}

function FactorList({ title, factors, tone }) {
  const isPositive = tone === "positive";
  const items = factors ?? [];

  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        isPositive ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50"
      }`}
    >
      <p
        className={`text-xs font-semibold tracking-wide uppercase ${
          isPositive ? "text-emerald-800" : "text-rose-800"
        }`}
      >
        {title}
      </p>
      {items.length ? (
        <ul className="mt-2 space-y-1">
          {items.map((factor) => (
            <li key={factor} className="flex items-start gap-2 text-sm text-slate-700">
              <span aria-hidden="true" className={isPositive ? "text-emerald-600" : "text-rose-600"}>
                {isPositive ? "▲" : "▼"}
              </span>
              {factor}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-500">None identified.</p>
      )}
    </div>
  );
}
