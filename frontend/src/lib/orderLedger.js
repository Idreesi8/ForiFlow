export const MAX_LEDGER_BYTES = 1024 * 1024;
const MAX_ROWS = 20_000;
const HEADER = ['order_id', 'order_date', 'status'];
const CELL = '("(?:[^"]|"")*"|[^",]*)';
const CSV_LINE = new RegExp(`^${CELL},${CELL},${CELL}$`);

function cells(line, lineNumber) {
  if (line.length > 1024) throw new Error(`Line ${lineNumber} is too long for the three-column ledger format.`);
  const match = CSV_LINE.exec(line.trim());
  if (!match) throw new Error(`Line ${lineNumber} must contain exactly three CSV columns. Keep each record on one line.`);
  return match.slice(1).map(cell =>
    (cell.startsWith('"') ? cell.slice(1, -1).replaceAll('""', '"') : cell).trim(),
  );
}

function isDate(value) {
  if (!/^[1-9]\d{3}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

/** Returns counts only. Order identifiers and raw lines do not leave this function. */
export function parseOrderLedger(csv) {
  if (csv.length > MAX_LEDGER_BYTES) throw new Error('The CSV must be 1 MB or smaller.');
  const lines = csv.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/);
  const header = cells(lines[0], 1);
  if (!HEADER.every((name, index) => name === header[index].toLowerCase())) {
    throw new Error('Use these three headers in order: order_id, order_date, status.');
  }

  const orders = new Map();
  let rows = 0;
  let firstDate = null;
  let lastDate = null;
  for (let index = 1; index < lines.length; index += 1) {
    if (!lines[index].trim()) continue;
    if (++rows > MAX_ROWS) throw new Error('The ledger can contain up to 20,000 data rows.');
    const lineNumber = index + 1;
    const [id, date, rawStatus] = cells(lines[index], lineNumber);
    if (!id || id.length > 128 || /[\x00-\x1f\x7f]/.test(id)) {
      throw new Error(`Line ${lineNumber} needs an order ID of 1–128 characters, without control characters.`);
    }
    if (!isDate(date)) throw new Error(`Line ${lineNumber} needs a valid order date in YYYY-MM-DD format.`);
    const status = rawStatus.toLowerCase();
    const cancelled = status === 'cancelled' || status === 'canceled';
    if (!cancelled && status !== 'placed' && status !== 'completed') {
      throw new Error(`Line ${lineNumber} needs a status of placed, completed or cancelled.`);
    }
    const previous = orders.get(id);
    if (previous && (previous.date !== date || previous.cancelled !== cancelled)) {
      throw new Error(`Line ${lineNumber} repeats an order with a conflicting date or cancellation status. Use one order date and the final status on every line.`);
    }
    if (previous) continue;
    orders.set(id, { date, cancelled });
    if (firstDate === null || date < firstDate) firstDate = date;
    if (lastDate === null || date > lastDate) lastDate = date;
  }

  const byMonth = new Map();
  for (const order of orders.values()) {
    const month = order.date.slice(0, 7);
    const counts = byMonth.get(month) ?? { orders: 0, cancelled: 0 };
    counts[order.cancelled ? 'cancelled' : 'orders'] += 1;
    byMonth.set(month, counts);
  }
  return { byMonth, rows, distinctOrders: orders.size, firstDate, lastDate };
}

function monthIndex(month) {
  if (!/^[1-9]\d{3}-(?:0[1-9]|1[0-2])$/.test(month)) return null;
  const [year, number] = month.split('-').map(Number);
  return year * 12 + number - 1;
}

export function summariseOrderLedger(ledger, start, end, today, complete) {
  const first = monthIndex(start);
  const last = monthIndex(end);
  if (first === null || last === null || last < first) {
    throw new Error('Choose a start and end month in order.');
  }
  if (last >= monthIndex(today.slice(0, 7))) throw new Error('Choose months that have ended in Pakistan.');
  if (last - first >= 12) throw new Error('Choose no more than 12 months.');
  if (!complete) throw new Error('Confirm that the ledger covers every selected month in full.');

  const months = [];
  let totalOrders = 0;
  let totalCancelled = 0;
  for (let index = first; index <= last; index += 1) {
    const month = `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, '0')}`;
    const { orders, cancelled } = ledger.byMonth.get(month) ?? { orders: 0, cancelled: 0 };
    months.push({ month, orders, cancelled });
    totalOrders += orders;
    totalCancelled += cancelled;
  }

  let stability = null;
  if (months.length >= 3 && totalOrders > 0) {
    const mean = totalOrders / months.length;
    const variance = months.reduce((sum, month) => sum + (month.orders - mean) ** 2, 0) / months.length;
    stability = Math.round(100 * Math.max(0, 1 - Math.sqrt(variance) / mean));
  }
  return {
    months, totalOrders, totalCancelled, stability,
    excludedOrders: ledger.distinctOrders - totalOrders - totalCancelled,
  };
}
