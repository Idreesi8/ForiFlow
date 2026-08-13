# ForiFlow Frontend

React 18 + Vite + Tailwind CSS dashboard for **ForiFlow** — the credit officer
workspace for SME scoring and Early Warning System (EWS) surveillance at
Pakistani banks. All amounts are shown in PKR (with crore/lakh shorthand),
bureau references are ECIB, and every decision is backed by an explainable SHAP
report for SBP adverse-action reporting.

## Quick start

The backend must be running first, because the dashboard reads live data:

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Then, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The app is served at **http://localhost:3000** — the port is fixed in
`vite.config.js` because the FastAPI service only allows CORS from that origin.

To point the UI at a different API host, create `frontend/.env.local`:

```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Workspaces

| Route           | Sidebar item   | What it does                                                        |
| --------------- | -------------- | ------------------------------------------------------------------- |
| `/`             | Dashboard      | Portfolio KPIs, decision mix, score distribution, latest assessment  |
| `/scoring`      | Credit Scoring | Application intake form, live score gauge and SHAP rationale         |
| `/shap/:id`     | SHAP Reports   | Application picker plus the full feature-attribution chart           |
| `/alerts`       | EWS Alerts     | Monthly monitoring run and the alert queue with resolve actions      |
| `/applications` | Applications   | Sortable, searchable register with a "View SHAP" action per row      |

## Components

- `components/ScoreDial.jsx` — semi-circular Recharts gauge (0-100) with the
  three policy bands (red 0-40 Rejected, yellow 41-70 Manual Review, green
  71-100 Approved), a needle at the exact score and a band legend.
- `components/ApplicationForm.jsx` — all twelve applicant fields with ranges
  mirroring the backend's Pydantic validation. Submits `POST /score` and renders
  the result in the dial. Three sample profiles load a demo applicant for each
  policy band.
- `components/ShapWaterfall.jsx` — horizontal contribution chart from
  `POST /explain/{id}`, with base value, positive/negative totals, the credit
  file narrative and the compliance note.
- `components/EWSAlertFeed.jsx` — alert table from `GET /ews/alerts` with red
  severity badges, days-to-default and `PATCH /ews/alerts/{id}/resolve`.
- `components/ApplicationTable.jsx` — sortable register from
  `GET /score/applications` with search, decision filters and per-row SHAP links.
- `components/MonitoringPanel.jsx` — records a surveillance month through
  `POST /ews/monitor` so alerts can be raised from the UI.

## API layer

`src/api/client.js` holds a single Axios instance plus one function per
endpoint. `apiErrorMessage()` converts failures into officer-readable text: it
expands FastAPI's 422 validation lists into `field: message` strings and tells
the user how to start the backend when the API is unreachable.

## Notes

- The score is oriented so **higher is better** even though the API field is
  named `risk_score`; the band colours follow that orientation everywhere.
- SQLite returns timestamps without a timezone suffix, so `parseApiDate()`
  interprets naive values as UTC before rendering them in local (PKT) time.
- Tailwind v4 is configured through the `@tailwindcss/vite` plugin; the brand
  palette and shared component classes live in `src/index.css`.
