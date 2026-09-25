# Scripts

## Screenshot capture

The dashboard needs a JWT login, so use the authenticated capture script. From
the repository root, with the stack already running (`start.bat`):

```bash
python scripts/capture_auth2.py              # logs in with FORIFLOW_ADMIN_* from .env
python scripts/cleanup_test_applications.py  # keep only the newest Khan Traders row
```

The older unauthenticated capture tools remain:

```bash
npm run capture
```

or:

```bash
python scripts/capture.py
```

Prerequisites: Docker containers running (`start.bat` / `docker compose up -d`)
or local servers (`uvicorn` on :8000 and `npm run dev` on :3000). The Node
script polls `/health` and the dashboard first; if they are down it starts
Docker Compose. It does **not** stop the servers afterwards.

Output directory: `docs/screenshots/`

Files written: `01-dashboard-overview.png` … `07-swagger-docs.png` at
1920×1080, light colour scheme.

The scoring form uses the 0–100 intake scale (`payment_history_score=95`,
`order_consistency=100`). Values of `0.95` / `1.0` in older notes were 0–1
fractions and would produce a useless Rejected screenshot.
