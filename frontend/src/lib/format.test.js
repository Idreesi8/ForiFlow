import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import { businessDate, formatDate, formatDateTime, parseApiDate } from "./format.js";

test("Pakistan calendar rolls over at 19:00 UTC, including month, year and leap day", () => {
  for (const [instant, expected] of [
    ["2026-10-25T18:59:59.999Z", "2026-10-25"],
    ["2026-10-25T19:00:00Z", "2026-10-26"],
    ["2026-10-31T19:00:00Z", "2026-11-01"],
    ["2026-12-31T19:00:00Z", "2027-01-01"],
    ["2028-02-28T19:00:00Z", "2028-02-29"],
  ]) assert.equal(businessDate(new Date(instant)), expected);
});

test("offset and naive SQLite timestamps describe the same instant", () => {
  const values = ["2026-10-25T20:30:00Z", "2026-10-26T01:30:00+05:00", "2026-10-25T20:30:00"];
  assert.equal(new Set(values.map(value => parseApiDate(value).getTime())).size, 1);
  assert.equal(new Set(values.map(formatDateTime)).size, 1);
  assert.match(formatDateTime(values[0]), /26[- ]Oct[- ]2026.*1:30.*PKT/);
});

test("a calendar due date stays on its recorded day and invalid dates stay unknown", () => {
  assert.match(formatDate("2026-10-26"), /^26[- ]Oct[- ]2026$/);
  assert.equal(formatDate("2026-10-25T20:30:00Z"), formatDate("2026-10-26"));
  assert.match(formatDate("2028-02-29"), /^29[- ]Feb[- ]2028$/);
  for (const value of [null, undefined, "", "invalid", "2026-02-29", "2026-04-31", 123, {}]) {
    assert.equal(parseApiDate(value), null);
    assert.equal(formatDate(value), "—");
    assert.equal(formatDateTime(value), "—");
  }
});

test("officers see identical calendar dates and PKT timestamps in three machine timezones", () => {
  const module = new URL("./format.js", import.meta.url).href;
  const code = `import {businessDate,formatDate,formatDateTime} from ${JSON.stringify(module)};
    console.log(JSON.stringify([businessDate(new Date('2026-10-25T20:30:00Z')),
      formatDate('2026-10-26'),formatDate('2026-10-25T20:30:00Z'),formatDateTime('2026-10-25T20:30:00')]));`;
  const results = ["UTC", "America/Los_Angeles", "Pacific/Kiritimati"].map(TZ =>
    execFileSync(process.execPath, ["--input-type=module", "-e", code], { env: { ...process.env, TZ }, encoding: "utf8" }).trim());
  assert.equal(new Set(results).size, 1);
});
