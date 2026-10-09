"""Sign-in (public), sign-out and officer accounts (``/me`` any user, ``/users`` admin).

2.3 hardening: failed sign-ins lock a username for a while, one address can
only try so often, sign-out revokes the token, and an admin can disable and
re-enable accounts. Every one of these is written to the audit trail; no
password and no token ever is.
"""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import JWT_EXPIRE_MINUTES
from models.database import User, get_db
from schemas import LoginRequest, TokenResponse, UserCreate, UserResponse, UserStatusUpdate
from services import audit_service, login_guard
from services.audit_service import Action, Audit, client_ip
from services.auth_service import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    get_current_user,
    hash_password,
    require_admin,
    revoke_token,
    validate_new_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(require_admin)]

# One message for an unknown username and a wrong password: the response
# must not say which usernames exist.
_BAD_CREDENTIALS = "Incorrect username or password"


def _too_many(seconds: float, message: str) -> HTTPException:
    minutes = max(1, math.ceil(seconds / 60))
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"{message} Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
        headers={"Retry-After": str(int(math.ceil(seconds)))},
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange username and password for a JWT",
    responses={
        401: {"description": "Wrong username or password (one message for both)."},
        403: {"description": "Correct password, but the account is disabled."},
        429: {"description": "Too many attempts; see Retry-After."},
    },
)
async def login(
    body: LoginRequest, request: Request, db: DbSession, audit: Audit
) -> TokenResponse:
    """Return a Bearer token when the credentials match an enabled account.

    Five wrong passwords for one username within 15 minutes lock that
    username for 15 minutes (429), whether or not the account exists; the lock
    lifts by itself. One address may make 30 attempts per 5 minutes. The
    password is never recorded, and neither is the token.
    """
    address = client_ip(request) or "unknown"
    wait = login_guard.login_ip_limiter.hit(address)
    if wait is not None:
        if login_guard.login_ip_limiter.first_refusal(address):
            audit_service.record(
                db,
                action=Action.LOGIN_RATE_LIMITED,
                entity_type="user",
                username=body.username,
                details={
                    "limit": login_guard.IP_MAX_ATTEMPTS,
                    "window_seconds": login_guard.IP_WINDOW_SECONDS,
                    "note": "recorded once per window; later refusals are not",
                },
                context=audit,
            )
            db.commit()
        raise _too_many(wait, "Too many sign-in attempts from this computer.")

    key = login_guard.username_key(body.username)
    locked_for = login_guard.seconds_locked(db, key)
    if locked_for is not None:
        audit_service.record(
            db,
            action=Action.LOGIN_REFUSED_LOCKED,
            entity_type="user",
            username=body.username,
            details={"seconds_remaining": locked_for},
            context=audit,
        )
        db.commit()
        raise _too_many(locked_for, "Too many failed sign-in attempts for this username.")

    user = authenticate_user(db, body.username, body.password)
    if user is None:
        outcome = login_guard.record_failure(db, key)
        audit_service.record(
            db,
            action=Action.LOGIN_FAILED,
            entity_type="user",
            username=body.username,
            details={
                "reason": "incorrect username or password",
                "failed_attempts_in_window": outcome.failed_count,
            },
            context=audit,
        )
        if outcome.locked_now:
            audit_service.record(
                db,
                action=Action.LOGIN_LOCKED,
                entity_type="user",
                username=body.username,
                details={
                    "failed_attempts": outcome.failed_count,
                    "locked_until": outcome.locked_until,
                    "lockout_minutes": int(login_guard.LOCKOUT_PERIOD.total_seconds() // 60),
                },
                context=audit,
            )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)

    if not user.is_active:
        audit_service.record(
            db,
            action=Action.LOGIN_REFUSED_DISABLED,
            entity_type="user",
            entity_id=user.id,
            username=user.username,
            details={"reason": "account disabled"},
            context=audit,
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is disabled. Ask an administrator to enable it.",
        )

    login_guard.record_success(db, key)
    token = create_access_token(username=user.username, role=user.role)
    session_id = decode_access_token(token)["jti"]
    audit_service.record(
        db,
        action=Action.LOGIN,
        entity_type="user",
        entity_id=user.id,
        actor=user,
        details={"session_lifetime_minutes": JWT_EXPIRE_MINUTES, "session_id": session_id},
        context=audit,
    )
    db.commit()
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(JWT_EXPIRE_MINUTES * 60),
        username=user.username,
        role=user.role,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out: revoke the token used for this request",
)
async def logout(request: Request, user: CurrentUser, db: DbSession, audit: Audit) -> Response:
    """The token stops working at once, on every endpoint, until it would have
    expired anyway. Other sessions of the same officer are not affected."""
    claims = request.state.token_claims
    revoke_token(db, claims, user)
    audit_service.record(
        db,
        action=Action.LOGOUT,
        entity_type="user",
        entity_id=user.id,
        actor=user,
        details={"session_id": claims["jti"]},
        context=audit,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse, summary="The signed-in officer")
async def me(user: CurrentUser) -> UserResponse:
    """Return the account the Bearer token belongs to, including its role."""
    return UserResponse.model_validate(user)


@router.get(
    "/users",
    response_model=list[UserResponse],
    summary="List officer accounts (admin only)",
)
async def list_users(_: Admin, db: DbSession) -> list[UserResponse]:
    """Every officer account, oldest first. Password hashes are never returned."""
    users = db.scalars(select(User).order_by(User.id)).all()
    return [UserResponse.model_validate(user) for user in users]


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an officer account (admin only)",
)
async def create_user(
    body: UserCreate, admin: Admin, db: DbSession, audit: Audit
) -> UserResponse:
    """Create an ``analyst`` (default), ``manager`` or ``admin`` account.

    The password must be 12 to 72 characters, not a common or sequential
    password, and must not contain the username.
    """
    try:
        validate_new_password(body.password, body.username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User {body.username!r} already exists.",
        )
    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role.value,
    )
    db.add(user)
    db.flush()
    audit_service.record(
        db,
        action=Action.USER_CREATED,
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        new={"username": user.username, "role": user.role},
        context=audit,
    )
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch(
    "/users/{user_id}/status",
    response_model=UserResponse,
    summary="Disable or re-enable an officer account (admin only)",
)
async def set_user_status(
    user_id: int, body: UserStatusUpdate, admin: Admin, db: DbSession, audit: Audit
) -> UserResponse:
    """A disabled account cannot sign in, and its open sessions stop working
    on their next request. Nothing is deleted; re-enabling restores access.

    An admin cannot disable their own account, and the last enabled admin
    cannot be disabled, so administration cannot be locked out.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such officer account.")
    if user.is_active == body.is_active:
        return UserResponse.model_validate(user)
    if not body.is_active:
        if user.id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot disable your own account.",
            )
        if user.role == "admin":
            enabled_admins = db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.role == "admin", User.is_active.is_(True))
            )
            if enabled_admins <= 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This is the last enabled admin account; it cannot be disabled.",
                )
    previous = {"is_active": user.is_active}
    user.is_active = body.is_active
    audit_service.record(
        db,
        action=Action.USER_ENABLED if body.is_active else Action.USER_DISABLED,
        entity_type="user",
        entity_id=user.id,
        actor=admin,
        previous=previous,
        new={"is_active": user.is_active, "username": user.username, "role": user.role},
        details={"reason": body.reason} if body.reason else None,
        context=audit,
    )
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)
