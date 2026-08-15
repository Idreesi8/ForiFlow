# Deploying ForiFlow

This is the path a relationship manager follows on a Windows or Linux laptop
before a bank demo. Deeper model notes live in [`backend/README.md`](../backend/README.md).

## Prerequisites

- Docker Desktop 4.x (Windows / macOS) or Docker Engine with the Compose plugin
- Trained artefacts in `backend/ml/` (`foriflow_model.pkl`, `scaler.pkl`,
  `shap_explainer.pkl`, `feature_names.json`)

Verify the CLI:

```bash
docker compose version
```

On this project Docker Desktop is often a **per-user** install. If `docker` is
not recognized, either reopen the terminal or prepend:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
```

If the CLI works but Compose says it cannot open
`//./pipe/dockerDesktopLinuxEngine`, start Docker Desktop and wait for the
whale icon to settle. Containers with `restart: unless-stopped` come back on
their own.

## One-command start

```bash
./start.sh          # Linux, macOS, Git Bash
.\start.ps1         # Windows PowerShell
```

Or:

```bash
docker compose up --build -d
```

The script waits until `/health` returns 200, then prints:

```
ForiFlow is running at http://localhost:3000
```

| URL | What |
|-----|------|
| http://localhost:3000 | Officer dashboard |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/health | Liveness |

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FORIFLOW_DATABASE_URL` | `sqlite:////data/foriflow.db` in Docker, `sqlite:///./foriflow.db` locally | SQLAlchemy URL. Four slashes = absolute path. |
| `FORIFLOW_SCORING_ENGINE` | `auto` | `auto` prefers the ensemble; `ml` refuses to start without artefacts; `surrogate` forces the linear fallback. |
| `FORIFLOW_LOG_LEVEL` | `INFO` | Python logging level. |
| `VITE_API_BASE_URL` | `/api` | Axios base. Leave relative so nginx / Vite can proxy. |
| `VITE_DEV_API_TARGET` | `http://127.0.0.1:8000` | Vite proxy target for local `npm run dev`. |

Set them under `environment:` in `docker-compose.yml` or in a local `.env`
(gitignored).

## Persistence

SQLite lives on the named volume `foriflow-data`. Applications and alerts
survive `docker compose down` and laptop reboots.

```bash
docker compose down       # stop, keep data
docker compose down -v    # wipe the demo database
```

## Confirm the real model is serving

```bash
docker compose logs backend | grep "Scoring engine ready"
```

`ensemble-xgb-rf-...` is the trained model. `surrogate-linear-v1` means the
artefacts were not baked into the image. Rebuild after training, or pass
`--build-arg REQUIRE_MODEL=false` only if you intend to demo the UI alone.

Startup logs may show scikit-learn `InconsistentVersionWarning` (artefacts
trained on 1.8, image resolved 1.9). Three hold-out-style applicants scored
identically in the container and on the training machine; `pytest` inside the
container is 80 passed. Re-check after any rebuild:

```bash
docker compose exec backend pytest
```

## Everyday commands

| Task | Command |
|------|---------|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f` |
| Rebuild after code changes | `docker compose up -d --build` |
| Shell | `docker compose exec backend bash` |

## Air-gapped laptop

```bash
docker compose build
docker save foriflow-backend:1.0.0 foriflow-frontend:1.0.0 -o foriflow-images.tar
```

Copy the tarball and `docker-compose.yml` to the demo machine:

```bash
docker load -i foriflow-images.tar
docker compose up -d
```

## Troubleshooting

| Symptom | Cause and fix |
|---------|----------------|
| `docker` is not recognized | PATH points at a missing Program Files install. Use the `$env:PATH` line above, or reopen Cursor after installing Docker Desktop. |
| `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine` | Engine is down. Start Docker Desktop; do not rebuild. |
| `ERROR: backend/ml artefacts missing` | Train with `python -m ml.train_real_model` in `backend/`, or build with `--build-arg REQUIRE_MODEL=false`. |
| `pip` `ReadTimeoutError` | Slow link. Rebuild; the pip cache mount resumes instead of starting over. |
| `Ports are not available` | A local `uvicorn` or `npm run dev` holds 8000 or 3000. Stop it. |
| Dashboard shows "API offline" | Backend still loading the ensemble (tens of seconds on a cold start) or unhealthy. `docker compose logs backend`. |
| `502 Bad Gateway` | Backend container exited. Check its logs. |
| `start.sh: bash\r: No such file` | CRLF line endings. `.gitattributes` prevents this; `git add --renormalize .` if it already happened. |
| Windows blocks `start.ps1` | `powershell -ExecutionPolicy Bypass -File .\start.ps1` |
