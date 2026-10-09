"""2.3 security hardening: authentication, RBAC, data exposure, API and configuration.

Every role rule is checked against the API directly; the dashboard hiding a
button is never treated as the control.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select

import config
from main import create_app
from models.database import Alert, Application, AuditLog, LoginAttempt, RevokedToken, User
from services import login_guard
from services.audit_service import Action
from services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    password_problem,
    pwd_context,
)
from services.security_config import configuration_report
from tests.conftest import (
    STRONG_APPLICANT,
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_USERNAME,
    WEAK_APPLICANT,
    bearer_header,
)

ANALYST_PASSWORD = "river-mango-lantern-42"
MANAGER_PASSWORD = "copper-falcon-meadow-17"


@pytest.fixture(name="officers")
def officers_fixture(db_session_factory) -> dict[str, dict[str, str]]:
    """An analyst and a manager next to the conftest admin; their headers."""
    with db_session_factory() as session:
        session.add_all(
            [
                User(username="analyst1", hashed_password=hash_password(ANALYST_PASSWORD), role="analyst"),
                User(username="manager1", hashed_password=hash_password(MANAGER_PASSWORD), role="manager"),
            ]
        )
        session.commit()
    return {
        "admin": bearer_header(),
        "manager": bearer_header("manager1", "manager"),
        "analyst": bearer_header("analyst1", "analyst"),
    }


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/auth/login",
        json={"username": username, "password": password},
        headers={"Authorization": ""},
    )


def _actions(db_session_factory, action: str) -> list[AuditLog]:
    with db_session_factory() as session:
        return list(session.scalars(select(AuditLog).where(AuditLog.action == action)))


# --------------------------------------------------------------------------
# Authentication


def test_a_valid_login_returns_a_token_with_id_issuer_and_expiry(anonymous_client: TestClient) -> None:
    response = _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in", "username", "role"}
    claims = decode_access_token(body["access_token"])
    assert claims["iss"] == config.JWT_ISSUER
    assert len(claims["jti"]) == 32
    assert claims["exp"] - claims["iat"] == config.JWT_EXPIRE_MINUTES * 60
    assert TEST_ADMIN_PASSWORD not in response.text


def test_unknown_user_and_wrong_password_get_the_same_answer(anonymous_client: TestClient) -> None:
    wrong_password = _login(anonymous_client, TEST_ADMIN_USERNAME, "not-the-password-at-all")
    unknown_user = _login(anonymous_client, "nobody-here", "not-the-password-at-all")
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {"detail": "Incorrect username or password"}


@pytest.mark.parametrize(
    "make_token",
    [
        pytest.param(lambda: "not-a-jwt", id="garbage"),
        pytest.param(lambda: "a.b.c", id="three-dots"),
        pytest.param(
            lambda: create_access_token(
                username=TEST_ADMIN_USERNAME, role="admin", expires_delta=timedelta(seconds=-5)
            ),
            id="expired",
        ),
        pytest.param(
            lambda: jwt.encode(
                {"sub": TEST_ADMIN_USERNAME, "role": "admin", "iat": 1, "exp": 4102444800,
                 "iss": "foriflow", "jti": "x" * 32},
                "a-different-secret-that-is-long-enough!!",
                algorithm="HS256",
            ),
            id="wrong-signature",
        ),
        pytest.param(
            lambda: jwt.encode(
                {"sub": TEST_ADMIN_USERNAME, "role": "admin", "iat": 1, "exp": 4102444800},
                config.jwt_secret_key(),
                algorithm="HS256",
            ),
            id="pre-2.3-token-without-jti-or-issuer",
        ),
        pytest.param(
            lambda: jwt.encode(
                {"sub": TEST_ADMIN_USERNAME, "role": "admin", "iat": 1, "exp": 4102444800,
                 "iss": "someone-else", "jti": "y" * 32},
                config.jwt_secret_key(),
                algorithm="HS256",
            ),
            id="wrong-issuer",
        ),
        pytest.param(
            lambda: jwt.encode(
                {"sub": TEST_ADMIN_USERNAME, "role": "admin", "iat": 1, "exp": 4102444800,
                 "iss": "foriflow", "jti": "z" * 32},
                None,
                algorithm="none",
            ),
            id="alg-none",
        ),
    ],
)
def test_bad_tokens_are_refused(anonymous_client: TestClient, make_token) -> None:
    response = anonymous_client.get("/auth/me", headers={"Authorization": f"Bearer {make_token()}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def _protected_routes() -> list[APIRoute]:
    from routers import audit, auth, borrowers, ews, explain, model, policy, portfolio, score

    routes = []
    for module in (audit, auth, borrowers, ews, explain, model, policy, portfolio, score):
        for route in module.router.routes:
            if isinstance(route, APIRoute) and route.path != "/auth/login":
                routes.append(route)
    return routes


def _required_roles(route: APIRoute) -> frozenset[str] | None:
    """The roles a route's dependency allows; None for any signed-in officer."""

    def walk(dependant) -> frozenset[str] | None:
        for sub in dependant.dependencies:
            for cell in getattr(sub.call, "__closure__", None) or ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, frozenset):
                    return value
            found = walk(sub)
            if found is not None:
                return found
        return None

    return walk(route.dependant)


