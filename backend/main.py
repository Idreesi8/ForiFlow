"""ForiFlow API — SME credit scoring and Early Warning System for Pakistani banks.

Run locally from the ``backend`` directory:

    uvicorn main:app --reload --port 8000

Interactive docs are then served at http://localhost:8000/docs (development
mode only; production never serves them).

``FORIFLOW_ENV=production`` (set by docker-compose.yml) makes the API refuse to
start on an unsafe configuration: see ``services.security_config`` and
SECURITY.md.
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

import config
from models.database import SessionLocal, engine, init_db
from routers import audit, auth, borrowers, ews, explain, model, policy, portfolio, score
from schemas import HealthResponse, ReadinessCheck, ReadinessResponse
from services import model_registry, policy_service
from services.audit_service import new_request_id
from services.auth_service import jwt_secret_problem
from services.http_security import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from services.scoring_service import get_scoring_service
from services.security_config import configuration_report

API_VERSION = "2.3.1"

logging.basicConfig(
    level=os.getenv("FORIFLOW_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("foriflow")


class UnsafeConfiguration(RuntimeError):
    """Production refuses to start; the message names the settings, not values."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Check the configuration, prepare the database, load the model.

    The scoring engine is resolved here rather than on first request: loading the
    trained ensemble pulls in xgboost, shap and scikit-learn, which costs tens of
    seconds on a cold filesystem cache and would otherwise stall the first
    applicant a credit officer submits.
    """
    report = configuration_report()
    logger.info("Starting ForiFlow API v%s (%s mode)", API_VERSION, report.environment)
    for warning in report.warnings:
        logger.warning("Configuration: %s", warning)
    if not report.ok:
        for problem in report.problems:
            logger.error("Configuration: %s", problem)
        raise UnsafeConfiguration(
            "Refusing to start in production: " + " | ".join(report.problems)
        )
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


_PRIVATE_FIELDS = frozenset({"password", "borrower_identifier"})


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
        # Pydantic adds a documentation link per error; it says nothing useful
        # to an officer and names the library version.
        error.pop("url", None)
        errors.append(error)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT")
        else 422,
        content={"detail": jsonable_encoder(errors)},
    )


async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Convert database failures into a 503 without leaking SQL internals."""
    logger.exception("Database error while handling %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "detail": "The scoring database is currently unavailable.",
            "request_id": getattr(request.state, "request_id", None),
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Any other failure: a generic 500 with the request id, never a traceback.

    The full traceback goes to the server log under the same request id, so
    an administrator can find it from what the officer reports.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled error (request %s) on %s %s",
        request_id,
        request.method,
        request.url.path,
        exc_info=exc,
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error. Quote the request id to an administrator.",
            "request_id": request_id,
        },
    )
    # This response is built outside the header middleware; add the basics.
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request_id:
        response.headers["X-Request-ID"] = request_id
    return response


ENDPOINT_GROUPS = [
    "/auth/login",
    "/auth/logout",
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
    "/health/live",
    "/health/ready",
]


def create_app() -> FastAPI:
    """Build the API from the current environment.

    A factory so the tests can build a production-mode app (docs off, CORS
    closed) without restarting the interpreter. ``app`` below is the one
    uvicorn serves.
    """
    docs = config.docs_enabled()
    application = FastAPI(
        title="ForiFlow API",
        description=(
            "Alternative-data credit scoring and Early Warning System for Pakistani SMEs. "
            "All amounts are in PKR. Bureau-style fields are officer-entered (no live "
            "ECIB connector). Built with SBP-oriented explainability in mind; not SBP-certified."
        ),
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Starlette runs the middleware added LAST first. Order, outermost first:
    # request id -> security headers -> body size -> CORS -> routes.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        # The token travels in the Authorization header, never in a cookie,
        # so cross-origin credentials are not needed.
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    application.add_middleware(BodySizeLimitMiddleware, max_bytes=config.max_body_bytes())
    application.add_middleware(SecurityHeadersMiddleware)

    @application.middleware("http")
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

    for router in (auth, score, explain, ews, model, portfolio, borrowers, audit, policy):
        application.include_router(router.router)

    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)

    @application.get("/", tags=["Meta"], summary="Service metadata")
    async def root() -> dict[str, str | list[str] | None]:
        """Return basic service metadata and the available endpoint groups."""
        return {
            "service": "ForiFlow API",
            "version": API_VERSION,
            "docs": "/docs" if docs else None,
            "endpoints": ENDPOINT_GROUPS,
        }

    @application.get(
        "/health", response_model=HealthResponse, tags=["Meta"], summary="Health summary"
    )
    async def health() -> HealthResponse:
        """Status, version, database connectivity and the serving model.

        Kept from earlier releases for the dashboard and scripts. Always 200
        while the process runs; use ``/health/ready`` to gate traffic. Holds no
        secret, no host name and no configuration value.
        """
        database_ok = _database_reachable()
        scorer = get_scoring_service()
        return HealthResponse(
            status="ok" if database_ok else "degraded",
            service="ForiFlow API",
            version=API_VERSION,
            database="connected" if database_ok else "unavailable",
            scoring_engine=scorer.engine,
            model_version=scorer.model_version,
            scoring_fallback_reason=scorer.fallback_reason,
        )

    @application.get("/health/live", tags=["Meta"], summary="Liveness")
    async def health_live() -> dict[str, str]:
        """The process is up and answering. Checks nothing else."""
        return {"status": "alive"}

    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["Meta"],
        summary="Readiness",
        responses={503: {"model": ReadinessResponse, "description": "Not ready."}},
    )
    async def health_ready() -> JSONResponse:
        """200 when the API can serve officers, 503 (naming what is missing) when not.

        Ready means: the database answers, the trained model is serving (or
        the fallback was pinned on purpose), and the configuration can sign
        tokens. Each check gives a short reason, never a value.
        """
        checks: list[ReadinessCheck] = []
        database_ok = _database_reachable()
        checks.append(
            ReadinessCheck(
                name="database",
                ok=database_ok,
                detail="reachable" if database_ok else "not reachable",
            )
        )
        scorer = get_scoring_service()
        model_ok = scorer.fallback_reason not in ("artifacts_missing", "load_failed")
        checks.append(
            ReadinessCheck(
                name="model",
                ok=model_ok,
                detail=(
                    f"{scorer.engine} engine serving"
                    if model_ok
                    else f"trained model not serving ({scorer.fallback_reason})"
                ),
            )
        )
        secret_problem = jwt_secret_problem(config.jwt_secret_key())
        report = configuration_report()
        config_ok = secret_problem is None and report.ok
        checks.append(
            ReadinessCheck(
                name="configuration",
                ok=config_ok,
                detail="loaded" if config_ok else "unsafe or incomplete; see the server log",
            )
        )
        ready = all(check.ok for check in checks)
        body = ReadinessResponse(
            status="ready" if ready else "not_ready",
            version=API_VERSION,
            environment=report.environment,
            checks=checks,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(),
        )

    return application


def _database_reachable() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("Health check could not reach the database.")
        return False
    return True


app = create_app()
