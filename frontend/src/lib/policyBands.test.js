// Run with `npm test` (Node's built-in test runner; no extra packages).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bandIndexForRiskBand,
  bandIndexForScore,
  bandSegments,
  describeBands,
  normaliseBands,
} from "./policyBands.js";

const POLICY_A = { decline_max_score: 40, manual_review_max_score: 70 };
const POLICY_B = { decline_max_score: 45, manual_review_max_score: 74 };

test("policy A (40 / 70) puts scores in the bands the API uses", () => {
  const cases = [[0, 0], [40, 0], [40.01, 1], [45, 1], [70, 1], [70.01, 2], [74, 2], [100, 2]];
  for (const [score, band] of cases) assert.equal(bandIndexForScore(score, POLICY_A), band, `score ${score}`);
});

test("policy B (45 / 74) moves the same scores into other bands", () => {
  const cases = [[40, 0], [45, 0], [45.01, 1], [70.01, 1], [74, 1], [74.01, 2], [75, 2]];
  for (const [score, band] of cases) assert.equal(bandIndexForScore(score, POLICY_B), band, `score ${score}`);
});

test("dial arcs follow the policy and always cover 0-100", () => {
  const a = bandSegments(POLICY_A);
  assert.deepEqual(a.map((s) => [s.from, s.to]), [[0, 40], [40, 70], [70, 100]]);
  assert.deepEqual(a.map((s) => s.range), ["0 – 40", "> 40 – 70", "> 70"]);

  const b = bandSegments(POLICY_B);
  assert.deepEqual(b.map((s) => [s.from, s.to]), [[0, 45], [45, 74], [74, 100]]);
  assert.deepEqual(b.map((s) => s.span), [45, 29, 26]);
  assert.deepEqual(b.map((s) => s.range), ["0 – 45", "> 45 – 74", "> 74"]);
  for (const segments of [a, b]) {
    assert.equal(segments.reduce((sum, s) => sum + s.span, 0), 100);
    assert.deepEqual(segments.map((s) => s.key), ["Rejected", "Manual Review", "Approved"]);
  }
});

test("fractional cut-offs are labelled exactly", () => {
  const segments = bandSegments({ decline_max_score: 42.5, manual_review_max_score: 71.25 });
  assert.deepEqual(segments.map((s) => s.range), ["0 – 42.5", "> 42.5 – 71.25", "> 71.25"]);
  assert.equal(describeBands(POLICY_B), "Decline ≤ 45 · Manual Review ≤ 74 · Approve > 74");
});

test("missing or inconsistent bands draw nothing rather than a guess", () => {
  for (const bad of [null, undefined, {}, { decline_max_score: 70, manual_review_max_score: 40 },
    { decline_max_score: 40, manual_review_max_score: 101 }, { decline_max_score: "x", manual_review_max_score: 70 }]) {
    assert.equal(normaliseBands(bad), null);
    assert.equal(bandSegments(bad), null);
    assert.equal(bandIndexForScore(50, bad), null);
  }
});

test("histogram bars are coloured by the band the API assigned", () => {
  assert.equal(bandIndexForRiskBand("High Risk"), 0);
  assert.equal(bandIndexForRiskBand("Medium Risk"), 1);
  assert.equal(bandIndexForRiskBand("Low Risk"), 2);
  assert.equal(bandIndexForRiskBand(undefined), null);
});
