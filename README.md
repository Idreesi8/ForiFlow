# ForiFlow

Alternative-data credit scoring and an Early Warning System for Pakistani SMEs.
A credit officer submits an application, gets a 0-100 risk score with a SHAP
explanation of *why*, and the EWS flags borrowers whose monthly score decays
before they miss a payment. All amounts are in PKR; bureau features reference
ECIB and decisions follow SBP fair-lending expectations.

This page covers running the whole stack with Docker for a demo. For deeper
detail see [`backend/README.md`](backend/README.md) (model training, feature
engineering, endpoints) and [`frontend/README.md`](frontend/README.md).

## What runs where

| Container | Image | Port | Contents |
| --- | --- | --- | --- |
| `foriflow-backend` | `python:3.11-slim` | 8000 | FastAPI, SQLite, trained XGBoost + Random Forest ensemble, SHAP explainer |
| `foriflow-frontend` | `nginx:1.27-alpine` | 3000 | React 18 dashboard built by Vite, served as static files |

The dashboard calls `/api/...` on its own origin and nginx forwards it to the
backend, stripping the prefix (`/api/score` becomes `/score`). Because the
browser only ever talks to `localhost:3000`, the request is same-origin and
**CORS is not involved in the Docker deployment at all** — one less thing to go
wrong on an unfamiliar laptop.

## Prerequisites

Docker Desktop 4.x on Windows or macOS, or Docker Engine with the Compose
plugin on Linux. Nothing else — Python and Node are only needed for the
non-Docker workflow at the end.

Verify with `docker compose version`.

## Before the first build: the trained model

The model artefacts in `backend/ml/` (`foriflow_model.pkl`, `scaler.pkl`,
`shap_explainer.pkl`, `feature_names.json`, ~34 MB) are **gitignored**, so a
fresh clone does not contain them. The backend image copies them in, and the
build deliberately **fails** if they are missing rather than shipping an image
that silently serves fallback scores to a bank.

If you cloned this repository, train them once:

```bash
cd backend
pip install -r requirements.txt
python -m ml.train_real_model
```

To demo the interface without a trained model, build with the surrogate instead:

```bash
docker compose build --build-arg REQUIRE_MODEL=false backend
```

## Quick start

```bash
./start.sh
```

On Windows PowerShell:

```powershell
.\start.ps1
```

Or without the helper scripts:

```bash
docker compose up -d --build
```

The script builds the images, starts both containers, waits for the scoring
engine to finish loading, and prints:

```
ForiFlow is running at http://localhost:3000
```

Open that address. The API's interactive docs are at
<http://localhost:8000/docs>.

Two expectations for the first run: the build downloads roughly 1.5 GB of
Python wheels (numpy, scikit-learn, xgboost, shap), and the backend then spends
tens of seconds loading the ensemble and SHAP explainer before it answers. The
frontend waits for the backend's healthcheck, so the dashboard will not come up
showing "API offline".

## Confirming the real model is serving

The engine is logged once at startup:

```bash
docker compose logs backend | grep "Scoring engine ready"
```

`ensemble-xgb-rf-...` is the trained model. `surrogate-linear-v1` means the
artefacts were not found and the linear fallback is answering — scores are
plausible but not the real model's. Every `/score` response also carries the
active `model_version`.

To refuse to start at all without the trained ensemble, set
`FORIFLOW_SCORING_ENGINE: ml` in `docker-compose.yml`.

### About the `InconsistentVersionWarning` in the logs

Startup logs a handful of scikit-learn warnings of the form "Trying to unpickle
estimator ... from version 1.8.0 when using version 1.9.0". `requirements.txt`
declares minimum versions, so the image can resolve newer libraries than the
ones that trained the model.

This was verified rather than assumed: the same three applicants (a strong, a
weak and a borderline case) score identically in the container and on the
training machine — 79.4, 3.49 and 10.2 — with SHAP contributions matching to the
decimal, and all 80 tests pass inside the container. If you ever rebuild months
from now and want the same assurance, re-run the suite:

```bash
docker compose exec backend pytest
```

The ML contract tests check SHAP additivity, score/decision consistency and that
a strong applicant still outranks a weak one, so a genuinely incompatible
library version would fail them rather than pass quietly.

## Demo data persists

SQLite lives on the named volume `foriflow-data`, mounted at `/data` in the
backend, so applications and alerts scored during a demo survive restarts and
`docker compose down`.

```bash
docker compose down       # stop, keep the data
docker compose down -v    # stop and wipe the database for a clean demo
```

## Everyday commands

| Task | Command |
| --- | --- |
| Follow logs | `docker compose logs -f` |
| Container and health status | `docker compose ps` |
| Restart just the API | `docker compose restart backend` |
| Rebuild after code changes | `docker compose up -d --build` |
| Shell into the backend | `docker compose exec backend bash` |
| Run the backend test suite | `docker compose exec backend pytest` |

## Taking it to a laptop with no internet

Build once on a machine with connectivity, then move the images:

```bash
docker compose build
docker save foriflow-backend:1.0.0 foriflow-frontend:1.0.0 -o foriflow-images.tar
```

Copy `foriflow-images.tar` and `docker-compose.yml` to the demo laptop:

```bash
docker load -i foriflow-images.tar
docker compose up -d
```

The trained model travels inside the backend image, so the demo laptop needs
neither the datasets nor a Python toolchain.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ERROR: backend/ml artefacts missing` during build | The model was never trained in this clone. Run the training command above, or build with `--build-arg REQUIRE_MODEL=false`. |
| Build fails at `npm ci` | `package-lock.json` is out of step with `package.json`. Run `npm install` in `frontend/` to refresh it, then rebuild. |
| `pip` `ReadTimeoutError` during the backend build | A slow connection. Just run the build again: the wheel cache mount resumes from what already downloaded rather than starting over. |
| Dashboard loads but shows "API offline" | The backend is still loading, or unhealthy. Check `docker compose ps` and `docker compose logs backend`. |
| `Ports are not available` / `address already in use` | Something else holds 3000 or 8000 (often a leftover `npm run dev` or `uvicorn`). Stop it, or remap the left-hand side of `ports:` in `docker-compose.yml`. |
| `502 Bad Gateway` from nginx | The backend container exited. `docker compose logs backend` will show why. |
| `start.sh: /usr/bin/env: bash\r: No such file` | The file was checked out with Windows line endings. `.gitattributes` prevents this; if it already happened, run `git add --renormalize .`. |
| Windows blocks `start.ps1` | `powershell -ExecutionPolicy Bypass -File .\start.ps1` |

## Running without Docker

Two terminals, from the repository root:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

The dashboard is at <http://localhost:3000> and Vite proxies `/api` to
`127.0.0.1:8000`, matching the Docker path exactly (override the target with
`VITE_DEV_API_TARGET`). The backend also allows CORS from ports 3000, 3001 and
5173 for the case where the dashboard calls it directly.

## Layout

```
docker-compose.yml      # the two-container demo stack
start.sh / start.ps1    # one-command launchers
backend/
  Dockerfile            # python:3.11-slim + libgomp1 for xgboost
  main.py               # FastAPI app, CORS, lifespan, health
  ml/                   # feature schema, training script, trained artefacts
  routers/              # /score, /explain, /ews
  services/             # scoring engine (trained ensemble + surrogate), EWS
frontend/
  Dockerfile            # Vite build, served by nginx
  nginx.conf            # SPA fallback and the /api proxy
  src/                  # dashboard, charts, API client
```
