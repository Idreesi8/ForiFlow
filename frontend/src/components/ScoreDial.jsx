import { useMemo } from "react";
import { Cell, Pie, PieChart } from "recharts";

import { SCORE_BANDS, bandForDecision, bandForScore } from "../lib/decisions.js";

/**
 * Semi-circular credit score gauge (0-100) drawn with Recharts.
 *
 * The outer ring shows the three policy bands (red 0-40 Rejected, yellow 41-70
 * Manual Review, green 71-100 Approved), the inner arc fills up to the score
 * and the needle points at the exact value. The needle and hub are drawn in an
 * overlay SVG so the geometry stays pixel-exact at any `size`.
 */
export default function ScoreDial({
  score,
  decision,
  riskBand,
  size = 280,
  caption,
  showLegend = true,
}) {
  const hasScore = score !== null && score !== undefined && !Number.isNaN(Number(score));
  const value = hasScore ? Math.min(100, Math.max(0, Number(score))) : 0;
  const band = decision ? bandForDecision(decision) : bandForScore(value);

  const geometry = useMemo(() => {
    const outerRadius = size / 2 - 6;
    const centerX = size / 2;
    const centerY = outerRadius + 6;
    return {
      width: size,
      height: centerY + 26,
      centerX,
      centerY,
      outerRadius,
      bandInnerRadius: outerRadius * 0.78,
      arcOuterRadius: outerRadius * 0.71,
      arcInnerRadius: outerRadius * 0.61,
      needleLength: outerRadius * 0.7,
      hubRadius: Math.max(6, outerRadius * 0.06),
    };
  }, [size]);

  // 0 points due west (180°), 100 points due east (0°).
  const needleAngle = Math.PI * (1 - value / 100);
  const tipX = geometry.centerX + geometry.needleLength * Math.cos(needleAngle);
  const tipY = geometry.centerY - geometry.needleLength * Math.sin(needleAngle);
  const baseOffset = geometry.hubRadius * 0.62;
  const baseX = Math.cos(needleAngle + Math.PI / 2) * baseOffset;
  const baseY = -Math.sin(needleAngle + Math.PI / 2) * baseOffset;

  const bandData = SCORE_BANDS.map((item) => ({
    name: item.decision,
    value: item.max - item.min + (item.min === 0 ? 0 : 1),
  }));
  const progressData = [
    { name: "score", value },
    { name: "remainder", value: 100 - value },
  ];

  return (
    <div className="flex flex-col items-center">
      <div
        className="relative"
        style={{ width: geometry.width, height: geometry.height }}
        role="img"
        aria-label={
          hasScore
            ? `Credit score ${value.toFixed(1)} out of 100, ${decision ?? band.decision}`
            : "Credit score not available"
        }
      >
        <PieChart width={geometry.width} height={geometry.height}>
          <Pie
            data={bandData}
            dataKey="value"
            cx={geometry.centerX}
            cy={geometry.centerY}
            startAngle={180}
            endAngle={0}
            innerRadius={geometry.bandInnerRadius}
            outerRadius={geometry.outerRadius}
            paddingAngle={1}
            stroke="none"
            isAnimationActive={false}
          >
            {SCORE_BANDS.map((item) => (
              <Cell
                key={item.decision}
                fill={item.color}
                fillOpacity={hasScore && item.decision !== band.decision ? 0.28 : 1}
              />
            ))}
          </Pie>

          <Pie
            data={progressData}
            dataKey="value"
            cx={geometry.centerX}
            cy={geometry.centerY}
            startAngle={180}
            endAngle={0}
            innerRadius={geometry.arcInnerRadius}
            outerRadius={geometry.arcOuterRadius}
            stroke="none"
            cornerRadius={4}
          >
            <Cell fill={hasScore ? band.color : "#cbd5e1"} />
            <Cell fill="#f1f5f9" />
          </Pie>
        </PieChart>

        <svg
          className="pointer-events-none absolute inset-0"
          width={geometry.width}
          height={geometry.height}
          aria-hidden="true"
        >
          {hasScore ? (
            <polygon
              points={`${geometry.centerX + baseX},${geometry.centerY + baseY} ${
                geometry.centerX - baseX
              },${geometry.centerY - baseY} ${tipX},${tipY}`}
              fill="#0f172a"
            />
          ) : null}
          <circle
            cx={geometry.centerX}
            cy={geometry.centerY}
            r={geometry.hubRadius}
            fill="#0f172a"
          />
          <circle
            cx={geometry.centerX}
            cy={geometry.centerY}
            r={geometry.hubRadius * 0.4}
            fill="#ffffff"
          />
        </svg>

        <span
          className="tabular absolute text-xs font-medium text-slate-400"
          style={{ left: 2, top: geometry.centerY + 6 }}
        >
          0
        </span>
        <span
          className="tabular absolute text-xs font-medium text-slate-400"
          style={{ right: 2, top: geometry.centerY + 6 }}
        >
          100
        </span>
      </div>

      {/* The readout sits under the arc so the needle never crosses the digits. */}
      {hasScore ? (
        <div className="flex flex-col items-center gap-1.5">
          <span className="flex items-baseline gap-1">
            <span className="tabular text-4xl leading-none font-bold text-slate-900">
              {value.toFixed(1)}
            </span>
            <span className="text-sm font-medium text-slate-400">/ 100</span>
          </span>
          <span
            className={`badge px-3 py-1.5 text-sm ${band.badgeClass}`}
            data-testid="score-decision"
          >
            {decision ?? band.decision}
          </span>
          <span className="text-xs font-medium text-slate-500">
            {riskBand ?? band.riskBand}
          </span>
        </div>
      ) : (
        <p className="mt-1 text-sm text-slate-500">Awaiting assessment</p>
      )}

      {caption ? (
        <p className="mt-2 max-w-xs text-center text-xs text-slate-500">{caption}</p>
      ) : null}

      {showLegend ? (
        <ul className="mt-4 grid w-full max-w-sm grid-cols-3 gap-2 text-center">
          {SCORE_BANDS.map((item) => {
            const isActive = hasScore && item.decision === band.decision;
            return (
              <li
                key={item.decision}
                className={`rounded-lg border px-2 py-2 transition ${
                  isActive
                    ? `${item.bgClass} ${item.borderClass}`
                    : "border-slate-200 bg-white"
                }`}
              >
                <span className="flex items-center justify-center gap-1.5">
                  <span
                    className={`h-2 w-2 rounded-full ${item.dotClass}`}
                    aria-hidden="true"
                  />
                  <span className="tabular text-xs font-semibold text-slate-700">
                    {item.range}
                  </span>
                </span>
                <span
                  className={`mt-0.5 block text-[11px] font-medium ${
                    isActive ? item.textClass : "text-slate-500"
                  }`}
                >
                  {item.decision}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
