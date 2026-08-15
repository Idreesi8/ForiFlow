/**
 * Capture the seven ForiFlow screenshots used in the GitHub README.
 *
 *   npm run capture          (from frontend/)
 *   node scripts/capture-screenshots.js
 *
 * Polls the running stack first. If nothing answers, starts Docker Compose
 * or the local uvicorn + Vite pair. Servers are left running on purpose.
 */

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, "docs", "screenshots");
const FRONTEND = "http://localhost:3000";
const BACKEND = "http://localhost:8000";

const APPLICANT = {
  applicant_name: "Ali Khan",
  business_name: "Khan Traders",
  loan_amount_pkr: "500000",
  tenure_months: "12",
  monthly_digital_payments: "150000",
  // Intake scale is 0-100. The brief's 0.95 / 1.0 were 0-1 fractions.
  payment_history_score: "95",
  inventory_turnover: "4.5",
  order_consistency: "100",
  existing_debt_pkr: "100000",
  cash_flow_proxy: "150000",
  years_in_operation: "5",
  num_employees: "8",
};

const SHOTS = [
  {
    file: "01-dashboard-overview.png",
    run: async (page) => {
      await page.goto(`${FRONTEND}/`, { waitUntil: "networkidle" });
      await page.getByText(/API online|Dashboard/i).first().waitFor({ timeout: 20000 });
    },
  },
  {
    file: "02-credit-scoring-form.png",
    run: async (page) => {
      await clickNav(page, "Credit Scoring");
      await page.locator("#applicant_name").waitFor({ timeout: 15000 });
    },
  },
  {
    file: "03-credit-scoring-result.png",
    run: async (page) => {
      await clickNav(page, "Credit Scoring");
      await page.locator("#applicant_name").waitFor({ timeout: 15000 });
      for (const [name, value] of Object.entries(APPLICANT)) {
        const input = page.locator(`#${name}`);
        await input.fill("");
        await input.fill(String(value));
      }
      await page.getByRole("button", { name: /Score application/i }).click();
      await page.getByText(/Approved|Rejected|Manual Review/).first().waitFor({
        timeout: 60000,
      });
      await page.waitForTimeout(800);
    },
  },
  {
    file: "04-shap-waterfall.png",
    run: async (page) => {
      const viewShap = page.getByRole("button", { name: /View SHAP/i }).first();
      if (await viewShap.count()) {
        await viewShap.click();
      } else {
        await clickNav(page, "SHAP Reports");
      }
      await page.locator("svg").first().waitFor({ timeout: 20000 });
      await page.waitForTimeout(600);
    },
  },
  {
    file: "05-ews-alerts.png",
    run: async (page) => {
      await clickNav(page, "EWS Alerts");
      await page.locator("table, h2").first().waitFor({ timeout: 15000 });
    },
  },
  {
    file: "06-applications-table.png",
    run: async (page) => {
      await clickNav(page, "Applications");
      await page.locator("table tbody tr").first().waitFor({ timeout: 20000 });
    },
  },
  {
    file: "07-swagger-docs.png",
    run: async (page) => {
      await page.goto(`${BACKEND}/docs`, { waitUntil: "networkidle" });
      await page.locator(".swagger-ui, #swagger-ui").first().waitFor({ timeout: 20000 });
    },
  },
];

function log(kind, message) {
  const codes = { ok: "32", warn: "33", err: "31", info: "36" };
  const color = codes[kind] || "0";
  console.log(`\x1b[${color}m[${kind.toUpperCase()}]\x1b[0m ${message}`);
}

function httpOk(url, timeoutMs = 2500) {
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode >= 200 && res.statusCode < 500);
    });
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

async function clickNav(page, label) {
  const link = page.getByRole("link", { name: label }).first();
  await link.click();
  await page.waitForTimeout(400);
}

function spawnLogged(command, args, cwd) {
  log("info", `Starting: ${command} ${args.join(" ")}`);
  const child = spawn(command, args, {
    cwd,
    detached: false,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  child.on("error", (error) => log("err", `${command} failed to spawn: ${error.message}`));
  return child;
}

function dockerAvailable() {
  const probe = spawnSync("docker", ["compose", "version"], {
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  return probe.status === 0;
}

async function ensureServers() {
  const backendUp = await httpOk(`${BACKEND}/health`);
  const frontendUp = await httpOk(`${FRONTEND}/`);
  if (backendUp && frontendUp) {
    log("ok", "Backend and frontend are already running.");
    return;
  }

  log("warn", "Stack not reachable — starting it.");
  if (dockerAvailable()) {
    spawnLogged("docker", ["compose", "up", "-d"], ROOT);
  } else {
    spawnLogged("python", ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"], path.join(ROOT, "backend"));
    spawnLogged("npm", ["run", "dev"], path.join(ROOT, "frontend"));
  }

  log("info", "Waiting 15 seconds for servers to become ready...");
  await new Promise((resolve) => setTimeout(resolve, 15000));

  for (let attempt = 0; attempt < 24; attempt += 1) {
    const api = await httpOk(`${BACKEND}/health`);
    const ui = await httpOk(`${FRONTEND}/`);
    if (api && ui) {
      log("ok", "Both servers answered.");
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  throw new Error(
    "Could not reach http://localhost:8000/health and http://localhost:3000/. " +
      "Start Docker Desktop (or uvicorn + npm run dev) and re-run.",
  );
}

async function shoot(page, spec) {
  const dest = path.join(OUT_DIR, spec.file);
  try {
    await spec.run(page);
    await page.screenshot({ path: dest, fullPage: true });
    log("ok", dest);
    return;
  } catch (first) {
    log("warn", `${spec.file} failed (${first.message}). Retrying in 5s.`);
    await page.waitForTimeout(5000);
    try {
      await spec.run(page);
      await page.screenshot({ path: dest, fullPage: true });
      log("ok", dest);
    } catch (second) {
      log("err", `${spec.file} skipped: ${second.message}`);
    }
  }
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  await ensureServers();

  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch {
    log("err", "Playwright is not installed. From scripts/: npm install && npx playwright install chromium");
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 1080 },
    colorScheme: "light",
  });

  for (const spec of SHOTS) {
    await shoot(page, spec);
  }

  await browser.close();
  log("ok", "Browser closed. Servers were left running.");
}

main().catch((error) => {
  log("err", error.message);
  process.exit(1);
});
