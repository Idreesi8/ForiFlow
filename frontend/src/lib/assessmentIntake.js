/** Mirrors `BusinessSector` in backend/schemas.py. */
const BUSINESS_SECTORS = [
  "Retail",
  "Wholesale & Trading",
  "Manufacturing",
  "Textile & Garments",
  "Food & Hospitality",
  "Agriculture & Livestock",
  "Services",
  "Transport & Logistics",
  "Construction",
  "Other",
];

/** Field definitions mirror the backend's Pydantic ranges exactly. */
export const FIELD_GROUPS = [
  {
    title: "Applicant & business",
    id: "assessment-applicant",
    description: "Identity of the borrower as recorded in the credit file.",
    fields: [
      {
        name: "applicant_name",
        label: "Applicant name",
        type: "text",
        placeholder: "e.g. Ayesha Siddiqui",
        minLength: 2,
        maxLength: 120,
      },
      {
        name: "business_name",
        label: "Business name",
        type: "text",
        placeholder: "e.g. Siddiqui Textiles (Faisalabad)",
        minLength: 2,
        maxLength: 160,
      },
      {
        name: "business_sector",
        label: "Business sector",
        type: "select",
        options: BUSINESS_SECTORS,
        optional: true,
        hint: "For portfolio reports only. The model does not read it.",
      },
      {
        name: "contact_phone",
        label: "Contact number",
        type: "text",
        optional: true,
        placeholder: "e.g. +923001234567",
        pattern: /^\+?[0-9]{10,15}$/,
        patternHint: "Digits only, 10 to 15, with an optional + in front.",
        hint: "For payment reminders. Optional.",
      },
      {
        name: "borrower_public_id",
        label: "Existing borrower",
        type: "text",
        optional: true,
        placeholder: "e.g. BRW-000012",
        pattern: /^BRW-[0-9]{6,}$/i,
        patternHint: "A borrower reference looks like BRW-000012.",
        uppercase: true,
        hint: "Fill in for a repeat borrower. Leave empty for a new business.",
      },
      {
        name: "borrower_identifier_type",
        label: "Identifier type",
        type: "select",
        options: ["CNIC", "NTN"],
        optional: true,
        hint: "Optional. The model does not read it.",
      },
      {
        name: "borrower_identifier",
        label: "CNIC or NTN",
        type: "text",
        optional: true,
        placeholder: "e.g. 35202-1234567-1",
        pattern: /^[0-9][0-9 -]{5,22}[0-9]$/,
        patternHint: "Digits, with optional dashes.",
        hint: "Links repeat applications to the same borrower.",
      },
    ],
  },
  {
    title: "Facility requested",
    id: "assessment-facility",
    description: "Amount and tenure being underwritten.",
    fields: [
      {
        name: "loan_amount_pkr",
        label: "Loan amount",
        type: "number",
        currency: true,
        min: 1,
        max: 500000000,
        step: 50000,
        hint: "Requested facility in PKR.",
      },
      {
        name: "tenure_months",
        label: "Tenure (months)",
        type: "number",
        min: 3,
        max: 84,
        step: 1,
        integer: true,
        hint: "Between 3 and 84 months.",
        unusedByModel: true,
      },
    ],
  },
  {
    title: "Alternative data signals",
    id: "assessment-signals",
    description:
      "Digital footprint and officer-entered bureau-style signals (not a live bureau feed).",
    fields: [
      {
        name: "monthly_digital_payments",
        label: "Monthly digital payments",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 25000,
        hint: "Average monthly Raast, POS and wallet receipts.",
      },
      {
        name: "payment_history_score",
        label: "Payment history score",
        type: "number",
        min: 0,
        max: 100,
        step: 1,
        hint: "Officer-entered 0–100 estimate; not a verified bureau score. The model reads values at or below 52.5 as adverse and above 52.5 as clean. Values within the same category have the same credit effect.",
      },
      {
        name: "inventory_turnover",
        label: "Inventory turnover",
        type: "number",
        min: 0,
        max: 50,
        step: 0.1,
        hint: "Times stock is sold per year.",
        unusedByModel: true,
      },
      {
        name: "order_consistency",
        label: "Order consistency",
        type: "number",
        min: 0,
        max: 100,
        step: 1,
        hint: "Officer estimate (0–100). A statement supplies a receipts-stability proxy; it does not verify order volumes.",
        unusedByModel: true,
      },
      {
        name: "existing_debt_pkr",
        label: "Existing debt",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 50000,
        hint: "Outstanding exposure across all lenders.",
        unusedByModel: true,
      },
      {
        name: "cash_flow_proxy",
        label: "Monthly cash flow proxy",
        type: "number",
        currency: true,
        min: 0,
        max: 1000000000,
        step: 25000,
        hint: "Estimated monthly net cash flow.",
      },
      {
        name: "years_in_operation",
        label: "Years in operation",
        type: "number",
        min: 0,
        max: 100,
        step: 0.5,
        hint: "How long the business has been trading. The demo model learned from personal employment length; its use for business age has not been validated.",
      },
      {
        name: "num_employees",
        label: "Employees",
        type: "number",
        min: 0,
        max: 5000,
        step: 1,
        integer: true,
        hint: "Headcount including owners.",
        unusedByModel: true,
      },
    ],
  },
];

