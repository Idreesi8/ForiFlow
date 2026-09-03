#!/usr/bin/env bash
#
# Everyday start for the ForiFlow stack.
#
#   ./start.sh              start existing images (no rebuild)
#   ./start.sh --rebuild    rebuild images, then start
#
set -euo pipefail

cd "$(dirname "$0")"

FRONTEND_URL="http://127.0.0.1:3000"
BACKEND_URL="http://127.0.0.1:8000"
TIMEOUT_SECONDS=240

if docker compose version >/dev/null 2>&1; then
  compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose "$@"; }
else
  echo "ERROR: Docker Compose was not found." >&2
  echo "Install Docker Desktop (Windows/macOS) or the docker-compose-plugin (Linux)." >&2
  exit 1
fi

echo "=== ForiFlow start ==="
echo "[1/5] Checking Docker..."

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker Desktop is not running (or the engine is still starting)." >&2
  echo "Start Docker Desktop, wait for the whale icon to settle, then run this again." >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "ERROR: No .env file in the repo root." >&2
  echo "Copy .env.example to .env and fill POSTGRES_* and JWT_SECRET_KEY." >&2
  exit 1
fi

rebuild=0
for arg in "$@"; do
  case "$arg" in
    --rebuild) rebuild=1 ;;
    --no-build) rebuild=0 ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: ./start.sh [--rebuild]" >&2
      exit 1
      ;;
  esac
done

if [ "$rebuild" -eq 1 ]; then
  echo "[2/5] Rebuilding images, then starting (docker compose up -d --build)..."
  compose up -d --build
else
  echo "[2/5] Starting existing images (docker compose up -d, no rebuild)..."
  compose up -d
fi

echo "[3/5] Waiting for db, backend, and frontend to report healthy..."
echo "(Backend start_period is 120s while the ensemble loads. Polling compose health, not a fixed sleep.)"

deadline=$((SECONDS + TIMEOUT_SECONDS))
healthy=0
while [ "$SECONDS" -lt "$deadline" ]; do
  db_h=$(compose ps --format json 2>/dev/null | sed -n 's/.*"Service":"db".*"Health":"\([^"]*\)".*/\1/p' | head -n 1)
  be_h=$(compose ps --format json 2>/dev/null | sed -n 's/.*"Service":"backend".*"Health":"\([^"]*\)".*/\1/p' | head -n 1)
  fe_h=$(compose ps --format json 2>/dev/null | sed -n 's/.*"Service":"frontend".*"Health":"\([^"]*\)".*/\1/p' | head -n 1)
  echo "  db=${db_h:-missing}  backend=${be_h:-missing}  frontend=${fe_h:-missing}"
  if [ "${db_h:-}" = "healthy" ] && [ "${be_h:-}" = "healthy" ] && [ "${fe_h:-}" = "healthy" ]; then
    healthy=1
    break
  fi
  sleep 5
done

if [ "$healthy" -ne 1 ]; then
  echo "ERROR: Timed out after ${TIMEOUT_SECONDS}s waiting for all services to become healthy." >&2
  echo "Check logs with: docker compose logs" >&2
  exit 1
fi

echo "All three services are healthy."

echo "[4/5] Checking whether an officer user already exists..."
count="$(
  compose exec -T backend python -c 'from sqlalchemy import select, func; from models.database import SessionLocal, User; db = SessionLocal(); print(db.scalar(select(func.count()).select_from(User))); db.close()' 2>/dev/null || true
)"
count="$(printf '%s\n' "$count" | tr -d '\r' | grep -E '^[0-9]+$' | tail -n 1 || true)"

if [ -n "$count" ] && [ "$count" -gt 0 ]; then
  echo "Found $count officer user(s). You can log in at the dashboard."
else
  echo "No admin user found - run: docker compose exec backend python -m scripts.seed_admin"
  echo "Set FORIFLOW_ADMIN_PASSWORD in .env first. Seeding is not run automatically."
fi

echo "[5/5] Ready."
echo
echo "Dashboard : $FRONTEND_URL"
echo "API       : $BACKEND_URL"
echo "API docs  : $BACKEND_URL/docs"
echo "Stop      : docker compose down"
echo
echo "Postgres, the API, and the dashboard are bound to 127.0.0.1 only."
echo "They are not reachable from other machines on the network."
echo
