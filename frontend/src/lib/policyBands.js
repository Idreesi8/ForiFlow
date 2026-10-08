/**
 * Pure helpers for drawing a credit policy's score bands.
 *
 * Nothing here knows any cut-off. Every function takes the bands it should
 * draw, as the API returns them (`decline_max_score`, `manual_review_max_score`):
 *   - for a stored application, its own policy snapshot (`application.policy.bands`),
 *     so a newly activated policy never redraws an old assessment;
 *   - for anything about the present (an empty dial, the portfolio histogram),
 *     the active policy from `GET /policy/active` or `histogram_bands`.
 * The recommendation itself is always the API's; these helpers only draw.
 */

/** Band order, low score to high: Decline, Manual Review, Approve. */
export const BAND_KEYS = ["Rejected", "Manual Review", "Approved"];

/** Normalise an API bands object; `null` when it is missing or inconsistent. */
export function normaliseBands(bands) {
  if (!bands) return null;
  const decline = Number(bands.decline_max_score);
  const review = Number(bands.manual_review_max_score);
  if (!Number.isFinite(decline) || !Number.isFinite(review)) return null;
  if (!(decline >= 0 && decline < review && review <= 100)) return null;
  return { decline, review };
}

/** Which band a score falls in: 0 Decline, 1 Manual Review, 2 Approve. */
export function bandIndexForScore(score, bands) {
  const cut = normaliseBands(bands);
  const value = Number(score);
  if (!cut || !Number.isFinite(value)) return null;
  if (value <= cut.decline) return 0;
  if (value <= cut.review) return 1;
  return 2;
}

function formatEdge(value) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "");
}

/**
 * The three arcs of a 0-100 dial: each band's share of the scale and its range
 * label. Shares add up to exactly 100.
 */
export function bandSegments(bands) {
  const cut = normaliseBands(bands);
  if (!cut) return null;
  const { decline, review } = cut;
  return [
    { key: BAND_KEYS[0], from: 0, to: decline, span: decline, range: `0 – ${formatEdge(decline)}` },
    {
      key: BAND_KEYS[1],
      from: decline,
      to: review,
      span: review - decline,
      range: `> ${formatEdge(decline)} – ${formatEdge(review)}`,
    },
    { key: BAND_KEYS[2], from: review, to: 100, span: 100 - review, range: `> ${formatEdge(review)}` },
  ];
}

/** Short description of a set of bands, e.g. "Decline ≤ 45 · Approve > 74". */
export function describeBands(bands) {
  const cut = normaliseBands(bands);
  if (!cut) return "";
  return `Decline ≤ ${formatEdge(cut.decline)} · Manual Review ≤ ${formatEdge(cut.review)} · Approve > ${formatEdge(cut.review)}`;
}

/** Which band a histogram bar is drawn in, from the band the API gave it. */
export function bandIndexForRiskBand(riskBand) {
  return { "High Risk": 0, "Medium Risk": 1, "Low Risk": 2 }[riskBand] ?? null;
}