export const ALL_FIELDS = FIELD_GROUPS.flatMap((group) => group.fields);

// The trained 3-feature model's unused fields, used until the contract loads.

export function validateAssessment(values) {
  const errors = {};

  for (const field of ALL_FIELDS) {
    const raw = String(values[field.name] ?? "").trim();

    if (!raw) {
      if (!field.optional) errors[field.name] = "Required.";
      continue;
    }
    if (field.type === "select") {
      if (!field.options.includes(raw)) errors[field.name] = "Choose a listed option.";
      continue;
    }

    if (field.type === "text" && field.pattern) {
      if (!field.pattern.test(raw)) errors[field.name] = field.patternHint;
      continue;
    }
    if (field.type === "text") {
      if (raw.length < field.minLength) {
        errors[field.name] = `At least ${field.minLength} characters.`;
      } else if (raw.length > field.maxLength) {
        errors[field.name] = `At most ${field.maxLength} characters.`;
      }
      continue;
    }

    const numeric = Number(raw);
    if (!Number.isFinite(numeric)) {
      errors[field.name] = "Enter a finite number.";
    } else if (numeric < field.min) {
      errors[field.name] = `Minimum is ${field.min}.`;
    } else if (numeric > field.max) {
      errors[field.name] = `Maximum is ${field.max.toLocaleString("en-PK")}.`;
    } else if (field.integer && !Number.isInteger(numeric)) {
      errors[field.name] = "Whole numbers only.";
    }
  }

  // The API needs an identifier and its type together.
  const hasType = Boolean(String(values.borrower_identifier_type ?? "").trim());
  const hasNumber = Boolean(String(values.borrower_identifier ?? "").trim());
  if (hasType && !hasNumber) errors.borrower_identifier = "Enter the number, or clear the type.";
  if (hasNumber && !hasType) errors.borrower_identifier_type = "Choose CNIC or NTN.";

  if (hasType && hasNumber && ["CNIC", "NTN"].includes(values.borrower_identifier_type)) {
    const kind = values.borrower_identifier_type;
    const digits = String(values.borrower_identifier).replace(/[\s-]/g, "");
    const allowed = kind === "CNIC" ? [13] : [7, 8];
    if (!/^[0-9]+$/.test(digits) || !allowed.includes(digits.length)) {
      errors.borrower_identifier = `A ${kind} needs ${allowed.join(" or ")} digits; spaces and dashes are ignored.`;
    }
  }
  return errors;
}

export function assessmentPayload(values) {
  const payload = {};
  for (const field of ALL_FIELDS) {
    const raw = String(values[field.name] ?? "").trim();
    if (!raw && field.optional) continue;
    payload[field.name] =
      field.type === "number" ? Number(raw) : field.uppercase ? raw.toUpperCase() : raw;
  }
  return payload;
}

/** A review is tied to every submitted value and the exact attached CSV. */
export function assessmentKey(values, statement = null) {
  return JSON.stringify([ALL_FIELDS.map(field => String(values[field.name] ?? "")), statement?.csv ?? null]);
}

/** Match the backend evidence comparison: turnover only; order consistency is context. */
export function statementReview(statement, values) {
  if (!statement) return { status: "manual", changed: [] };
  const keys = { monthly_digital_payments: "suggested_monthly_digital_payments", cash_flow_proxy: "suggested_cash_flow_proxy" };
  const changed = Object.entries(keys).filter(([field, key]) => Number(values[field]) !== statement.summary[key]).map(([field]) => field);
  return { status: changed.length ? "edited" : "attached", changed };
}

// Keep every meaningful digit of a submitted JavaScript number in the review.
const preciseNumber = new Intl.NumberFormat("en-PK", { maximumSignificantDigits: 21 });
export function assessmentDisplay(field, value) {
  if (value === undefined) return "Not recorded";
  if (field.type !== "number") return String(value);
  const number = preciseNumber.format(value);
  return field.currency ? `PKR ${number}` : field.name === "tenure_months" ? `${number} months` : number;
}
