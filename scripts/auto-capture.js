/**
 * Auto-capture ForiFlow screenshots for the GitHub README.
 *
 *   npm run capture
 *   node scripts/auto-capture.js
 */

const fs = require("fs");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs", "screenshots");
const FRONTEND = "http://localhost:3000";
const BACKEND = "http://localhost:8000";

const FORM = [
  ["applicant_name", "Ali Khan"],
  ["business_name", "Khan Traders"],
  ["loan_amount_pkr", "500000"],
  ["tenure_months", "12"],
  ["monthly_digital_payments", "150000"],
  ["payment_history_score", "0.95"],
  ["inventory_turnover", "4.5"],
  ["order_consistency", "1.0"],
  ["existing_debt_pkr", "100000"],
  ["cash_flow_proxy", "1.0"],
  ["years_in_operation", "5"],
  ["num_employees", "8"],
];

function httpOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.setTimeout(3000, () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

function printStartCommands() {
  console.log("");
  console.log("Servers are not running. Start them in two terminals, then re-run npm run capture:");
  console.log("");
  console.log("  Terminal 1: cd backend && python -m uvicorn main:app --reload --port 8000");
  console.log("  Terminal 2: cd frontend && npm run dev -- --port 3000");
  console.log("");
}

async function clickNav(page, label) {
  await page.getByRole("link", { name: label }).first().click();
  await page.waitForTimeout(500);
}

async function main() {
  const backendUp = await httpOk(`${BACKEND}/health`);
  const frontendUp = await httpOk(`${FRONTEND}/`);

  if (!backendUp || !frontendUp) {
    printStartCommands();
    console.log("Waiting 10 seconds...");
    await new Promise((r) => setTimeout(r, 10000));
    const backend2 = await httpOk(`${BACKEND}/health`);
    const frontend2 = await httpOk(`${FRONTEND}/`);
    if (!backend2 || !frontend2) {
      printStartCommands();
      process.exit(1);
    }
  }

  let chromium;
  try {
    ({ chromium } = require("@playwright/test"));
  } catch {
    try {
      ({ chromium } = require("playwright"));
    } catch {
      console.error("Install Playwright first: npm install && npx playwright install chromium");
      process.exit(1);
    }
  }

  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    colorScheme: "light",
  });

  await page.goto(`${FRONTEND}/`, { waitUntil: "networkidle" });
  await page.getByText(/API online|API Online|Dashboard/i).first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(OUT, "01-dashboard.png"), fullPage: true });

  await clickNav(page, "Credit Scoring");
  await page.locator("#applicant_name").waitFor({ timeout: 15000 });
  await page.screenshot({ path: path.join(OUT, "02-scoring-form.png"), fullPage: true });

  for (const [name, value] of FORM) {
    const input = page.locator(`#${name}`);
    await input.fill("");
    await input.fill(value);
  }
  await page.getByRole("button", { name: /Score application/i }).click();
  await page.getByText(/Approved|Rejected|Manual Review/).first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "03-score-result.png"), fullPage: true });

  const shapBtn = page.getByRole("button", { name: /View SHAP/i }).first();
  if (await shapBtn.count()) {
    await shapBtn.click();
  } else {
    await clickNav(page, "SHAP Reports");
  }
  await page.locator("svg").first().waitFor({ timeout: 20000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, "04-shap-chart.png"), fullPage: true });

  await clickNav(page, "EWS Alerts");
  await page.locator("table, h2").first().waitFor({ timeout: 15000 });
  await page.screenshot({ path: path.join(OUT, "05-ews-alerts.png"), fullPage: true });

  await clickNav(page, "Applications");
  await page.locator("table tbody tr, table").first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(OUT, "06-applications.png"), fullPage: true });

  await page.goto(`${BACKEND}/docs`, { waitUntil: "networkidle" });
  await page.locator(".swagger-ui, #swagger-ui").first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(OUT, "07-swagger.png"), fullPage: true });

  await browser.close();
  console.log("✅ Screenshots saved to docs/screenshots/");
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
