"""ForiFlow API — SME credit scoring and Early Warning System for Pakistani banks.

Run locally from the ``backend`` directory:

    uvicorn main:app --reload --port 8000

Interactive docs are then served at http://localhost:8000/docs.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import env_flag
from models.database import DATABASE_URL, engine, init_db
from routers import auth, ews, explain, score
from schemas import HealthResponse
from services.scoring_service import get_scoring_service

API_VERSION = "1.0.0"

logging.basicConfig(
    level=os.getenv("FORIFLOW_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("foriflow")

# The React dashboard runs on port 3000 by default, 3001 when that port is
# already taken, and 5173 if started through Vite's own default.
ALLOWED_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Prepare the database on startup and dispose the pool on shutdown.

    The scoring engine is resolved here rather than on first request: loading the
    trained ensemble pulls in xgboost, shap and scikit-learn, which costs tens of
    seconds on a cold filesystem cache and would otherwise stall the first
    applicant a credit officer submits.
    """
    logger.info("Starting ForiFlow API v%s", API_VERSION)
    if not os.getenv("JWT_SECRET_KEY", "").strip():
        logger.warning("JWT_SECRET_KEY is not set; POST /auth/login will fail.")
    init_db()
    logger.info("Scoring engine ready: %s", get_scoring_service().model_version)
    yield
    engine.dispose()
    logger.info("ForiFlow API stopped.")


_ENABLE_DOCS = env_flag("FORIFLOW_ENABLE_DOCS", "true")

app = FastAPI(
    title="ForiFlow API",
    description=(
        "Alternative-data credit scoring and Early Warning System for Pakistani SMEs. "
        "All amounts are in PKR; bureau features reference ECIB and decisions follow "
        "SBP fair-lending expectations."
    ),
    version=API_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _ENABLE_DOCS else None,
    redoc_url="/redoc" if _ENABLE_DOCS else None,
    openapi_url="/openapi.json" if _ENABLE_DOCS else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(score.router)
app.include_router(explain.router)
app.include_router(ews.router)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Convert database failures into a 503 without leaking SQL internals."""
    logger.exception("Database error while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The scoring database is currently unavailable."},
    )


@app.get("/", tags=["Meta"], summary="Service metadata")
async def root() -> dict[str, str | list[str]]:
    """Return basic service metadata and the available endpoint groups."""
    return {
        "service": "ForiFlow API",
        "version": API_VERSION,
        "docs": "/docs",
        "endpoints": ["/score", "/explain/{application_id}", "/ews/monitor"],
    }


@app.get("/health", response_model=HealthResponse, tags=["Meta"], summary="Health check")
async def health() -> HealthResponse:
    """Report liveness together with database connectivity."""
    database_status = "connected"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check could not reach the database.")
        database_status = "unavailable"

    return HealthResponse(
        status="ok" if database_status == "connected" else "degraded",
        service="ForiFlow API",
        version=API_VERSION,
        database=database_status,
    )
