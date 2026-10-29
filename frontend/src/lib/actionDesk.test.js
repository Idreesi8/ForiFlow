import assert from "node:assert/strict";
import test from "node:test";
import { briefingText, deskPath, deskQuery, positiveInteger, readDeskQuery, snapshotLabel, taskPath, updateDeskQuery, worklistReturnPath, worklistReturnState } from "./actionDesk.js";

test("case links select the right case and only prefill a genuinely missing month", () => {
  assert.equal(taskPath({ kind: "review", application_id: 221 }), "/shap/221");
  assert.equal(taskPath({ kind: "alert", application_id: 221 }), "/alerts?facility=221#alert-queue");
  assert.equal(taskPath({ kind: "monitoring", application_id: 221, first_missing_month: 2 }), "/alerts?facility=221&month=2#monitoring");
  assert.equal(taskPath({ kind: "monitoring", application_id: 221, first_missing_month: null }), "/alerts?facility=221#monitoring");
});

test("malformed or unsafe case references never become navigation targets", () => {
  for (const value of [null, "", 0, -1, "1e2", "1.5", "//outside", "1&month=3", "9007199254740992"]) {
    assert.equal(positiveInteger(value), null);
    assert.equal(taskPath({ kind: "review", application_id: value }), "/action-desk");
  }
});

test("snapshots use the officer's Pakistan date across UTC midnight boundaries", () => {
  assert.match(snapshotLabel("2026-10-22T21:30:00Z"), /23.*Oct.*2026/);
  assert.match(snapshotLabel("2026-10-22T21:30:00Z"), /PKT$/);
});

test("copied briefings distinguish this page from complete portfolio counts", () => {
  const text = briefingText({ as_of: "2026-10-22T12:00:00Z", total_tasks: 41, application_count: 29,
    matching_tasks: 8, offset: 5, items: [{ priority: "urgent", business_name: "Synthetic workshop", application_id: 221,
      title: "Follow up overdue alert", reason: "An open alert needs follow-up.", evidence: ["Action deadline passed 2 days ago."] }] });
  assert.match(text, /41 tasks across 29 cases/);
  assert.match(text, /items 6–6 of 8 matching tasks/);
  assert.match(text, /Action deadline passed 2 days ago/);
  assert.match(text, /Missing records do not prove missed payment/);
});

test("briefings identify role scope without implying task ownership or approval authority", () => {
  const snapshot = { as_of: "2026-10-27T12:00:00Z", total_tasks: 40, application_count: 31,
    matching_tasks: 0, offset: 0, items: [], officer_role: "analyst", actionable_tasks: 7, actionable_only: true };
  const filtered = briefingText(snapshot);
  assert.match(filtered, /Role scope: tasks my role can act on; current role: analyst/);
  assert.match(filtered, /7 tasks match this role across the complete portfolio/);
  assert.match(filtered, /Role eligibility is not personal assignment; case-specific approval limits still apply/);
  assert.match(filtered, /items 0–0 of 0 matching tasks/);
  assert.match(briefingText({ ...snapshot, actionable_only: false }), /Role scope: all roles/);
});

test("a worklist address round-trips role, filters, applied search and page", () => {
  const view = { kind: "review", priority: "attention", actionableOnly: true, search: "A&B + Workshop #47", page: 3 };
  assert.deepEqual(readDeskQuery(deskQuery(view)), view);
  assert.equal(deskPath(), "/action-desk");
  assert.equal(deskPath({ actionableOnly: true }), "/action-desk?actionable_only=true");
  assert.equal(deskQuery({ search: "  " }), "");
});

test("untrusted worklist controls stay bounded and cannot add request parameters", () => {
  const view = readDeskQuery("kind=__proto__&priority=constructor&actionable_only=yes&page=999999999999999999999&role=admin&limit=99999&search=" + "x".repeat(500));
  assert.equal(view.kind, ""); assert.equal(view.priority, ""); assert.equal(view.actionableOnly, false);
  assert.equal(view.page, 1); assert.equal(view.search.length, 100);
  const query = new URLSearchParams(deskQuery(view));
  assert.deepEqual([...query.keys()], ["search"]);
  for (const page of ["-1", "0", "1.1", "1e2", "Infinity", "20000002", "01", "garbage"]) {
    assert.equal(readDeskQuery(`page=${page}`).page, 1);
  }
  assert.equal(readDeskQuery("page=20000001").page, 20_000_001);
});

test("changing filters resets paging while paging retains the complete applied view", () => {
  const initial = new URLSearchParams("kind=review&priority=routine&actionable_only=true&search=workshop&page=9&unrelated=discard");
  assert.deepEqual(readDeskQuery(updateDeskQuery(initial, { kind: "monitoring" })), {
    kind: "monitoring", priority: "routine", actionableOnly: true, search: "workshop", page: 1,
  });
  assert.deepEqual(readDeskQuery(updateDeskQuery(initial, { page: 8 })), { ...readDeskQuery(initial), page: 8 });
  assert.equal(initial.get("page"), "9");
  assert.equal(updateDeskQuery(initial, { page: 8 }).has("unrelated"), false);
});

test("case return navigation accepts only bounded worklist state and has a fixed local destination", () => {
  const state = { worklistSearch: "?kind=review&search=A%26B&page=2&role=admin", unsafe: "ignored" };
  assert.equal(worklistReturnPath(state), "/action-desk?kind=review&search=A%26B&page=2");
  assert.deepEqual(worklistReturnState(state), { worklistSearch: "kind=review&search=A%26B&page=2" });
  assert.equal(worklistReturnPath({ worklistSearch: "//evil.example/path" }), "/action-desk");
  assert.equal(worklistReturnPath({ worklistSearch: "" }), "/action-desk");
  for (const invalid of [null, undefined, {}, { worklistSearch: {} }, { worklistSearch: "x".repeat(2001) }]) {
    assert.equal(worklistReturnPath(invalid), null);
    assert.equal(worklistReturnState(invalid), undefined);
  }
});
