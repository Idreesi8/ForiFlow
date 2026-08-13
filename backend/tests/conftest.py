"""Shared pytest fixtures: isolated in-memory database and API client."""

from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from models.database import Base, get_db
from services.scoring_service import ScoringService, get_scoring_service

# The app resolves its scoring engine during startup. Pinning the surrogate keeps
# the suite fast and deterministic by not loading xgboost and shap for tests that
# override the dependency anyway; ``ml_service`` loads the real model explicitly.
os.environ.setdefault("FORIFLOW_SCORING_ENGINE", "surrogate")

STRONG_APPLICANT: dict[str, Any] = {
    "applicant_name": "Ayesha Siddiqui",
    "business_name": "Siddiqui Textiles (Faisalabad)",
    "loan_amount_pkr": 2_400_000,
    "tenure_months": 36,
    "monthly_digital_payments": 3_200_000,
    "payment_history_score": 92,
    "inventory_turnover": 9.5,
    "order_consistency": 90,
    "existing_debt_pkr": 400_000,
    "cash_flow_proxy": 850_000,
    "years_in_operation": 12,
    "num_employees": 45,
}

WEAK_APPLICANT: dict[str, Any] = {
    "applicant_name": "Bilal Ahmed",
    "business_name": "Ahmed Auto Spares (Karachi)",
    "loan_amount_pkr": 3_000_000,
    "tenure_months": 12,
    "monthly_digital_payments": 25_000,
    "payment_history_score": 18,
    "inventory_turnover": 0.6,
    "order_consistency": 15,
    "existing_debt_pkr": 4_500_000,
    "cash_flow_proxy": 60_000,
    "years_in_operation": 0.5,
    "num_employees": 2,
}

MID_APPLICANT: dict[str, Any] = {
    "applicant_name": "Hina Raza",
    "business_name": "Raza Kiryana Store (Lahore)",
    "loan_amount_pkr": 1_200_000,
    "tenure_months": 24,
    "monthly_digital_payments": 500_000,
    "payment_history_score": 62,
    "inventory_turnover": 5.0,
    "order_consistency": 58,
    "existing_debt_pkr": 900_000,
    "cash_flow_proxy": 220_000,
    "years_in_operation": 4,
    "num_employees": 8,
}


@pytest.fixture(name="db_session_factory")
def db_session_factory_fixture() -> Generator[sessionmaker[Session], None, None]:
    """Create a fresh in-memory SQLite schema for each test.

    ``StaticPool`` keeps every connection pointed at the same in-memory
    database, which SQLite otherwise scopes per connection.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(name="client")
def client_fixture(
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    """Return a TestClient using the test schema and the surrogate scorer.

    The scoring engine is pinned to :class:`ScoringService` so that the decision
    policy, persistence and explanation plumbing are asserted against fixed,
    documented arithmetic. Whether trained artefacts happen to be present on the
    machine running the suite then cannot change the outcome. The trained
    ensemble has its own contract tests in ``test_ml_model.py``.
    """

    def override_get_db() -> Generator[Session, None, None]:
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    # Must be a zero-argument callable: FastAPI reads a dependency's signature, so
    # passing the class itself would turn ``ScoringService.__init__`` parameters
    # into request parameters and reject every payload with a 422.
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(name="ml_service", scope="session")
def ml_service_fixture():
    """Load the trained ensemble, skipping the test module when it is absent."""
    from ml.features import artifacts_available

    if not artifacts_available():
        pytest.skip("Trained model artefacts not present; run ml/train_real_model.py")

    from services.scoring_service import MLScoringService

    return MLScoringService.from_artifacts()


@pytest.fixture(name="ml_client")
def ml_client_fixture(
    client: TestClient, ml_service
) -> Generator[TestClient, None, None]:
    """A TestClient wired to the trained ensemble instead of the surrogate."""
    app.dependency_overrides[get_scoring_service] = lambda: ml_service
    yield client
    app.dependency_overrides[get_scoring_service] = lambda: ScoringService()


@pytest.fixture(name="scored_application_id")
def scored_application_id_fixture(client: TestClient) -> int:
    """Score a strong applicant and return the persisted application id."""
    response = client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201, response.text
    return int(response.json()["application_id"])
