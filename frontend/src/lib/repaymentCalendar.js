/** Exact money and contract-date helpers. No interest or payment assumptions. */
export function paisa(value) {
  if (typeof value !== 'string' || !/^\d{1,12}(\.\d{1,2})?$/.test(value)) throw new Error('Enter a PKR amount with at most two decimal places.');
  const [whole, fraction = ''] = value.split('.');
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
}

export function isoDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

export function monthlyItems(first, count, amount) {
  if (!isoDate(first) || !Number.isInteger(count) || count < 1 || count > 120) throw new Error('Choose a valid first due date and 1–120 instalments.');
  if (paisa(amount) <= 0n || paisa(amount) > 100_000_000_000n) throw new Error('Enter the agreed instalment amount, up to PKR 1 billion.');
  const [year, month, day] = first.split('-').map(Number);
  return Array.from({ length: count }, (_, number) => {
    const index = month - 1 + number;
    const y = year + Math.floor(index / 12), m = index % 12;
    const end = new Date(0); end.setUTCFullYear(y, m + 1, 0);
    const due = new Date(0); due.setUTCFullYear(y, m, Math.min(day, end.getUTCDate()));
    const date = due.toISOString().slice(0, 10);
    if (!isoDate(date)) throw new Error('The schedule extends beyond supported calendar dates.');
    return { due_on: date, amount_pkr: amount };
  });
}

export function validCalendar(data, applicationId) {
  try {
    if (data?.application_id !== Number(applicationId) || !isoDate(data.as_of_date) ||
        !Array.isArray(data.installments) || !Array.isArray(data.limits) || !Array.isArray(data.recent_receipts)) return false;
    if (data.schedule === null) return data.installments.length === 0 && data.recent_receipts.length === 0;
    if (!Number.isSafeInteger(data.schedule?.id) || data.schedule.id < 1 || !data.installments.length || data.installments.length > 120 ||
        typeof data.schedule.is_current !== 'boolean' || !Array.isArray(data.schedule_versions) ||
        !data.schedule_versions.some(v => v.id === data.schedule.id) ||
        !data.schedule_versions.some(v => v.id === data.current_schedule_id) ||
        data.schedule.is_current !== (data.schedule.id === data.current_schedule_id) ||
        !Number.isSafeInteger(data.receipt_count) || data.receipt_count < data.recent_receipts.length ||
        !Number.isSafeInteger(data.receipt_offset) || data.receipt_offset < 0 || data.recent_receipts.length > 20) return false;
    let total = 0n, paid = 0n, balance = 0n, overdue = 0n;
    for (const [index, row] of data.installments.entries()) {
      const a = paisa(row.amount_pkr), p = paisa(row.paid_pkr), b = paisa(row.outstanding_pkr);
      if (row.installment !== index + 1 || !isoDate(row.due_on) || a <= 0n || p + b !== a ||
          !Number.isSafeInteger(row.days_past_due) || row.days_past_due < 0 ||
          !['paid', 'overdue', 'due_today', 'upcoming'].includes(row.status)) return false;
      const days = b === 0n ? 0 : Math.max(0, Math.round((Date.parse(data.as_of_date) - Date.parse(row.due_on)) / 86400000));
      const status = b === 0n ? 'paid' : days > 0 ? 'overdue' : row.due_on === data.as_of_date ? 'due_today' : 'upcoming';
      if (row.days_past_due !== days || row.status !== status) return false;
      total += a; paid += p; balance += b;
      if (row.status === 'overdue') overdue += b;
    }
    for (const receipt of data.recent_receipts) {
      if (!Number.isSafeInteger(receipt.id) || typeof receipt.reference !== 'string' || !isoDate(receipt.paid_on) ||
          !Array.isArray(receipt.allocations) || !receipt.allocations.length ||
          new Set(receipt.allocations.map(a => a.installment)).size !== receipt.allocations.length) return false;
      let sum = 0n;
      for (const allocation of receipt.allocations) {
        if (!Number.isSafeInteger(allocation.installment) || allocation.installment < 1 || allocation.installment > data.installments.length || paisa(allocation.amount_pkr) <= 0n) return false;
        sum += paisa(allocation.amount_pkr);
      }
      if (paisa(receipt.total_pkr) !== sum) return false;
    }
    return paisa(data.total_scheduled_pkr) === total && paisa(data.total_paid_pkr) === paid &&
      paisa(data.total_outstanding_pkr) === balance && paisa(data.overdue_pkr) === overdue &&
      data.maximum_days_past_due === Math.max(...data.installments.map(i => i.days_past_due));
  } catch { return false; }
}

/** Retain a key on a lost response; edits are a different save intent. */
export function saveIntent(previous, payload, makeKey) {
  const fingerprint = JSON.stringify(payload);
  return previous?.fingerprint === fingerprint ? previous : { fingerprint, key: makeKey() };
}