def _url(route: APIRoute) -> str:
    return (
        route.path.replace("{borrower_ref}", "B-000001")
        .replace("{application_id}", "1")
        .replace("{alert_id}", "1")
        .replace("{facility_id}", "1")
        .replace("{borrower_id}", "1")
        .replace("{observation_id}", "1")
        .replace("{policy_id}", "1")
        .replace("{user_id}", "1")
    )


def test_every_route_except_login_and_health_needs_a_token(anonymous_client: TestClient) -> None:
    routes = _protected_routes()
    assert len(routes) > 50
    for route in routes:
        for method in route.methods:
            response = anonymous_client.request(method, _url(route), json={})
            assert response.status_code == 401, f"{method} {route.path} -> {response.status_code}"


def test_role_limited_routes_refuse_lower_roles(client: TestClient, officers) -> None:
    """Every admin-only route refuses analysts and managers; every
    manager-or-admin route refuses analysts. Read from the routes themselves,
    so a new route without its role check shows up here."""
    checked = 0
    for route in _protected_routes():
        allowed = _required_roles(route)
        if allowed is None:
            continue
        for role in ("analyst", "manager"):
            if role in allowed:
                continue
            for method in route.methods:
                response = client.request(method, _url(route), json={}, headers=officers[role])
                assert response.status_code == 403, f"{role} {method} {route.path}"
                checked += 1
    assert checked >= 20


def test_expected_role_boundaries(client: TestClient, officers) -> None:
    """The boundaries the workflow depends on, named explicitly."""
    roles = {f"{','.join(sorted(r.methods))} {r.path}": _required_roles(r) for r in _protected_routes()}
    manager_or_admin = frozenset({"admin", "manager"})
    admin_only = frozenset({"admin"})
    assert roles["POST /score/applications/{application_id}/decision"] == manager_or_admin
    assert roles["POST /score/applications/{application_id}/review"] == manager_or_admin
    assert roles["POST /ews/alerts/{alert_id}/acknowledge"] == manager_or_admin
    assert roles["POST /ews/observations/{observation_id}/correct"] == manager_or_admin
    assert roles["PATCH /borrowers/{borrower_ref}"] == manager_or_admin
    assert roles["POST /policy/versions"] == admin_only
    assert roles["POST /policy/versions/{policy_id}/activate"] == admin_only
    assert roles["GET /audit/logs"] == admin_only
    assert roles["POST /auth/users"] == admin_only
    assert roles["GET /auth/users"] == admin_only
    assert roles["PATCH /auth/users/{user_id}/status"] == admin_only


def test_analyst_cannot_decide_escalate_or_change_policy(client: TestClient, officers) -> None:
    app_id = client.post("/score", json=STRONG_APPLICANT).json()["application_id"]
    analyst = officers["analyst"]
    for decision in ("Approved", "Rejected", "Escalated"):
        response = client.post(
            f"/score/applications/{app_id}/decision",
            json={"decision": decision, "note": "An analyst trying to decide this file."},
            headers=analyst,
        )
        assert response.status_code == 403
    assert client.post("/policy/versions", json={}, headers=analyst).status_code == 403
    assert client.get(f"/score/applications/{app_id}").json()["decision_status"] == "Pending"


def test_manager_cannot_do_admin_work_and_admin_can(client: TestClient, officers) -> None:
    manager = officers["manager"]
    assert client.get("/audit/logs", headers=manager).status_code == 403
    assert client.get("/auth/users", headers=manager).status_code == 403
    new_user = {"username": "newanalyst", "password": "harbour-violet-candle-9", "role": "analyst"}
    assert client.post("/auth/users", json=new_user, headers=manager).status_code == 403
    assert client.post("/policy/versions/1/activate", headers=manager).status_code == 403

    admin = officers["admin"]
    assert client.get("/audit/logs", headers=admin).status_code == 200
    assert client.post("/auth/users", json=new_user, headers=admin).status_code == 201


