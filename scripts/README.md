# Scripts

## Screenshot capture

How to run capture: `npm run capture` or `python scripts/capture.py`.

From the repository root:

```bash
# Node (install Playwright once)
cd scripts
npm install
# Slow links: Playwright's default 30s download timeout is too short for the 190 MB browser.
set PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000
npx playwright install chromium
cd ../frontend
npm run capture
```

```bash
# Python alternative
pip install playwright
playwright install chromium
python scripts/capture.py
```

Prerequisites: Docker containers running or local servers (`uvicorn` on :8000
and `npm run dev` on :3000). The script polls `/health` and the dashboard
first; if they are down it starts Docker Compose (Node script) or tells you
to start them (Python script). It does **not** kill the servers afterwards.

Output directory: `docs/screenshots/`

Files written: `01-dashboard-overview.png` … `07-swagger-docs.png` at
1920×1080, light colour scheme.

The scoring form uses the 0–100 intake scale (`payment_history_score=95`,
`order_consistency=100`). Values of `0.95` / `1.0` in older notes were 0–1
fractions and would produce a useless Rejected screenshot.

## Repo bootstrap

`setup-repo.sh` / `setup-repo.bat` initialise git if needed, stage the
professionalisation files, and print the GitHub push command. Safe to run on
an existing clone — it will not rewrite history.
