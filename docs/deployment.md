# Deploying ForiFlow

On-premise stack for a bank pilot: PostgreSQL, a FastAPI scoring API with
JWT login, and the officer dashboard. Secrets never live in git. Deeper
model notes live in [`backend/README.md`](../backend/README.md).

## Prerequisites

- Docker Desktop 4.x (Windows / macOS) or Docker Engine with the Compose
  plugin (`docker compose` or `docker-compose`)
- A copy of [`.env.example`](../.env.example) saved as `.env` in the
  **repository root**. `.env` is gitignored. Never commit it.
- Trained scoring artefacts in `backend/ml/` (`foriflow_model.pkl`,
  `scaler.pkl`, `shap_explainer.pkl`, `feature_names.json`). The default
  image build (`REQUIRE_MODEL=true`) fails if they are missing.

Verify the CLI:

```bash
docker compose version
```

On this project Docker Desktop is often a **per-user** install. If `docker`
is not recognized, either reopen the terminal or prepend:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
```

If the CLI works but Compose cannot open
`//./pipe/dockerDesktopLinuxEngine`, start Docker Desktop and wait for the
whale icon to settle.

Create the env file (then replace every placeholder — see below):

```bash
# Linux, macOS, Git Bash
cp .env.example .env

# Windows PowerShell
Copy-Item .env.example .env
```

## Required environment variables

Compose interpolates these from `.env`. **`docker compose up` will fail to
start if any of them are unset** (`:?` in `docker-compose.yml`). None of
them belong in the compose file itself.

| Variable | Purpose |
|----------|---------|
| `POSTGRES_USER` | PostgreSQL role created on first start. |
| `POSTGRES_PASSWORD` | Unique per deployment. |
| `POSTGRES_DB` | Database name. |
| `JWT_SECRET_KEY` | Unique per deployment. **Minimum 32 characters.** Used to sign officer JWTs with HMAC-SHA256. |

Example shape in `.env` (placeholders only — generate real values):

```
POSTGRES_USER=foriflow
POSTGRES_PASSWORD=<generate-a-random-password>
POSTGRES_DB=foriflow
JWT_SECRET_KEY=<generate-a-random-32-char-value>
```

[`.env.example`](../.env.example) also sets `POSTGRES_HOST=127.0.0.1` and
`POSTGRES_PORT=5432` for tools that run **on the laptop** against the
published port. Compose overrides `POSTGRES_HOST` to `db` inside the
backend container so the API talks to PostgreSQL on the internal network.

## First-run setup (creating the admin user)

Seeding is **not** automatic on startup. After the backend is healthy,
create the first officer account in a separate step.

Set these in `.env` (the backend `env_file` makes them available to
`docker compose exec`):

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `FORIFLOW_ADMIN_PASSWORD` | Yes for seed | none | Strong random password. The seed script reads it from the environment only — it is not accepted as a CLI flag and is never logged. |
| `FORIFLOW_ADMIN_USERNAME` | No | `admin` | Officer username. |
| `FORIFLOW_ADMIN_ROLE` | No | `admin` | `admin` or `analyst`. Both roles may use scoring and EWS; the value is stored on the user, not a full RBAC matrix. |

Placeholder only:

```
FORIFLOW_ADMIN_USERNAME=admin
FORIFLOW_ADMIN_PASSWORD=<generate-a-strong-random-password>
```

Create the user:

```bash
docker compose exec backend python -m scripts.seed_admin
```

Expected first-run output: `Created admin user 'admin'.` If the username
already exists, the script leaves the hash unchanged unless you pass
`--reset-password`:

```bash
docker compose exec backend python -m scripts.seed_admin --reset-password
```

That replaces the password hash (and role, if `FORIFLOW_ADMIN_ROLE` /
`--role` is set) for the existing username.

## Optional application flags

These have defaults in compose and/or [`.env.example`](../.env.example).
They are not required for Compose interpolation.