# --------------------------------------------------------------------------
# Guessed ids (IDOR / BOLA)


def test_guessed_ids_do_not_let_an_analyst_change_records(
    client: TestClient, officers, db_session_factory
) -> None:
    app_id = client.post("/score", json=WEAK_APPLICANT).json()["application_id"]
    client.post(
        f"/score/applications/{app_id}/decision",
        json={"decision": "Approved", "note": "Approved by the admin after a full review."},
    )
    analyst = officers["analyst"]
    borrower_ref = client.get(f"/score/applications/{app_id}").json()["borrower_public_id"]
    before = client.get(f"/borrowers/{borrower_ref}").json()
    response = client.patch(
        f"/borrowers/{borrower_ref}", json={"business_name": "Hijacked Traders"}, headers=analyst
    )
    assert response.status_code == 403
    assert client.get(f"/borrowers/{borrower_ref}").json() == before

    for alert_id in (1, 2, 3, 999):
        for path in (
            f"/ews/alerts/{alert_id}/acknowledge",
            f"/ews/alerts/{alert_id}/dismiss",
            f"/ews/alerts/{alert_id}/resolve",
        ):
            assert client.post(path, json={"note": "x" * 20}, headers=analyst).status_code == 403
    with db_session_factory() as session:
        statuses = {alert.alert_status for alert in session.scalars(select(Alert))}
    assert "Dismissed" not in statuses and "Resolved" not in statuses


def test_unknown_ids_are_404_without_internal_detail(client: TestClient, officers) -> None:
    manager = officers["manager"]
    for method, path, body in (
        ("POST", "/score/applications/987654/decision", {"decision": "Approved", "note": "A note long enough."}),
        ("GET", "/score/applications/987654", None),
        ("GET", "/explain/987654", None),
        ("POST", "/ews/alerts/987654/acknowledge", {}),
        ("GET", "/borrowers/B-999999", None),
    ):
        response = client.request(method, path, json=body, headers=manager)
        assert response.status_code == 404, path
        text = response.text.lower()
        assert "traceback" not in text and "sqlalchemy" not in text and "select " not in text


# --------------------------------------------------------------------------
# Sign-in protection


def test_five_failures_lock_the_username_even_for_the_right_password(
    anonymous_client: TestClient, db_session_factory
) -> None:
    for _ in range(login_guard.MAX_FAILED_ATTEMPTS):
        assert _login(anonymous_client, TEST_ADMIN_USERNAME, "wrong-password-xyz").status_code == 401
    locked = _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert "Try again in" in locked.json()["detail"]
    assert len(_actions(db_session_factory, Action.LOGIN_LOCKED)) == 1
    assert len(_actions(db_session_factory, Action.LOGIN_REFUSED_LOCKED)) == 1

    # The lock is temporary: once it has passed, the right password works.
    with db_session_factory() as session:
        row = session.get(LoginAttempt, TEST_ADMIN_USERNAME)
        row.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).status_code == 200
    with db_session_factory() as session:
        assert session.get(LoginAttempt, TEST_ADMIN_USERNAME) is None


def test_an_unknown_username_locks_the_same_way(anonymous_client: TestClient) -> None:
    """Otherwise a 429 for real accounts only would reveal which exist."""
    answers = [
        _login(anonymous_client, "ghost-user", "wrong-password-xyz").status_code
        for _ in range(login_guard.MAX_FAILED_ATTEMPTS + 1)
    ]
    assert answers == [401] * login_guard.MAX_FAILED_ATTEMPTS + [429]


def test_failures_outside_the_window_do_not_add_up(db_session_factory) -> None:
    now = datetime.now(timezone.utc)
    with db_session_factory() as session:
        for _ in range(login_guard.MAX_FAILED_ATTEMPTS - 1):
            login_guard.record_failure(session, "slow", now)
        later = now + login_guard.FAILURE_WINDOW + timedelta(seconds=1)
        outcome = login_guard.record_failure(session, "slow", later)
        assert outcome.failed_count == 1 and not outcome.locked_now


