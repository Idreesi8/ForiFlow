import assert from "node:assert/strict";
import test from "node:test";

import { resilienceView } from "./statementView.js";

const evidence = {
  source_sha256: "a".repeat(64),
  matches_statement: true,
  resilience: {
    method_version: "principal-stress-v1",
    monthly_principal_pkr: 25000,
    scenarios: [0, 10, 20, 30].map((decline, index) => ({
      inflow_decline_percent: decline, months_observed: 6,
      months_covering_principal: index < 2 ? 6 : 0,
      median_remainder_pkr: 15000 - 10000 * index,
      lowest_remainder_pkr: 15000 - 10000 * index,
    })),
  },
};

test("scenario figures and counts come from stored evidence unchanged", () => {
  const view = resilienceView(evidence);
  assert.strictEqual(view.scenarios, evidence.resilience.scenarios);
  assert.equal(view.scenarios[2].median_remainder_pkr, -5000);
  assert.equal(view.sourceFingerprint, evidence.source_sha256);
  assert.equal(view.matchesStatement, true);
});

test("compact view selects recorded and twenty-percent-lower scenarios without rewriting them", () => {
  const view = resilienceView(evidence, true);
  assert.deepEqual(view.scenarios, [evidence.resilience.scenarios[0], evidence.resilience.scenarios[2]]);
  assert.equal(evidence.resilience.scenarios.length, 4);
});

test("old files and unsupported methods do not invent a cash-flow check", () => {
  assert.equal(resilienceView(null), null);
  assert.equal(resilienceView({ months: [] }), null);
  assert.equal(resilienceView({ resilience: { ...evidence.resilience, method_version: "future" } }), null);
});

test("edited turnover stays explicitly distinguishable from statement evidence", () => {
  assert.equal(resilienceView({ ...evidence, matches_statement: false }).matchesStatement, false);
});

test("impossible or non-finite counts and values are not displayed as valid results", () => {
  for (const changes of [{ months_covering_principal: 7 }, { months_observed: 0 },
    { months_covering_principal: -1 }, { median_remainder_pkr: NaN },
    { lowest_remainder_pkr: Infinity }, { months_covering_principal: 1.5 }]) {
    const invalid = { ...evidence, resilience: { ...evidence.resilience,
      scenarios: [{ ...evidence.resilience.scenarios[0], ...changes }] } };
    assert.equal(resilienceView(invalid), null);
  }
});
