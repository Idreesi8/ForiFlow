// Run with `npm test` (Node's built-in test runner; no extra packages).
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  alertActions,
  alertEvidence,
  alertSeverityStyle,
  alertStatusStyle,
  ewsStateStyle,
  formatDeterioration,
  isOpenAlert,
  scoreSourceLabel,
  stateCounts,
  timelineSourceLabel,
  trendChartData,
  trendMessage,
  trendStyle,
} from "./ews.js";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

const TREND_TWO = {
  observations: 2,
  min_observations: 3,
  direction: "Insufficient Data",
  message: "Insufficient history for multi-month trend",
  points: [
    { label: "Baseline", month_number: 0, score: 82.4, score_source: "origination_assessment" },
    { label: "Month 1", month_number: 1, score: 80.1, score_source: "ews_rule_adjusted", installment_status: "On Time" },
    { label: "Month 2", month_number: 2, score: 55, score_source: "officer_override", installment_status: "Late 30-59" },
  ],
};

test("each EWS state has its own label, apart from credit bands", () => {
  assert.deepEqual(
    ["NORMAL", "WATCH", "WARNING", "CRITICAL"].map((s) => ewsStateStyle(s).label),
    ["Normal", "Watch", "Warning", "Critical"],
  );
  assert.equal(ewsStateStyle(undefined).label, "Not monitored");
  for (const word of ["Low Risk", "Medium Risk", "High Risk", "Approve", "Decline"]) {
    assert.ok(!["NORMAL", "WATCH", "WARNING", "CRITICAL"].some((s) => ewsStateStyle(s).label === word));
  }
});

test("severity is the API's, never derived from the score drop", () => {
  assert.equal(alertSeverityStyle({ severity: "WARNING", score_drop: 95 }).label, "Warning");
  assert.equal(alertSeverityStyle({ severity: "CRITICAL", score_drop: 0.5 }).label, "Critical");
  const legacy = alertSeverityStyle({ severity: null, score_drop: 40 });
  assert.equal(legacy.label, "Legacy");
  assert.match(legacy.title, /before 2\.1/);
});

test("trend directions and the insufficient-data message", () => {
  assert.equal(trendStyle("Deteriorating").label, "Deteriorating");
  assert.equal(trendStyle("Improving").symbol, "↗");
  assert.equal(trendStyle("Insufficient Data").label, "Insufficient data");
  assert.equal(trendMessage(TREND_TWO), "Insufficient history for multi-month trend");
  assert.equal(trendMessage({ ...TREND_TWO, message: null, observations: 1 }), "Insufficient history for multi-month trend");
  assert.equal(trendMessage({ ...TREND_TWO, message: null, observations: 3 }), null);
});

test("chart data keeps the baseline apart and marks overrides", () => {
  const data = trendChartData(TREND_TWO);
  assert.deepEqual(data.map((p) => p.label), ["Baseline", "Month 1", "Month 2"]);
  assert.deepEqual(data.map((p) => p.isBaseline), [true, false, false]);
  assert.deepEqual(data.map((p) => p.isOverride), [false, false, true]);
  assert.deepEqual(trendChartData(null), []);
});

test("provenance labels never call a manual value a model score", () => {
  assert.equal(scoreSourceLabel("officer_override"), "Officer Override");
  assert.equal(scoreSourceLabel("officer_override", { short: true }), "Officer Override");
  assert.equal(scoreSourceLabel("latest_foriflow_assessment"), "ForiFlow Assessment");
  assert.match(scoreSourceLabel("ews_rule_adjusted"), /EWS rules/);
  assert.match(scoreSourceLabel("legacy_unknown"), /Unknown/);
  assert.equal(scoreSourceLabel("something_new"), "Unknown");
  assert.ok(!/ForiFlow/.test(scoreSourceLabel("officer_override")));
});

test("lifecycle: who sees which step, in which state", () => {
  const open = { alert_status: "Open", is_open: true };
  const acked = { alert_status: "Acknowledged", is_open: true };
  const action = { alert_status: "Action Required", is_open: true };
  const resolved = { alert_status: "Resolved", is_open: false };
  assert.deepEqual(alertActions(open, { canManage: true }), ["acknowledge", "assign", "due-date", "resolve", "dismiss"]);
  assert.deepEqual(alertActions(acked, { canManage: true }), ["action-required", "assign", "due-date", "resolve", "dismiss"]);
  assert.deepEqual(alertActions(action, { canManage: true }), ["assign", "due-date", "resolve", "dismiss"]);
  assert.deepEqual(alertActions(resolved, { canManage: true }), []);
  assert.deepEqual(alertActions(open, { canManage: false }), []);
  assert.equal(isOpenAlert({ alert_status: "Dismissed" }), false);
  assert.equal(isOpenAlert({ alert_status: "Action Required" }), true);
  assert.equal(alertStatusStyle("Dismissed").rowClass, "opacity-60");
});

test("reasons and evidence are listed as the API gave them", () => {
  const alert = {
    evidence: [
      { kind: "signal", code: "PAYMENT_DELAY_INCREASED", label: "Payment delay increased", evidence: "On Time -> Late 30-59." },
      { kind: "state_rule", code: null, label: "WARNING rule", evidence: "Latest month is Late 30-59." },
    ],
  };
  assert.deepEqual(alertEvidence(alert), [
    { kind: "signal", code: "PAYMENT_DELAY_INCREASED", label: "Payment delay increased", text: "On Time -> Late 30-59." },
    { kind: "state_rule", code: null, label: "WARNING rule", text: "Latest month is Late 30-59." },
  ]);
  assert.deepEqual(alertEvidence({ evidence: null }), []);
});

test("deterioration reads as a change in score", () => {
  assert.equal(formatDeterioration(18), "−18.0");
  assert.equal(formatDeterioration(-4.25), "+4.3");
  assert.equal(formatDeterioration(0), "0.0");
  assert.equal(formatDeterioration(null), "—");
});

test("timeline sources and overview counts", () => {
  assert.equal(timelineSourceLabel({ source: "audit_log" }), "Audit trail");
  assert.match(timelineSourceLabel({ source: "record" }), /before the audit trail/);
  const counts = stateCounts({ state_counts: { NORMAL: 3, CRITICAL: 1 } });
  assert.deepEqual(counts.map((c) => [c.state, c.count]), [["NORMAL", 3], ["WATCH", 0], ["WARNING", 0], ["CRITICAL", 1]]);
});

test("no EWS business threshold is hard-coded in the dashboard", () => {
  const files = [
    join(SRC, "lib", "ews.js"),
    join(SRC, "lib", "decisions.js"),
    join(SRC, "pages", "AlertsPage.jsx"),
    join(SRC, "pages", "ModelPage.jsx"),
    ...readdirSync(join(SRC, "components"))
      .filter((name) => name.endsWith(".jsx"))
      .map((name) => join(SRC, "components", name)),
  ];
  const forbidden = [
    /alertSeverity\s*\(/, // the old drop-based severity
    /score_drop\s*[<>]=?\s*\d/,
    /\b(15|22|30)[- ]points?\b/i,
    /\b10\s*%\s*or more\b/i,
  ];
  for (const file of files) {
    const source = readFileSync(file, "utf8");
    for (const pattern of forbidden) {
      assert.ok(!pattern.test(source), `${file} matches ${pattern}`);
    }
  }
});