def test_one_address_is_rate_limited(anonymous_client: TestClient, db_session_factory) -> None:
    statuses = [
        _login(anonymous_client, f"user{n}", "wrong-password-xyz").status_code
        for n in range(login_guard.IP_MAX_ATTEMPTS + 3)
    ]
    assert statuses[: login_guard.IP_MAX_ATTEMPTS] == [401] * login_guard.IP_MAX_ATTEMPTS
    assert statuses[login_guard.IP_MAX_ATTEMPTS :] == [429, 429, 429]
    # A flood is recorded once per window, not once per request.
    assert len(_actions(db_session_factory, Action.LOGIN_RATE_LIMITED)) == 1


# --------------------------------------------------------------------------
# Sign-out and account status


def test_logout_revokes_only_that_token(anonymous_client: TestClient, db_session_factory) -> None:
    first = _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).json()["access_token"]
    second = _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).json()["access_token"]
    one = {"Authorization": f"Bearer {first}"}
    two = {"Authorization": f"Bearer {second}"}
    assert anonymous_client.post("/auth/logout", headers=one).status_code == 204
    assert anonymous_client.get("/auth/me", headers=one).status_code == 401
    assert anonymous_client.post("/score", json=STRONG_APPLICANT, headers=one).status_code == 401
    assert anonymous_client.get("/auth/me", headers=two).status_code == 200
    with db_session_factory() as session:
        stored = list(session.scalars(select(RevokedToken)))
    assert [row.jti for row in stored] == [decode_access_token(first)["jti"]]
    entry = _actions(db_session_factory, Action.LOGOUT)[0]
    assert entry.username == TEST_ADMIN_USERNAME
    assert first not in json.dumps(entry.details)


def test_a_disabled_account_is_shut_out_at_once(
    client: TestClient, officers, db_session_factory
) -> None:
    analyst_token = _login(client, "analyst1", ANALYST_PASSWORD).json()["access_token"]
    analyst = {"Authorization": f"Bearer {analyst_token}"}
    assert client.get("/auth/me", headers=analyst).status_code == 200
    with db_session_factory() as session:
        analyst_id = session.scalar(select(User.id).where(User.username == "analyst1"))

    response = client.patch(
        f"/auth/users/{analyst_id}/status", json={"is_active": False, "reason": "Left the branch."}
    )
    assert response.status_code == 200 and response.json()["is_active"] is False
    assert client.get("/auth/me", headers=analyst).status_code == 401
    refused = _login(client, "analyst1", ANALYST_PASSWORD)
    assert refused.status_code == 403
    assert "disabled" in refused.json()["detail"]
    # A wrong password still gets the ordinary answer: no hint the account exists.
    assert _login(client, "analyst1", "wrong-password-xyz").status_code == 401

    disabled = _actions(db_session_factory, Action.USER_DISABLED)[0]
    assert disabled.previous_state == {"is_active": True}
    assert disabled.details == {"reason": "Left the branch."}
    assert _actions(db_session_factory, Action.LOGIN_REFUSED_DISABLED)

    assert client.patch(f"/auth/users/{analyst_id}/status", json={"is_active": True}).status_code == 200
    assert _login(client, "analyst1", ANALYST_PASSWORD).status_code == 200
    assert _actions(db_session_factory, Action.USER_ENABLED)


def test_admin_cannot_lock_administration_out(client: TestClient, officers, db_session_factory) -> None:
    with db_session_factory() as session:
        admin_id = session.scalar(select(User.id).where(User.username == TEST_ADMIN_USERNAME))
        manager_id = session.scalar(select(User.id).where(User.username == "manager1"))
    assert client.patch(f"/auth/users/{admin_id}/status", json={"is_active": False}).status_code == 409
    assert client.patch("/auth/users/99999/status", json={"is_active": False}).status_code == 404
    assert (
        client.patch(
            f"/auth/users/{admin_id}/status", json={"is_active": False}, headers=officers["manager"]
        ).status_code
        == 403
    )
    with db_session_factory() as session:
        session.add(User(username="admin2", hashed_password=hash_password("glacier-orchid-tunnel-5"), role="admin"))
        session.commit()
        admin2_id = session.scalar(select(User.id).where(User.username == "admin2"))
    # admin2 may disable the first admin, but then not itself (the last one).
    admin2 = bearer_header("admin2", "admin")
    assert client.patch(f"/auth/users/{admin_id}/status", json={"is_active": False}, headers=admin2).status_code == 200
    assert client.patch(f"/auth/users/{admin2_id}/status", json={"is_active": False}, headers=admin2).status_code == 409
    assert manager_id is not None


