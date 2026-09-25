"""Password hashing and JWT issue/verify for on-premise officer accounts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import JWT_ALGORITHM, JWT_EXPIRE_HOURS, jwt_secret_key
from models.database import User, get_db
from schemas import UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)

ALLOWED_ROLES = frozenset(role.value for role in UserRole)
# bcrypt silently truncates after 72 bytes; reject instead.
_MAX_PASSWORD_BYTES = 72
# Applies when a password is SET (seeding, rotation, new accounts). Login does not
# re-check it, so an account created under an older rule can still sign in and
# be rotated.
MIN_PASSWORD_LENGTH = 12
# HS256 keys shorter than the 256-bit hash output weaken the MAC (RFC 7518 3.2).
MIN_JWT_SECRET_LENGTH = 32
_PLACEHOLDER_PREFIX = "CHANGE_ME"


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    _assert_password_length(password)
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True when ``plain`` matches ``hashed``."""
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def _assert_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {_MAX_PASSWORD_BYTES} bytes."
        )


def validate_new_password(password: str) -> None:
    """Reject a password that is too short, too long or a placeholder."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if password.startswith(_PLACEHOLDER_PREFIX):
        raise ValueError("Password is still the .env.example placeholder.")
    _assert_password_length(password)


def jwt_secret_problem(secret: str) -> str | None:
    """Describe why ``secret`` cannot sign tokens, or None when it is usable."""
    if not secret:
        return "JWT_SECRET_KEY is not set. Copy .env.example to .env and set a unique secret."
    if secret.startswith(_PLACEHOLDER_PREFIX):
        return "JWT_SECRET_KEY is still the .env.example placeholder. Set a unique secret."
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        return (
            f"JWT_SECRET_KEY is {len(secret)} characters; at least "
            f"{MIN_JWT_SECRET_LENGTH} are required."
        )
    return None


def _secret() -> str:
    secret = jwt_secret_key()
    problem = jwt_secret_problem(secret)
    if problem:
        raise RuntimeError(problem)
    return secret


def create_access_token(
    *,
    username: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Return a signed HS256 JWT for ``username``."""
    lifetime = expires_delta or timedelta(hours=JWT_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on failure."""
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Return the user when credentials match, otherwise None."""
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.hashed_password):
        return None
    return user


_unauthenticated = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the Bearer token to a live ``User`` row."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthenticated
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise _unauthenticated from None

    username = payload.get("sub")
    if not username or not isinstance(username, str):
        raise _unauthenticated

    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise _unauthenticated
    return user


def require_role(*roles: UserRole):
    """Dependency factory: allow only users whose role is in ``roles``."""
    allowed = frozenset(role.value for role in roles)

    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action needs the {' or '.join(sorted(allowed))} role.",
            )
        return user

    return dependency


require_admin = require_role(UserRole.ADMIN)
