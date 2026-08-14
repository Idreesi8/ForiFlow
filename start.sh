#!/usr/bin/env bash
#
# One-command start for the ForiFlow demo stack.
# Works on Linux, macOS, and Windows through Git Bash.
#
#   ./start.sh              build if needed and start in the background
#   ./start.sh --no-build   skip the image build
#
set -euo pipefail

cd "$(dirname "$0")"

FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://localhost:8000"

# Compose v2 ships as a "docker compose" subcommand; v1 as its own binary.
if docker compose version >/dev/null 2>&1; then
  compose() { docker compose "$@"; }
elif command -v docker-compose >/dev/null 2>&1; then
  compose() { docker-compose "$@"; }
else
  echo "ERROR: Docker Compose was not found." >&2
  echo "Install Docker Desktop (Windows/macOS) or the docker-compose-plugin (Linux)." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: the Docker daemon is not responding." >&2
  echo "Start Docker Desktop (or 'sudo systemctl start docker') and run this again." >&2
  exit 1
fi

build_flag="--build"
for arg in "$@"; do
  [ "$arg" = "--no-build" ] && build_flag=""
done

echo "Starting ForiFlow (first build downloads ~1.5 GB of Python wheels)..."
# shellcheck disable=SC2086  # build_flag is intentionally word-split or empty
compose up -d $build_flag

# The backend loads the trained ensemble, scaler and SHAP explainer before it
# serves anything, so announcing the URL immediately would be premature.
printf "Waiting for the scoring engine to load"
ready=0
for _ in $(seq 1 60); do
  if command -v curl >/dev/null 2>&1; then
    if curl --silent --fail --max-time 3 "$BACKEND_URL/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
  else
    # No curl: fall back to the container's own healthcheck verdict.
    if compose ps 2>/dev/null | grep -qi "foriflow-backend.*healthy"; then
      ready=1
      break
    fi
  fi
  printf "."
  sleep 3
done
printf "\n"

if [ "$ready" -ne 1 ]; then
  echo "WARNING: the backend did not report healthy in time." >&2
  echo "Check the logs with: docker compose logs backend" >&2
  exit 1
fi

echo
echo "ForiFlow is running at $FRONTEND_URL"
echo "  API docs:  $BACKEND_URL/docs"
echo "  Logs:      docker compose logs -f"
echo "  Stop:      docker compose down"