# --------------------------------------------------------------------------
# Passwords


@pytest.mark.parametrize(
    "password, username",
    [
        ("short-pass", "newofficer"),
        ("Password1234!", "newofficer"),
        ("aaaaaaaaaaaaaaaa", "newofficer"),
        ("1234567890123", "newofficer"),
        ("qwertyuiop2026", "newofficer"),
        ("newofficer-2026-secure", "newofficer"),
        ("CHANGE_ME_ADMIN_PASSWORD", "newofficer"),
        ("x" * 73, "newofficer"),
    ],
)
def test_weak_passwords_are_refused(client: TestClient, password: str, username: str) -> None:
    response = client.post("/auth/users", json={"username": username, "password": password, "role": "analyst"})
    assert response.status_code == 422
    assert password not in response.text


def test_a_strong_passphrase_is_accepted_and_hashed_with_bcrypt(client: TestClient, db_session_factory) -> None:
    password = "harbour violet candle nine"
    assert password_problem(password, "newofficer") is None
    response = client.post("/auth/users", json={"username": "newofficer", "password": password})
    assert response.status_code == 201
    assert "password" not in response.text and "hash" not in response.text
    with db_session_factory() as session:
        stored = session.scalar(select(User.hashed_password).where(User.username == "newofficer"))
    assert stored.startswith("$2b$") and password not in stored
    assert pwd_context.identify(stored) == "bcrypt"
    assert int(stored.split("$")[2]) >= 12


# --------------------------------------------------------------------------
# Data exposure


def test_responses_never_carry_hashes_tokens_or_raw_identifiers(
    client: TestClient, officers
) -> None:
    cnic = "3520212345671"
    applicant = {**STRONG_APPLICANT, "borrower_identifier_type": "CNIC", "borrower_identifier": cnic}
    app_id = client.post("/score", json=applicant).json()["application_id"]
    borrower_ref = client.get(f"/score/applications/{app_id}").json()["borrower_public_id"]
    token = _login(client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).json()["access_token"]
    for path in (
        "/auth/users",
        "/auth/me",
        "/borrowers",
        f"/borrowers/{borrower_ref}",
        f"/borrowers/{borrower_ref}/history",
        "/score/applications",
        f"/score/applications/{app_id}",
        "/audit/logs?limit=200",
        "/portfolio/summary",
    ):
        text = client.get(path).text
        assert "$2b$" not in text, path
        assert "hashed_password" not in text, path
        assert token not in text, path
        assert cnic not in text, path
        assert TEST_ADMIN_PASSWORD not in text, path


def test_an_unexpected_error_returns_no_traceback() -> None:
    probe = create_app()

    @probe.get("/boom-for-test")
    async def boom() -> None:
        raise RuntimeError("internal detail /srv/secret/path password=hunter2")

    with TestClient(probe, raise_server_exceptions=False) as local:
        response = local.get("/boom-for-test", headers={"X-Request-ID": "probe-123"})
    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == "probe-123"
    assert "internal detail" not in response.text
    assert "Traceback" not in response.text and "hunter2" not in response.text
    assert response.headers["cache-control"] == "no-store"


# --------------------------------------------------------------------------
# HTTP hardening


def test_security_headers_are_on_every_api_response(anonymous_client: TestClient) -> None:
    for path in ("/health", "/health/live", "/auth/me", "/does-not-exist"):
        headers = anonymous_client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff", path
        assert headers["x-frame-options"] == "DENY", path
        assert headers["referrer-policy"] == "no-referrer", path
        assert "frame-ancestors 'none'" in headers["content-security-policy"], path
        assert headers["cache-control"] == "no-store", path
        assert "server" not in headers, path
        assert "strict-transport-security" not in headers, path
    https = anonymous_client.get("/health/live", headers={"X-Forwarded-Proto": "https"})
    assert https.headers["strict-transport-security"].startswith("max-age=")


def test_oversized_bodies_are_refused(client: TestClient) -> None:
    limit = config.max_body_bytes()
    response = client.post(
        "/score/statement",
        content=b"{" + b" " * (limit + 10) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def _asgi_call(asgi_app, headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> tuple[int, bytes]:
    import asyncio

    sent: list[dict] = []
    queue = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)]

    async def receive() -> dict:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/x", "headers": headers, "scheme": "http"}
    asyncio.run(asgi_app(scope, receive, send))
    status_code = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status_code, body


