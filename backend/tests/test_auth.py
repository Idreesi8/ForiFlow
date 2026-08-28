"""JWT login and route protection."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from config import JWT_ALGORITHM, JWT_EXPIRE_HOURS
from services.auth_service import create_access_token
from tests.conftest import (
    STRONG_APPLICANT,
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_USERNAME,
)

pytestmark = pytest.mark.auth


def test_login_returns_bearer_token(anonymous_client: TestClient) -> None:
    response = anonymous_client.post(
        "/auth/login",
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == JWT_EXPIRE_HOURS * 3600
    assert body["username"] == TEST_ADMIN_USERNAME
    assert body["role"] == "admin"
    payload = jwt.decode(
        body["access_token"],
        "test-jwt-secret-foriflow-32b-min",
        algorithms=[JWT_ALGORITHM],
    )
    assert payload["sub"] == TEST_ADMIN_USERNAME
    assert payload["role"] == "admin"


def test_login_rejects_wrong_password(anonymous_client: TestClient) -> None:
    response = anonymous_client.post(
        "/auth/login",
        json={"username": TEST_ADMIN_USERNAME, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "Incorrect username or password" in response.json()["detail"]


def test_health_and_root_are_public(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/health").status_code == 200
    assert anonymous_client.get("/").status_code == 200


def test_docs_remain_public(anonymous_client: TestClient) -> None:
    assert anonymous_client.get("/docs").status_code == 200
    assert anonymous_client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/score"),
        ("get", "/score/applications"),
        ("get", "/ews/alerts"),
        ("post", "/ews/monitor"),
        ("get", "/explain/1"),
        ("post", "/explain/1"),
    ],
)
def test_protected_routes_return_401_without_token(
    anonymous_client: TestClient, method: str, path: str
) -> None:
    request = getattr(anonymous_client, method)
    kwargs = {}
    if method == "post" and path == "/score":
        kwargs["json"] = STRONG_APPLICANT
    elif method == "post" and path == "/ews/monitor":
        kwargs["json"] = {
            "borrower_id": 1,
            "month_number": 1,
            "installment_status": "On Time",
            "bureau_balance": 1,
            "pos_cash_balance": 1,
            "data_source_primary": "POS",
        }
    response = request(path, **kwargs)
    assert response.status_code == 401, response.text
    assert response.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_score_succeeds_with_token(client: TestClient) -> None:
    response = client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201, response.text


def test_expired_token_is_rejected(anonymous_client: TestClient) -> None:
    token = create_access_token(
        username=TEST_ADMIN_USERNAME,
        role="admin",
        expires_delta=timedelta(seconds=-1),
    )
    response = anonymous_client.get(
        "/score/applications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_analyst_token_can_score(
    anonymous_client: TestClient,
    db_session_factory,
) -> None:
    from models.database import User
    from services.auth_service import hash_password

    db = db_session_factory()
    try:
        db.add(
            User(
                username="analyst1",
                hashed_password=hash_password("analyst-password"),
                role="analyst",
            )
        )
        db.commit()
    finally:
        db.close()

    login = anonymous_client.post(
        "/auth/login",
        json={"username": "analyst1", "password": "analyst-password"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    response = anonymous_client.post(
        "/score",
        json=STRONG_APPLICANT,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


def test_seed_admin_requires_password_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.seed_admin import main

    monkeypatch.delenv("FORIFLOW_ADMIN_PASSWORD", raising=False)
    assert main([]) == 1
