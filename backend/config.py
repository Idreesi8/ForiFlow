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
JWT_EXPIRE_HOURS = 8


def jwt_secret_key() -> str:
    """Return the signing secret. Empty values are rejected at token time."""
    return os.getenv("JWT_SECRET_KEY", "").strip()


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
