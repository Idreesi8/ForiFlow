"""Process environment for ForiFlow.

Secrets never live in source. Docker Compose injects variables from ``.env``;
local uvicorn and one-off scripts load the same file via python-dotenv.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


def load_env_files() -> None:
    """Load repo-root then backend ``.env`` if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(BACKEND_DIR / ".env")


load_env_files()


def env_flag(name: str, default: str = "false") -> bool:
    """Parse a boolean environment flag (1/true/yes/on)."""
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def is_sqlite_url(url: str) -> bool:
    """Return True when ``url`` is a SQLAlchemy SQLite URL."""
    return url.startswith("sqlite:")


def database_url() -> str:
    """Resolve the SQLAlchemy URL.

    Precedence: ``FORIFLOW_DATABASE_URL`` if set, else Postgres parts
    (``POSTGRES_USER``, ``POSTGRES_PASSWORD``, ``POSTGRES_HOST``,
    ``POSTGRES_PORT``, ``POSTGRES_DB``), else local SQLite.
    """
    explicit = os.getenv("FORIFLOW_DATABASE_URL", "").strip()
    if explicit:
        return explicit

    user = os.getenv("POSTGRES_USER", "").strip()
    host = os.getenv("POSTGRES_HOST", "").strip()
    if user and host:
        password = os.getenv("POSTGRES_PASSWORD", "")
        db_name = os.getenv("POSTGRES_DB", user).strip() or user
        port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
        return (
            f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{quote_plus(db_name)}"
        )

    return "sqlite:///./foriflow.db"


JWT_ALGORITHM = "HS256"
# Every token carries this issuer and is refused without it.
JWT_ISSUER = "foriflow"
DEFAULT_JWT_EXPIRE_MINUTES = 480
# A session shorter than 15 minutes is unusable for an officer; one longer than
# 12 hours outlives a working day and widens the window for a stolen token.
JWT_EXPIRE_MINUTES_RANGE = (15, 720)


def jwt_expire_minutes() -> int:
    """Token lifetime from ``FORIFLOW_JWT_EXPIRE_MINUTES`` (default 480 = 8 hours)."""
    text = os.getenv("FORIFLOW_JWT_EXPIRE_MINUTES", "").strip()
    if not text:
        return DEFAULT_JWT_EXPIRE_MINUTES
    try:
        minutes = int(text)
    except ValueError:
        raise RuntimeError("FORIFLOW_JWT_EXPIRE_MINUTES must be a whole number.") from None
    low, high = JWT_EXPIRE_MINUTES_RANGE
    if not low <= minutes <= high:
        raise RuntimeError(f"FORIFLOW_JWT_EXPIRE_MINUTES must be between {low} and {high}.")
    return minutes


JWT_EXPIRE_MINUTES = jwt_expire_minutes()
# Kept for callers written before 2.3; derived, not configured separately.
JWT_EXPIRE_HOURS = JWT_EXPIRE_MINUTES / 60


def jwt_secret_key() -> str:
    """Return the signing secret. Empty values are rejected at token time."""
    return os.getenv("JWT_SECRET_KEY", "").strip()


# --- Deployment mode (2.3) -------------------------------------------------
#
# ``development`` (the default for a local run) keeps the developer
# conveniences: interactive API docs and the localhost dev-server origins.
# ``production`` (set by docker-compose.yml) refuses to start on an unsafe
# configuration and turns the docs off unless they are asked for explicitly.

APP_ENVIRONMENTS = ("development", "production")


def app_env() -> str:
    """``FORIFLOW_ENV``: ``development`` (default) or ``production``."""
    value = os.getenv("FORIFLOW_ENV", "development").strip().lower() or "development"
    if value not in APP_ENVIRONMENTS:
        raise RuntimeError(
            f"FORIFLOW_ENV must be one of {', '.join(APP_ENVIRONMENTS)}; got {value!r}."
        )
    return value


def is_production() -> bool:
    return app_env() == "production"


# Origins a Vite dev server may run on. Production serves the dashboard and
# the API from one origin (nginx proxies /api), so it needs none.
DEVELOPMENT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
)


def cors_origins() -> list[str]:
    """Allowed browser origins: ``FORIFLOW_CORS_ORIGINS`` (comma separated).

    Unset: the dev-server origins in development, none in production. A
    wildcard is refused in every mode: the API is authenticated, and ``*``
    would let any web page a signed-in officer visits call it.
    """
    text = os.getenv("FORIFLOW_CORS_ORIGINS")
    if text is None or not text.strip():
        return [] if is_production() else list(DEVELOPMENT_CORS_ORIGINS)
    origins = [item.strip().rstrip("/") for item in text.split(",") if item.strip()]
    for origin in origins:
        if "*" in origin:
            raise RuntimeError("FORIFLOW_CORS_ORIGINS cannot contain '*'. List each origin.")
        if not origin.startswith(("http://", "https://")):
            raise RuntimeError(
                f"FORIFLOW_CORS_ORIGINS entry {origin!r} must start with http:// or https://."
            )
    return origins


def docs_enabled() -> bool:
    """Interactive docs (/docs, /redoc, /openapi.json).

    An explicit ``FORIFLOW_ENABLE_DOCS`` wins; otherwise on in development and
    off in production.
    """
    if os.getenv("FORIFLOW_ENABLE_DOCS", "").strip():
        return env_flag("FORIFLOW_ENABLE_DOCS")
    return not is_production()


DEFAULT_MAX_BODY_BYTES = 3 * 1024 * 1024


def max_body_bytes() -> int:
    """Largest request body accepted (``FORIFLOW_MAX_BODY_BYTES``, default 3 MiB).

    The largest legitimate body is a statement CSV, capped at 2,000,000
    characters by its schema; 3 MiB leaves room for its JSON encoding.
    """
    text = os.getenv("FORIFLOW_MAX_BODY_BYTES", "").strip()
    if not text:
        return DEFAULT_MAX_BODY_BYTES
    try:
        value = int(text)
    except ValueError:
        raise RuntimeError("FORIFLOW_MAX_BODY_BYTES must be a whole number.") from None
    if value < 64 * 1024:
        raise RuntimeError("FORIFLOW_MAX_BODY_BYTES must be at least 65536.")
    return value


# Largest facility a manager may approve alone; above it an admin must approve.
# A policy figure the lender sets, not something measured from data.
DEFAULT_MANAGER_APPROVAL_LIMIT_PKR = 2_000_000.0


def manager_approval_limit_pkr() -> float:
    """Return the manager's approval limit from ``MANAGER_APPROVAL_LIMIT_PKR``."""
    text = os.getenv("MANAGER_APPROVAL_LIMIT_PKR", "").strip()
    if not text:
        return DEFAULT_MANAGER_APPROVAL_LIMIT_PKR
    try:
        limit = float(text)
    except ValueError:
        raise RuntimeError("MANAGER_APPROVAL_LIMIT_PKR must be a number.") from None
    if limit < 0:
        raise RuntimeError("MANAGER_APPROVAL_LIMIT_PKR cannot be negative.")
    return limit
