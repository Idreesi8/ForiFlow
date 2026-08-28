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


def _secret() -> str:
    secret = jwt_secret_key()
    if not secret:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Copy .env.example to .env and set a unique secret."
        )
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
