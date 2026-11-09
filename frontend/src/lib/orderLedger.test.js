import test from 'node:test';
import assert from 'node:assert/strict';
import { MAX_LEDGER_BYTES, parseOrderLedger, summariseOrderLedger } from './orderLedger.js';

const header = 'order_id,order_date,status';
const ledger = (...lines) => parseOrderLedger([header, ...lines].join('\n'));
const today = '2026-04-01';

test('groups product lines by exact order ID and reports distinct cancellations and outside orders', () => {
  const data = parseOrderLedger(`\uFEFF"${header.replaceAll(',', '","')}"\r\n"order, ""A""",2026-01-01,Completed\r\n"order, ""A""",2026-01-01,completed\r\nB,2026-01-03,cancelled\r\nB,2026-01-03,canceled\r\nC,2026-03-02,placed\r\nD,2025-12-31,completed\r\n`);
  assert.equal(data.rows, 6);
  assert.equal(data.distinctOrders, 4);
  assert.equal(data.firstDate, '2025-12-31');
  assert.equal(data.lastDate, '2026-03-02');
  assert.deepEqual([...data.byMonth.keys()], ['2026-01', '2026-03', '2025-12']);
  const report = summariseOrderLedger(data, '2026-01', '2026-03', today, true);
  assert.deepEqual(report.months, [
    { month: '2026-01', orders: 1, cancelled: 1 },
    { month: '2026-02', orders: 0, cancelled: 0 },
    { month: '2026-03', orders: 1, cancelled: 0 },
  ]);
  assert.equal(report.stability, 29);
  assert.equal(report.excludedOrders, 1);
});

test('an unconfirmed gap remains unknown and a current month cannot be called complete', () => {
  const data = ledger('A,2026-01-03,placed');
  assert.throws(() => summariseOrderLedger(data, '2026-01', '2026-03', today, false), /Confirm/);
  assert.throws(() => summariseOrderLedger(data, '2026-01', '2026-04', today, true), /ended in Pakistan/);
  assert.throws(() => summariseOrderLedger(data, '2026-03', '2026-02', today, true), /in order/);
  assert.throws(() => summariseOrderLedger(data, '2025-02', '2026-03', today, true), /12 months/);
});

test('all-zero or short confirmed windows do not manufacture stability', () => {
  const empty = summariseOrderLedger(ledger(), '2026-01', '2026-03', today, true);
  assert.equal(empty.totalOrders, 0);
  assert.equal(empty.stability, null);
  const short = summariseOrderLedger(ledger('A,2026-03-01,completed'), '2026-02', '2026-03', today, true);
  assert.equal(short.totalOrders, 1);
  assert.equal(short.stability, null);
});

test('three equal positive months give full stability across a year boundary', () => {
  const data = ledger('A,2025-12-01,completed', 'B,2026-01-01,completed', 'C,2026-02-01,placed');
  assert.equal(summariseOrderLedger(data, '2025-12', '2026-02', today, true).stability, 100);
});

test('duplicate dates and cancellation conflicts are rejected without exposing the order ID', () => {
  for (const duplicate of ['SECRET,2026-01-04,completed', 'SECRET,2026-01-03,cancelled']) {
    assert.throws(() => ledger('SECRET,2026-01-03,completed', duplicate), error =>
      /Line 3.*conflicting/.test(error.message) && !error.message.includes('SECRET'));
  }
});

test('malformed CSV, unknown status and invalid calendar dates are refused', () => {
  assert.throws(() => parseOrderLedger('order_id,order_date,quantity'), /headers/);
  assert.throws(() => ledger('"bad,2026-01-01,completed'), /Line 2.*three CSV columns/);
  assert.throws(() => ledger('A,2026-01-03,unknown'), /Line 2.*status/);
  assert.throws(() => ledger('A,2026-02-29,completed'), /Line 2.*valid order date/);
  assert.equal(ledger('A,2024-02-29,completed').firstDate, '2024-02-29');
  assert.throws(() => parseOrderLedger('x'.repeat(MAX_LEDGER_BYTES + 1)), /1 MB/);
  assert.throws(() => ledger(...Array(20_001).fill('A,2026-01-01,placed')), /20,000 data rows/);
});
