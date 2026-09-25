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


# --- roles and officer accounts -------------------------------------------------


def _add_analyst(db_session_factory, username: str = "analyst1") -> dict[str, str]:
    from models.database import User
    from services.auth_service import hash_password
    from tests.conftest import bearer_header

    db = db_session_factory()
    try:
        db.add(
            User(
                username=username,
                hashed_password=hash_password("analyst-password"),
                role="analyst",
            )
        )
        db.commit()
    finally:
        db.close()
    return bearer_header(username=username, role="analyst")


def test_me_returns_the_signed_in_account(client: TestClient) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["username"] == TEST_ADMIN_USERNAME
    assert body["role"] == "admin"
    assert "hashed_password" not in body


def test_role_comes_from_the_database_not_the_token(
    client: TestClient, db_session_factory
) -> None:
    """A token that claims admin for an analyst account must not grant admin."""
    from tests.conftest import bearer_header

    _add_analyst(db_session_factory)
    forged = bearer_header(username="analyst1", role="admin")
    assert client.get("/auth/users", headers=forged).status_code == 403


def test_admin_creates_an_analyst_who_can_log_in(client: TestClient) -> None:
    created = client.post(
        "/auth/users",
        json={"username": "officer.two", "password": "a-long-password-1"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "analyst"
    assert "password" not in created.json() and "hashed_password" not in created.json()

    listed = client.get("/auth/users").json()
    assert [user["username"] for user in listed] == [TEST_ADMIN_USERNAME, "officer.two"]

    login = client.post(
        "/auth/login", json={"username": "officer.two", "password": "a-long-password-1"}
    )
    assert login.status_code == 200 and login.json()["role"] == "analyst"


def test_user_creation_rejects_short_passwords_and_duplicates(client: TestClient) -> None:
    short = client.post("/auth/users", json={"username": "officer3", "password": "short-pw"})
    assert short.status_code == 422

    placeholder = client.post(
        "/auth/users",
        json={"username": "officer3", "password": "CHANGE_ME_ADMIN_PASSWORD"},
    )
    assert placeholder.status_code == 422
    assert "placeholder" in placeholder.json()["detail"]

    duplicate = client.post(
        "/auth/users",
        json={"username": TEST_ADMIN_USERNAME, "password": "another-long-password"},
    )
    assert duplicate.status_code == 409


def test_analyst_cannot_manage_users_or_resolve_alerts(
    client: TestClient, db_session_factory
) -> None:
    analyst = _add_analyst(db_session_factory)
    assert client.get("/auth/users", headers=analyst).status_code == 403
    denied = client.post(
        "/auth/users",
        json={"username": "sneaky", "password": "a-long-password-1"},
        headers=analyst,
    )
    assert denied.status_code == 403
    assert "admin" in denied.json()["detail"]
    # 403 is decided before the alert is looked up, so no alert is needed.
    assert client.patch("/ews/alerts/1/resolve", headers=analyst).status_code == 403
    # Analysts keep read access to the alert queue.
    assert client.get("/ews/alerts", headers=analyst).status_code == 200


# --- secret and password policy -------------------------------------------------


def test_jwt_secret_must_be_long_and_not_the_placeholder() -> None:
    from services.auth_service import jwt_secret_problem

    assert jwt_secret_problem("") is not None
    assert "31 characters" in jwt_secret_problem("x" * 31)
    assert "placeholder" in jwt_secret_problem("CHANGE_ME_JWT_SECRET_KEY_AT_LEAST_32_CHARS")
    assert jwt_secret_problem("x" * 32) is None


def test_short_jwt_secret_refuses_to_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET_KEY", "too-short-secret")
    with pytest.raises(RuntimeError, match="at least 32"):
        create_access_token(username=TEST_ADMIN_USERNAME, role="admin")


def test_seed_admin_rejects_a_short_password() -> None:
    from scripts.seed_admin import seed_admin

    with pytest.raises(ValueError, match="at least 12"):
        seed_admin(username="admin", password="8charpwd", role="admin")
