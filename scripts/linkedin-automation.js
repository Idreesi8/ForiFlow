/**
 * LinkedIn helper: copy ready-to-paste ForiFlow copy, then open the right page.
 * LinkedIn blocks injected browser automation; Ctrl+V is the last human step.
 *
 *   npm run linkedin
 *   node scripts/linkedin-automation.js
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const https = require("https");
const path = require("path");
const readline = require("readline");

const ROOT = path.resolve(__dirname, "..");
const HELPER_HTML = path.join(ROOT, "linkedin-helper.html");
const PROFILE = "https://www.linkedin.com/in/ramzan-idreesi-0b0245328";

const STEPS = [
  {
    name: "About Section",
    url: `${PROFILE}/details/about/`,
    text: `AI Software Engineer | Building Credit Intelligence Systems for Emerging Markets

I build AI-powered fintech solutions that make financial services accessible to the underserved.

Over the past 3 months, I developed ForiFlow — an end-to-end SME Credit Scoring & Early Warning System for Pakistani banks. It uses alternative data (digital payments, ECIB, inventory turnover) to score unbanked SMEs without collateral, provides SHAP explainability for SBP compliance, and detects portfolio deterioration 60-90 days before default.

Tech Stack: FastAPI, React, XGBoost, Random Forest, SHAP, Docker, PostgreSQL

I'm passionate about using Machine Learning and Full-Stack Development to solve real-world problems in financial inclusion. Currently open to full-time AI/ML roles, freelance fintech projects, and bank technology partnerships.

📩 Open for collaborations. Let's build something impactful together.`,
  },
  {
    name: "Featured Project",
    url: `${PROFILE}/details/featured/`,
    title: "ForiFlow — SME Credit Intelligence Platform",
    desc: "AI-powered credit scoring system for Pakistani banks. Features XGBoost+RF ensemble, SHAP explainability for SBP compliance, Early Warning System, and Docker deployment. Built with FastAPI, React, and Python.",
    link: "https://github.com/Idreesi8/ForiFlow",
  },
  {
    name: "Post #1 - Launch",
    url: "https://www.linkedin.com/feed/",
    text: `🚀 I spent 3 months building an AI system that could save Pakistani banks millions.

The Problem:
• 60% of SME loans rejected due to lack of collateral
• 14-17% NPL ratio in microfinance
• SBP mandates explainable AI for credit decisions

The Solution — ForiFlow:
✅ Scores SMEs using alternative data (digital payments, ECIB history)
✅ SHAP explainability for every decision — SBP audit-ready
✅ Early Warning System detects defaults 60-90 days in advance
✅ One-command Docker deployment for bank demos

Built with: FastAPI ⚡ React ⚡ XGBoost ⚡ SHAP ⚡ Docker

🔗 GitHub: https://github.com/Idreesi8/ForiFlow

Open for fintech collaborations and AI/ML roles. DM me!

#AI #Fintech #Pakistan #MachineLearning #CreditScoring #ExplainableAI #FullStack`,
  },
];

function color(code, text) {
  return `\x1b[${code}m${text}\x1b[0m`;
}

function clipboardPayload(step) {
  if (step.text) return step.text;
  return [
    `Title: ${step.title}`,
    `Description: ${step.desc}`,
    `URL: ${step.link}`,
  ].join("\n");
}

function copyWithClipboardy(text) {
  const clipboardy = require("clipboardy");
  if (typeof clipboardy.writeSync === "function") {
    clipboardy.writeSync(text);
    return true;
  }
  if (clipboardy.default && typeof clipboardy.default.writeSync === "function") {
    clipboardy.default.writeSync(text);
    return true;
  }
  return false;
}

function copyWithPowerShell(text) {
  const encoded = Buffer.from(text, "utf16le").toString("base64");
  const result = spawnSync(
    "powershell",
    [
      "-NoProfile",
      "-Command",
      `$t = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('${encoded}')); Set-Clipboard -Value $t`,
    ],
    { windowsHide: true },
  );
  return result.status === 0;
}

function openUrl(target) {
  if (process.platform === "win32") {
    spawnSync("cmd", ["/c", "start", "", target], { detached: true, stdio: "ignore" });
  } else if (process.platform === "darwin") {
    spawnSync("open", [target], { detached: true, stdio: "ignore" });
  } else {
    spawnSync("xdg-open", [target], { detached: true, stdio: "ignore" });
  }
}

function openHelper() {
  openUrl(HELPER_HTML);
  console.log(color("32", "✅ LinkedIn Helper opened in browser!"));
  console.log("👉 Click 'Copy' buttons and paste into LinkedIn");
  console.log(color("36", `🌐 Your LinkedIn: ${PROFILE}`));
}

function pageLooksMissing(status, body) {
  const snippet = String(body || "").toLowerCase();
  return (
    status === 404 ||
    snippet.includes("this page doesn't exist") ||
    snippet.includes("this page doesn&#39;t exist") ||
    snippet.includes("page not found")
  );
}

function checkPage(url) {
  return new Promise((resolve) => {
    const req = https.get(
      url,
      {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
          Accept: "text/html",
        },
        timeout: 8000,
      },
      (res) => {
        let body = "";
        res.on("data", (chunk) => {
          if (body.length < 8000) body += chunk.toString("utf8");
        });
        res.on("end", () => resolve(!pageLooksMissing(res.statusCode, body)));
      },
    );
    req.on("error", () => resolve(true));
    req.on("timeout", () => {
      req.destroy();
      resolve(true);
    });
  });
}

function copyText(text) {
  try {
    if (copyWithClipboardy(text)) return "clipboardy";
  } catch {
    // fall through
  }
  if (process.platform === "win32" && copyWithPowerShell(text)) return "powershell";
  return null;
}

function waitForEnter(prompt) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(prompt, () => {
      rl.close();
      resolve();
    });
  });
}

async function main() {
  if (!fs.existsSync(HELPER_HTML)) {
    console.log(color("31", "linkedin-helper.html is missing from the project root."));
    process.exit(1);
  }

  for (let index = 0; index < STEPS.length; index += 1) {
    const step = STEPS[index];
    const payload = clipboardPayload(step);

    console.log("");
    console.log(color("36", `=== STEP ${index + 1}: ${step.name} ===`));

    const method = copyText(payload);
    if (method) {
      console.log(color("32", "✅ Text copied to clipboard!"));
    } else {
      console.log(color("33", "Clipboard API unavailable — opening the HTML helper."));
      openHelper();
    }

    const reachable = await checkPage(step.url);
    if (!reachable) {
      console.log(
        color(
          "33",
          "⚠️ LinkedIn page not accessible. Opening fallback HTML helper instead...",
        ),
      );
      openHelper();
    } else {
      openUrl(step.url);
      console.log(color("36", `🌐 Browser opened: ${step.url}`));
    }

    console.log("👉 Just press Ctrl+V to paste");
    if (step.title) {
      console.log(color("33", "Featured fields on clipboard: Title, Description, and URL (one block)."));
    }
    await waitForEnter(color("33", "⏳ Press Enter in terminal when done..."));
  }

  console.log("");
  console.log(color("32", "All LinkedIn steps queued. Remaining posts are in linkedin/POST_*.txt"));
}

main().catch((error) => {
  console.error(color("31", error.message || String(error)));
  process.exit(1);
});
