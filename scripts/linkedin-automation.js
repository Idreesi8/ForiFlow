/**
 * LinkedIn helper: copy ready-to-paste ForiFlow copy, then open the right page.
 * LinkedIn blocks injected browser automation; Ctrl+V is the last human step.
 *
 *   npm run linkedin
 *   node scripts/linkedin-automation.js
 */

const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const ROOT = path.resolve(__dirname, "..");
const TEMP_HTML = path.join(ROOT, "temp", "linkedin-helper.html");

const STEPS = [
  {
    name: "About Section",
    url: "https://www.linkedin.com/in/ramzan-idreesi/edit/about/",
    text: `AI Software Engineer | Building Credit Intelligence Systems for Emerging Markets

I build AI-powered fintech solutions that make financial services accessible to the underserved.

Over the past 3 months, I developed ForiFlow — an end-to-end SME Credit Scoring & Early Warning System for Pakistani banks. It uses alternative data (digital payments, ECIB, inventory turnover) to score unbanked SMEs without collateral, provides SHAP explainability for SBP compliance, and detects portfolio deterioration 60-90 days before default.

Tech Stack: FastAPI, React, XGBoost, Random Forest, SHAP, Docker, PostgreSQL

I'm passionate about using Machine Learning and Full-Stack Development to solve real-world problems in financial inclusion. Currently open to full-time AI/ML roles, freelance fintech projects, and bank technology partnerships.

📩 Open for collaborations. Let's build something impactful together.`,
  },
  {
    name: "Featured Project",
    url: "https://www.linkedin.com/in/ramzan-idreesi/edit/featured/",
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

function writeHelperHtml() {
  const blocks = STEPS.map((step, index) => {
    const body = escapeHtml(clipboardPayload(step));
    return `<section>
  <h2>${index + 1}. ${escapeHtml(step.name)}</h2>
  <p><a href="${escapeHtml(step.url)}" target="_blank">${escapeHtml(step.url)}</a></p>
  <textarea readonly onclick="this.select()">${body}</textarea>
</section>`;
  }).join("\n");

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ForiFlow LinkedIn helper</title>
  <style>
    body { font-family: Segoe UI, sans-serif; max-width: 720px; margin: 2rem auto; color: #0f172a; }
    textarea { width: 100%; min-height: 180px; font: 14px/1.45 Consolas, monospace; }
    h1 { font-size: 1.4rem; }
    section { margin: 1.5rem 0; }
  </style>
</head>
<body>
  <h1>ForiFlow LinkedIn copy</h1>
  <p>Click a box, Ctrl+A, Ctrl+C, then paste on the LinkedIn page.</p>
  ${blocks}
</body>
</html>`;

  fs.mkdirSync(path.dirname(TEMP_HTML), { recursive: true });
  fs.writeFileSync(TEMP_HTML, html, "utf8");
  return TEMP_HTML;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function openUrl(url) {
  if (process.platform === "win32") {
    spawnSync("cmd", ["/c", "start", "", url], { detached: true, stdio: "ignore" });
  } else if (process.platform === "darwin") {
    spawnSync("open", [url], { detached: true, stdio: "ignore" });
  } else {
    spawnSync("xdg-open", [url], { detached: true, stdio: "ignore" });
  }
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
  let helperOpened = false;

  for (let index = 0; index < STEPS.length; index += 1) {
    const step = STEPS[index];
    const payload = clipboardPayload(step);

    console.log("");
    console.log(color("36", `=== STEP ${index + 1}: ${step.name} ===`));

    const method = copyText(payload);
    if (method) {
      console.log(color("32", "✅ Text copied to clipboard!"));
    } else {
      const htmlPath = writeHelperHtml();
      console.log(color("33", "Clipboard API unavailable — opened a helper page with selectable text."));
      if (!helperOpened) {
        openUrl(htmlPath);
        helperOpened = true;
      }
    }

    openUrl(step.url);
    console.log(color("36", `🌐 Browser opened: ${step.url}`));
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