| Variable | Default | Purpose |
|----------|---------|---------|
| `FORIFLOW_DATABASE_URL` | unset | If set, this SQLAlchemy URL **wins** over `POSTGRES_*`. Encode `@`, `:`, and `/` in the password. Example shape: `postgresql+psycopg2://foriflow:<url-encoded-password>@db:5432/foriflow` |
| `FORIFLOW_SCORING_ENGINE` | `auto` | See below. |
| `FORIFLOW_LOG_LEVEL` | `INFO` | Python logging level. |
| `FORIFLOW_ENABLE_DOCS` | `true` | Set `false` to disable `/docs`, `/redoc`, and `/openapi.json`. |

### `FORIFLOW_SCORING_ENGINE`

| Value | Behaviour |
|-------|-----------|
| `auto` | Load the trained ensemble when artefacts are present. **This is what a pilot or any real deployment must run.** |
| `ml` | Load the ensemble and **refuse to start** if artefacts are missing or cannot be loaded. |
| `surrogate` | Linear fallback for development and automated tests only. **Must never be used for an actual pilot or production scoring session.** |

Confirm the live engine after startup:

```bash
docker compose logs backend | grep "Scoring engine ready"
```

You want a `ensemble-xgb-rf-...` version string, not `surrogate-linear-v1`.

## Starting the stack

From a clean state (no leftover ForiFlow containers or volumes):

```bash
docker compose down -v --remove-orphans
docker compose up -d --build
```

On Windows, double-click `start.bat`, or run `create-shortcut.bat` once to put
a **ForiFlow** icon on the desktop (it targets `start.bat`). Either starts
existing images with `docker compose up -d`, waits until **db**, **backend**,
and **frontend** are healthy, reminds you to seed if the users table is empty,
and opens http://127.0.0.1:3000. It does **not** rebuild images and does
**not** run `scripts.seed_admin`. After code changes, use `rebuild.bat` or
`.\start.ps1 -Rebuild`. Git Bash / Linux / macOS: `./start.sh` (add
`--rebuild` after code changes).

Startup order follows `docker-compose.yml`: **db** must be healthy before
**backend** starts; **frontend** waits until **backend** is healthy
(nginx resolves `backend`, and the dashboard would otherwise show
"API offline" while the ensemble loads).

### What "healthy" means

These are the healthchecks already in `docker-compose.yml`. Compose marks
a service healthy only after the check succeeds; `start_period` is grace
time before failures count.

| Service | Container | Check | Timing |
|---------|-----------|-------|--------|
| `db` | `foriflow-db` | `pg_isready` as `POSTGRES_USER` against `POSTGRES_DB` | every 5s, timeout 5s, 10 retries, `start_period` 10s |
| `backend` | `foriflow-backend` | HTTP GET `http://127.0.0.1:8000/health` inside the container must return **200** | every 15s, timeout 10s, 5 retries, `start_period` **120s** (ensemble, scaler, and SHAP load before the API accepts traffic) |
| `frontend` | `foriflow-frontend` | `wget --spider http://127.0.0.1:3000/` | every 15s, timeout 5s, 3 retries, `start_period` 10s |

```bash
docker compose ps
```

All three should show `healthy` (or `Up ... (healthy)`).

On backend startup, `init_db()` runs **Alembic `upgrade head`** against
PostgreSQL (revisions `0001_initial` then `0002_users` on an empty
database). Schema is owned by Alembic, not by ad hoc table creation.

Postgres data lives on the named volume `foriflow-pgdata`. It survives
`docker compose down`. Wipe it with `docker compose down -v`.

## Verifying the deployment

Replace the password placeholder with the value from `.env`. Do not paste
real secrets into tickets or chat logs.

1. **Liveness (no token)** — `GET /health` returns **200**:

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health
   ```

   A connected database reports `"database": "connected"` in the JSON body.

2. **Protected route without a token** — **401**:

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/score/applications
   ```

3. **Login, then the same route with a Bearer token** — login **200**, list **200**:

   ```bash
   curl -sS -X POST http://127.0.0.1:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username":"admin","password":"<generate-a-strong-random-password>"}'
   ```

   Use the returned `access_token` (HS256 JWT, 8-hour lifetime):

   ```bash
   curl -sS -o /dev/null -w "%{http_code}\n" \
     -H "Authorization: Bearer <access_token>" \
     http://127.0.0.1:8000/score/applications
   ```

