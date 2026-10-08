# ForiFlow Frontend

React 18 + Vite + Tailwind CSS dashboard for **ForiFlow** — the credit officer
workspace for SME scoring and Early Warning System (EWS) surveillance at
Pakistani banks. All amounts are shown in PKR (with crore/lakh shorthand).
Bureau-style fields are officer-entered (no live ECIB connector). SHAP
explanations are stored on-premise to support an SBP-oriented review; ForiFlow
is not SBP-certified.

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

The app is served at **http://localhost:3000**, the port fixed in
`vite.config.js`.

API calls go to the relative path `/api`, which Vite proxies to
`http://127.0.0.1:8000` in development and nginx proxies to the backend
container in Docker. Because the request is same-origin either way, CORS never
enters the picture. Point the dev proxy elsewhere with `VITE_DEV_API_TARGET`.

To bypass the proxy and call an absolute API host instead, create
`frontend/.env.local`:

```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Workspaces

| Route           | Sidebar item   | What it does                                                        |
| --------------- | -------------- | ------------------------------------------------------------------- |
| `/login`        | —              | Officer sign-in (JWT)                                               |
| `/`             | Dashboard      | Portfolio KPIs from `GET /score/stats`, model decision mix, score distribution, latest assessment, open alerts |
| `/scoring`      | Credit Scoring | Application intake form, live score gauge, SHAP rationale and, for Manual Review, the decision panel |
| `/shap/:id`     | SHAP Reports   | Application picker, the full feature-attribution chart and the decision on file |
| `/alerts`       | EWS Alerts     | Monthly monitoring of approved facilities; alert queue with Take for review and admin Resolve with a note |
| `/applications` | Applications   | Sortable, searchable register with model and final decision, Pending review filter, and a Review action for admins |

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
- `components/EWSAlertFeed.jsx` — alert queue from `GET /ews/alerts`: the
  API's severity, reason codes and evidence, follow-up (acknowledged by,
  assignee, due date, overdue), and the lifecycle steps for managers
  (acknowledge, assign, due date, action required, resolve, dismiss) with the
  alert's audit history. Closed alerts stay listed.
- `components/EWSOverview.jsx`, `components/EWSFacilityDetail.jsx` — the
  portfolio EWS position and one facility's state, signals, score-history
  chart (baseline drawn apart, overrides marked, "Insufficient history for
  multi-month trend" below three months), recorded months with corrections,
  and its stored timeline.
- `lib/ews.js` — EWS wording and colours only; every threshold and
  classification comes from the API (`lib/ews.test.js` checks that none is
  hard-coded).
- `components/ApplicationTable.jsx` — sortable register from
  `GET /score/applications` with search, model and final decision columns,
  Pending review / Approved / Rejected filters and per-row SHAP or Review links.
- `components/ReviewPanel.jsx` — the decision on file; for a pending Manual
  Review case an admin approves or rejects it with a reason through
  `POST /score/applications/{id}/review`.
- `components/MonitoringPanel.jsx` — records a month for an approved
  facility through `POST /ews/observations` (date, days late, typed figures,
  and a manager's score override with a reason). A month already on file is
  refused; a manager can save the figures as a correction instead.

## API layer

`src/api/client.js` holds a single Axios instance plus one function per
endpoint. `apiErrorMessage()` converts failures into officer-readable text: it
expands FastAPI's 422 validation lists into `field: message` strings and tells
the user how to start the backend when the API is unreachable.

## Notes

- The score is oriented so **higher is better** even though the API field is
  named `risk_score`; the band colours follow that orientation everywhere.
- SQLite (the non-Docker fallback) returns timestamps without a timezone
  suffix, so `parseApiDate()` interprets naive values as UTC before rendering
  them in local (PKT) time.
- Tailwind v4 is configured through the `@tailwindcss/vite` plugin; the brand
  palette and shared component classes live in `src/index.css`.
