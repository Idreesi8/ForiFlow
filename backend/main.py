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

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from config import env_flag, jwt_secret_key
from models.database import DATABASE_URL, SessionLocal, engine, init_db
from routers import audit, auth, borrowers, ews, explain, model, policy, portfolio, score
from schemas import HealthResponse
from services import model_registry, policy_service
from services.audit_service import new_request_id
from services.auth_service import jwt_secret_problem
from services.scoring_service import get_scoring_service

API_VERSION = "2.2.0"

logging.basicConfig(
    level=os.getenv("FORIFLOW_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("foriflow")

# In Docker (nginx) and under `vite dev` the dashboard is served on port 3000
# and calls /api on its own origin, so CORS is not involved. These origins
# only matter for a dev server started on another port.
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
    secret_problem = jwt_secret_problem(jwt_secret_key())
    if secret_problem:
        logger.error("%s POST /auth/login will fail until it is fixed.", secret_problem)
    init_db()
    scorer = get_scoring_service()
    logger.info("Scoring engine ready: %s", scorer.model_version)
    if scorer.fallback_reason in ("artifacts_missing", "load_failed"):
        logger.error(
            "The trained model is NOT serving (%s). Scores come from the fallback "
            "formula and are recorded as scoring_engine='surrogate'.",
            scorer.fallback_reason,
        )
    # Record which model is serving before the first officer scores anything.
    # Scoring registers it too, so a failure here costs the early record only.
    try:
        with SessionLocal() as session:
            model_registry.ensure_registered(session, scorer)
            active = policy_service.active_policy(session)
            session.commit()
            logger.info(
                "Credit policy in force: %s v%s (configurable demo policy; the model "
                "recommends, an officer decides).",
                active.name,
                active.version,
            )
    except (SQLAlchemyError, HTTPException):
        logger.exception("Could not record the serving model and policy at startup.")
    yield
    engine.dispose()
    logger.info("ForiFlow API stopped.")


_ENABLE_DOCS = env_flag("FORIFLOW_ENABLE_DOCS", "true")

app = FastAPI(
    title="ForiFlow API",
    description=(
        "Alternative-data credit scoring and Early Warning System for Pakistani SMEs. "
        "All amounts are in PKR. Bureau-style fields are officer-entered (no live "
        "ECIB connector). Built with SBP-oriented explainability in mind; not SBP-certified."
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



@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Give every request an id, for the audit trail and the response header.

    An ``X-Request-ID`` sent by a proxy is kept if it is a plain token;
    anything else is replaced, so the header cannot be used to write
    arbitrary text into the audit trail.
    """
    request.state.request_id = new_request_id(request.headers.get("x-request-id"))
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.include_router(auth.router)
app.include_router(score.router)
app.include_router(explain.router)
app.include_router(ews.router)
app.include_router(model.router)
app.include_router(portfolio.router)
app.include_router(borrowers.router)
app.include_router(audit.router)
app.include_router(policy.router)


_PRIVATE_FIELDS = frozenset({"password", "borrower_identifier"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI's default 422 body, minus passwords and national identifiers.

    The default handler echoes every rejected input back, which would put a
    typed password, CNIC or NTN into the response body (and any proxy or
    client log of it). A whole-body error echoes the body, so those keys are
    removed from it as well.
    """
    errors = []
    for error in exc.errors():
        error = dict(error)
        if any(str(part).lower() in _PRIVATE_FIELDS for part in error.get("loc", ())):
            error["input"] = "[redacted]"
        elif isinstance(error.get("input"), dict):
            error["input"] = {
                key: "[redacted]" if str(key).lower() in _PRIVATE_FIELDS else value
                for key, value in error["input"].items()
            }
        if isinstance(error.get("ctx"), dict) and "error" in error["ctx"]:
            # A validator's own exception object; only its message is JSON.
            error["ctx"] = {**error["ctx"], "error": str(error["ctx"]["error"])}
        errors.append(error)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT")
        else 422,
        content={"detail": jsonable_encoder(errors)},
    )


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
        "endpoints": [
            "/auth/login",
            "/score",
            "/score/applications",
            "/score/stats",
            "/explain/{application_id}",
            "/ews/monitor",
            "/ews/alerts",
            "/borrowers",
            "/borrowers/{borrower_ref}/history",
            "/portfolio/summary",
            "/portfolio/reminders",
            "/model/evaluation",
            "/model/comparison",
            "/model/early-warning",
            "/model/drift",
            "/model/fairness",
            "/model/versions",
            "/audit/logs",
            "/policy/active",
            "/policy/versions",
            "/score/applications/{id}/decision",
            "/score/applications/{id}/decision-history",
        ],
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
    scorer = get_scoring_service()

    return HealthResponse(
        status="ok" if database_status == "connected" else "degraded",
        service="ForiFlow API",
        version=API_VERSION,
        database=database_status,
        scoring_engine=scorer.engine,
        model_version=scorer.model_version,
        scoring_fallback_reason=scorer.fallback_reason,
    )