def test_body_limit_handles_chunked_and_malformed_requests() -> None:
    from services.http_security import BodySizeLimitMiddleware

    async def echo(scope, receive, send) -> None:
        total = 0
        while True:
            message = await receive()
            total += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": str(total).encode()})

    limited = BodySizeLimitMiddleware(echo, max_bytes=100)
    assert _asgi_call(limited, [], [b"a" * 60, b"b" * 30]) == (200, b"90")
    assert _asgi_call(limited, [], [b"a" * 60, b"b" * 60])[0] == 413
    assert _asgi_call(limited, [(b"content-length", b"abc")], [b""])[0] == 400
    assert _asgi_call(limited, [(b"content-length", b"500")], [b""])[0] == 413


# --------------------------------------------------------------------------
# Configuration: development vs production


STRONG_SECRET = "s" * 48
PG_URL = "postgresql+psycopg2://foriflow:{}@db:5432/foriflow"


def _production(monkeypatch, **env: str) -> None:
    monkeypatch.setenv("FORIFLOW_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    monkeypatch.delenv("FORIFLOW_ENABLE_DOCS", raising=False)
    monkeypatch.delenv("FORIFLOW_CORS_ORIGINS", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_production_refuses_a_missing_or_placeholder_jwt_secret(monkeypatch) -> None:
    good_url = PG_URL.format("Tq7-unique-db-password")
    for secret in ("", "CHANGE_ME_JWT_SECRET_KEY_AT_LEAST_32_CHARS", "too-short"):
        _production(monkeypatch, JWT_SECRET_KEY=secret)
        report = configuration_report(good_url)
        assert not report.ok
        assert any("JWT_SECRET_KEY" in problem for problem in report.problems)
        assert all(secret not in problem for problem in report.problems if secret)
    _production(monkeypatch)
    assert configuration_report(good_url).ok


def test_production_refuses_sqlite_and_weak_database_passwords(monkeypatch) -> None:
    _production(monkeypatch)
    assert not configuration_report("sqlite:///./foriflow.db").ok
    for password in ("postgres", "CHANGE_ME_POSTGRES_PASSWORD", "foriflow"):
        report = configuration_report(PG_URL.format(password))
        assert not report.ok
        assert all(password not in text for text in report.problems + report.warnings)
    short = configuration_report(PG_URL.format("Short-9x"))
    assert short.ok and any("shorter than" in warning for warning in short.warnings)


def test_development_only_warns(monkeypatch) -> None:
    monkeypatch.setenv("FORIFLOW_ENV", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    report = configuration_report("sqlite://")
    assert report.ok and any("JWT_SECRET_KEY" in warning for warning in report.warnings)


def test_an_unknown_environment_name_is_an_error(monkeypatch) -> None:
    monkeypatch.setenv("FORIFLOW_ENV", "prod")
    with pytest.raises(RuntimeError):
        config.app_env()
    assert not configuration_report("sqlite://").ok


def test_production_start_up_fails_on_an_unsafe_configuration(monkeypatch) -> None:
    _production(monkeypatch, JWT_SECRET_KEY="CHANGE_ME_JWT_SECRET_KEY_AT_LEAST_32_CHARS")
    from main import UnsafeConfiguration

    with pytest.raises(UnsafeConfiguration) as raised:
        with TestClient(create_app()):
            pass
    assert "JWT_SECRET_KEY" in str(raised.value)
    assert "CHANGE_ME_JWT" not in str(raised.value)


def test_cors_is_closed_in_production_and_never_a_wildcard(monkeypatch) -> None:
    _production(monkeypatch)
    assert config.cors_origins() == []
    monkeypatch.setenv("FORIFLOW_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError):
        config.cors_origins()
    monkeypatch.setenv("FORIFLOW_CORS_ORIGINS", "https://foriflow.bank.example")
    assert config.cors_origins() == ["https://foriflow.bank.example"]

    monkeypatch.delenv("FORIFLOW_CORS_ORIGINS")
    # No ``with``: the start-up checks (which want PostgreSQL in production)
    # are not what this test is about; CORS answers before any route runs.
    local = TestClient(create_app())
    preflight = local.options(
        "/score",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in preflight.headers


def test_development_cors_allows_the_dev_server_only(monkeypatch) -> None:
    monkeypatch.setenv("FORIFLOW_ENV", "development")
    monkeypatch.delenv("FORIFLOW_CORS_ORIGINS", raising=False)
    probe = create_app()
    with TestClient(probe) as local:
        good = local.options(
            "/score",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )
        evil = local.options(
            "/score",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
    assert good.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in good.headers
    assert "access-control-allow-origin" not in evil.headers


def test_docs_are_off_in_production_unless_asked_for(monkeypatch) -> None:
    _production(monkeypatch)
    assert config.docs_enabled() is False
    local = TestClient(create_app())
    assert local.get("/docs").status_code == 404
    assert local.get("/openapi.json").status_code == 404
    assert local.get("/").json()["docs"] is None
    monkeypatch.setenv("FORIFLOW_ENABLE_DOCS", "true")
    assert config.docs_enabled() is True
    report = configuration_report(PG_URL.format("Tq7-unique-db-password"))
    assert report.ok and any("FORIFLOW_ENABLE_DOCS" in warning for warning in report.warnings)
    monkeypatch.setenv("FORIFLOW_ENV", "development")
    monkeypatch.delenv("FORIFLOW_ENABLE_DOCS")
    assert config.docs_enabled() is True


def test_token_lifetime_is_configurable_within_bounds(monkeypatch) -> None:
    monkeypatch.setenv("FORIFLOW_JWT_EXPIRE_MINUTES", "60")
    assert config.jwt_expire_minutes() == 60
    for bad in ("5", "100000", "eight"):
        monkeypatch.setenv("FORIFLOW_JWT_EXPIRE_MINUTES", bad)
        with pytest.raises(RuntimeError):
            config.jwt_expire_minutes()


# --------------------------------------------------------------------------
# Health


def test_liveness_and_readiness(anonymous_client: TestClient, monkeypatch) -> None:
    assert anonymous_client.get("/health/live").json() == {"status": "alive"}
    ready = anonymous_client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    assert {check["name"] for check in body["checks"]} == {"database", "model", "configuration"}

    import main

    monkeypatch.setattr(main, "_database_reachable", lambda: False)
    down = anonymous_client.get("/health/ready")
    assert down.status_code == 503
    assert down.json()["status"] == "not_ready"
    # /health stays 200 for the dashboard, and says what is wrong.
    assert anonymous_client.get("/health").json()["database"] == "unavailable"


def test_health_endpoints_hold_no_secret(anonymous_client: TestClient) -> None:
    secret = config.jwt_secret_key()
    for path in ("/health", "/health/live", "/health/ready", "/"):
        text = anonymous_client.get(path).text
        assert secret not in text
        assert "sqlite" not in text.lower() and "postgresql" not in text.lower()
        assert "password" not in text.lower()


# --------------------------------------------------------------------------
# Audit trail


def test_security_events_are_audited_without_secrets(
    anonymous_client: TestClient, db_session_factory
) -> None:
    _login(anonymous_client, TEST_ADMIN_USERNAME, "wrong-password-xyz")
    token = _login(anonymous_client, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD).json()["access_token"]
    anonymous_client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    with db_session_factory() as session:
        entries = list(session.scalars(select(AuditLog).order_by(AuditLog.id)))
    actions = [entry.action for entry in entries]
    assert actions[-3:] == [Action.LOGIN_FAILED, Action.LOGIN, Action.LOGOUT]
    for entry in entries[-3:]:
        assert entry.request_id and entry.occurred_at is not None
        dumped = json.dumps(
            [entry.details, entry.previous_state, entry.new_state], default=str
        )
        assert token not in dumped
        assert TEST_ADMIN_PASSWORD not in dumped and "wrong-password-xyz" not in dumped
    assert entries[-2].user_id is not None and entries[-1].user_id == entries[-2].user_id
    assert entries[-1].details["session_id"] == entries[-2].details["session_id"]


def test_audit_routes_are_read_only() -> None:
    from routers import audit

    methods = {method for route in audit.router.routes for method in route.methods}
    assert methods == {"GET"}


def test_application_tables_untouched_by_auth_changes(client: TestClient, db_session_factory) -> None:
    """Security work must not alter credit records: scoring still stores the
    same fields and recommendation it did."""
    response = client.post("/score", json=STRONG_APPLICANT)
    assert response.status_code == 201
    with db_session_factory() as session:
        stored: Any = session.get(Application, response.json()["application_id"])
    assert stored.risk_score == response.json()["risk_score"]