4. **Dashboard** — open http://localhost:3000. An unauthenticated browser is
   redirected to `/login`. After sign-in, the shell should show **API online**.

`GET /` and `/docs` (when `FORIFLOW_ENABLE_DOCS=true`) stay unauthenticated.

## Access points

| URL | What |
|-----|------|
| http://127.0.0.1:3000 | Officer dashboard (nginx on host port **3000**) |
| http://127.0.0.1:8000 | ForiFlow API (uvicorn on host port **8000**) |
| http://127.0.0.1:8000/health | Liveness |
| http://127.0.0.1:8000/docs | Swagger UI (unless docs are disabled) |
| http://127.0.0.1:8000/auth/login | `POST` JSON `{ "username", "password" }` → JWT |

The API, dashboard, and PostgreSQL are published as **`127.0.0.1` only** —
loopback, not the LAN (`127.0.0.1:8000`, `127.0.0.1:3000`, `127.0.0.1:5432`).
This compose stack is a single-laptop pilot. Other machines on a bank network
cannot reach it. Other containers still reach Postgres as hostname `db` on
port 5432.

The dashboard calls `/api` on its own origin; nginx forwards that to the
backend container.

## Everyday commands

| Task | Command |
|------|---------|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f` |
| Rebuild after code changes | `docker compose up -d --build` |
| Seed / rotate admin | `docker compose exec backend python -m scripts.seed_admin` (add `--reset-password` to rotate) |
| Stop, keep Postgres data | `docker compose down` |
| Stop and wipe volumes | `docker compose down -v` |

## Air-gapped laptop

```bash
docker compose build
docker save foriflow-backend:1.0.0 foriflow-frontend:1.0.0 postgres:16.6 -o foriflow-images.tar
```

Copy the tarball, `docker-compose.yml`, and a filled `.env` (never the
example placeholders) to the destination machine:

```bash
docker load -i foriflow-images.tar
docker compose up -d
```

Then seed the admin user as in [First-run setup](#first-run-setup-creating-the-admin-user).

## Troubleshooting

| Symptom | Cause and fix |
|---------|----------------|
| `docker` is not recognized | PATH points at a missing Program Files install. Use the `$env:PATH` line above, or reopen the terminal after installing Docker Desktop. |
| `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` | Engine is down. Start Docker Desktop; do not rebuild. |
| Compose error `Set POSTGRES_* in .env` or `Set JWT_SECRET_KEY in .env` | Required variable missing from `.env`. Copy `.env.example` and fill the placeholders. |
| `ERROR: backend/ml artefacts missing` | Train with `python -m ml.train_real_model` in `backend/`, or (UI-only demo) build with `--build-arg REQUIRE_MODEL=false`. A pilot must ship the ensemble. |
| `pip` `ReadTimeoutError` | Slow link. Rebuild; the pip cache mount resumes instead of starting over. |
| `Ports are not available` | A local `uvicorn` or `npm run dev` holds 8000 or 3000. Stop it. |
| Dashboard shows "API offline" | Backend still inside the 120s health `start_period` (ensemble load) or unhealthy. `docker compose logs backend`. |
| `502 Bad Gateway` | Backend container exited. Check its logs. |
| Login 401 with a password you just set | Seed was not run, or the hash was not rotated (`--reset-password`). |
| `Scoring engine ready: surrogate-linear-v1` | Artefacts were not baked into the image, or `FORIFLOW_SCORING_ENGINE=surrogate`. Rebuild with artefacts; use `auto` or `ml` for a pilot. |
| `start.sh: bash\r: No such file` | CRLF line endings. `.gitattributes` prevents this; `git add --renormalize .` if it already happened. |
| Windows opens `start.ps1` in Notepad | Double-click `start.bat` or the desktop ForiFlow shortcut (`create-shortcut.bat`). Those call PowerShell with `-ExecutionPolicy Bypass`. |
