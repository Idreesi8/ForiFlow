/** Formatting helpers shared across the ForiFlow dashboard. */

// `currencyDisplay: "code"` renders "PKR 2,400,000" instead of the locale's
// default "Rs", keeping every amount consistent with the compact formatter.
const PKR_FORMATTER = new Intl.NumberFormat("en-PK", {
  style: "currency",
  currency: "PKR",
  currencyDisplay: "code",
  maximumFractionDigits: 0,
});

const NUMBER_FORMATTER = new Intl.NumberFormat("en-PK");

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en-PK", {
  dateStyle: "medium",
  timeStyle: "short",
});

const DATE_FORMATTER = new Intl.DateTimeFormat("en-PK", { dateStyle: "medium" });

/** Format an exact PKR amount, e.g. "PKR 2,500,000". */
export function formatPKR(value) {
  const amount = Number(value);
  if (value === null || value === undefined || Number.isNaN(amount)) return "—";
  return PKR_FORMATTER.format(amount);
}

/**
 * Format PKR using the crore / lakh conventions Pakistani officers read fastest.
 * 25,000,000 becomes "PKR 2.50 Cr" and 250,000 becomes "PKR 2.50 L".
 */
export function formatPKRCompact(value) {
  const amount = Number(value);
  if (value === null || value === undefined || Number.isNaN(amount)) return "—";
  if (Math.abs(amount) >= 1e7) return `PKR ${(amount / 1e7).toFixed(2)} Cr`;
  if (Math.abs(amount) >= 1e5) return `PKR ${(amount / 1e5).toFixed(2)} L`;
  return PKR_FORMATTER.format(amount);
}

export function formatNumber(value, fractionDigits = 0) {
  const amount = Number(value);
  if (value === null || value === undefined || Number.isNaN(amount)) return "—";
  return amount.toFixed(fractionDigits);
}

export function formatCount(value) {
  const amount = Number(value);
  if (value === null || value === undefined || Number.isNaN(amount)) return "—";
  return NUMBER_FORMATTER.format(amount);
}

/**
 * Parse a timestamp coming from the API.
 * SQLite drops the timezone suffix, so a naive string is interpreted as UTC
 * rather than as the browser's local time.
 */
export function parseApiDate(value) {
  if (!value) return null;
  const hasTimezone = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasTimezone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value) {
  const date = parseApiDate(value);
  return date ? DATE_TIME_FORMATTER.format(date) : "—";
}

export function formatDate(value) {
  const date = parseApiDate(value);
  return date ? DATE_FORMATTER.format(date) : "—";
}

/** Short relative age, e.g. "3h ago", used in the alert feed. */
export function formatRelative(value) {
  const date = parseApiDate(value);
  if (!date) return "—";

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(value);
}

export function formatSigned(value, fractionDigits = 2) {
  const amount = Number(value);
  if (value === null || value === undefined || Number.isNaN(amount)) return "—";
  return `${amount >= 0 ? "+" : ""}${amount.toFixed(fractionDigits)}`;
}
