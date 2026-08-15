/**
 * ForiFlow master automation: screenshots → README → git push → LinkedIn tabs.
 *
 *   node scripts/full-automation.js
 */

const { execSync, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs", "screenshots");
const README = path.join(ROOT, "README.md");
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

const SCREENSHOT_SECTION = `## 📸 Screenshots

![Dashboard](docs/screenshots/01-dashboard.png)
![Credit Scoring](docs/screenshots/02-scoring-form.png)
![Score Result](docs/screenshots/03-score-result.png)
![SHAP Chart](docs/screenshots/04-shap-chart.png)
![EWS Alerts](docs/screenshots/05-ews-alerts.png)
![Applications](docs/screenshots/06-applications.png)
![API Docs](docs/screenshots/07-swagger.png)
`;

function color(code, text) {
  return `\x1b[${code}m${text}\x1b[0m`;
}

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

async function clickNav(page, label) {
  await page.getByRole("link", { name: label }).first().click();
  await page.waitForTimeout(500);
}

function loadChromium() {
  try {
    return require("@playwright/test").chromium;
  } catch {
    return require("playwright").chromium;
  }
}

async function captureScreenshots() {
  fs.mkdirSync(OUT, { recursive: true });
  const chromium = loadChromium();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch {
    browser = await chromium.launch({ headless: true, channel: "chrome" });
  }
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
  console.log(color("32", "✅ Screenshots captured"));
}

function updateReadme() {
  const current = fs.readFileSync(README, "utf8");
  const replaced = current.replace(
    /## 📸 Screenshots[\s\S]*?(?=\n## )/,
    `${SCREENSHOT_SECTION}\n`,
  );
  if (replaced === current && !current.includes("docs/screenshots/01-dashboard.png")) {
    throw new Error("Could not find the Screenshots section in README.md");
  }
  fs.writeFileSync(README, replaced, "utf8");
  console.log(color("32", "✅ README updated with screenshots"));
}

function gitCommitAndPush() {
  execSync("git add .", { cwd: ROOT, stdio: "inherit" });
  try {
    execSync('git commit -m "docs: Add product screenshots and automation scripts"', {
      cwd: ROOT,
      stdio: "inherit",
    });
  } catch (error) {
    const message = String(error.stderr || error.stdout || error.message);
    if (!/nothing to commit/i.test(message) && error.status !== 1) {
      throw error;
    }
    console.log(color("33", "Nothing new to commit — pushing current main."));
  }
  execSync("git push origin main", { cwd: ROOT, stdio: "inherit" });
  console.log(color("32", "✅ Pushed to GitHub: https://github.com/Idreesi8/ForiFlow"));
}

function openLinkedIn() {
  const urls = [
    "https://www.linkedin.com/in/ramzan-idreesi/edit/about/",
    "https://www.linkedin.com/in/ramzan-idreesi/edit/featured/",
  ];
  for (const url of urls) {
    if (process.platform === "win32") {
      spawnSync("cmd", ["/c", "start", "", url], { detached: true, stdio: "ignore" });
    } else if (process.platform === "darwin") {
      spawnSync("open", [url], { detached: true, stdio: "ignore" });
    } else {
      spawnSync("xdg-open", [url], { detached: true, stdio: "ignore" });
    }
  }
  console.log(color("36", "🌐 LinkedIn pages opened in browser"));
}

function finalReport() {
  console.log("");
  console.log(color("32", "========================================"));
  console.log(color("32", "🎉 FORIFLOW AUTOMATION COMPLETE!"));
  console.log(color("32", "========================================"));
  console.log("✅ Screenshots: docs/screenshots/ (7 images)");
  console.log("✅ README: Updated with screenshot links");
  console.log("✅ GitHub: Pushed to origin/main");
  console.log("🌐 LinkedIn: Browser tabs opened");
  console.log("----------------------------------------");
  console.log("NEXT: Copy content from linkedin/ folder");
  console.log("and paste into opened LinkedIn tabs");
  console.log(color("32", "========================================"));
}

async function main() {
  const backendUp = await httpOk(`${BACKEND}/health`);
  const frontendUp = await httpOk(`${FRONTEND}/`);
  if (!backendUp || !frontendUp) {
    console.log(color("36", "🚀 Start Terminal 1: cd backend && python -m uvicorn main:app --reload --port 8000"));
    console.log(color("36", "🚀 Start Terminal 2: cd frontend && npm run dev -- --port 3000"));
    console.log(color("33", "⏳ Then wait 10 seconds and re-run: node scripts/full-automation.js"));
    process.exit(0);
  }

  await captureScreenshots();
  updateReadme();
  gitCommitAndPush();
  openLinkedIn();
  finalReport();
}

main().catch((error) => {
  console.error(color("31", error.message || String(error)));
  process.exit(1);
});
