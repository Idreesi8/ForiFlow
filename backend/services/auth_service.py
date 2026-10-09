"""Password hashing and JWT issue/verify for on-premise officer accounts."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_ISSUER, jwt_secret_key
from models.database import RevokedToken, User, get_db, utcnow
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


# Passwords that pass a length rule and are still among the first guessed.
# Compared after lower-casing and dropping digits and symbols, so "Password123!"
# and "Qwerty2026!!" count as "password" and "qwerty". Short on purpose: it
# catches the obvious, it is not a breach corpus (see SECURITY.md).
COMMON_PASSWORD_WORDS = frozenset(
    {
        "password", "passw", "passwd", "pass", "admin", "administrator", "welcome",
        "letmein", "qwerty", "qwertyuiop", "asdfgh", "asdfghjkl", "zxcvbnm", "abc",
        "abcdef", "iloveyou", "monkey", "dragon", "master", "login", "secret",
        "changeme", "default", "foriflow", "manager", "analyst", "pakistan",
        "lahore", "karachi", "islamabad", "bank", "banking", "credit", "user",
        "test", "testing", "root", "toor", "guest",
    }
)
_KEYBOARD_RUNS = ("0123456789", "1234567890", "9876543210", "abcdefghijklmnopqrstuvwxyz", "qwertyuiop")


def _is_sequence(text: str) -> bool:
    """True for runs like 1234567890123 or 9876543210987 (digits wrap 9 to 0)."""
    def step(a: str, b: str) -> int:
        if a.isdigit() and b.isdigit():
            return (int(b) - int(a)) % 10
        return ord(b) - ord(a)

    steps = {step(a, b) for a, b in zip(text, text[1:])}
    return steps in ({1}, {9}, {-1})


def password_problem(password: str, username: str | None = None) -> str | None:
    """Why ``password`` cannot be set, or ``None`` when it is acceptable.

    The rule follows NIST SP 800-63B: length matters most, known-weak and
    account-derived passwords are refused, and no character-class recipe is
    imposed. It applies when a password is SET (new accounts, the seed
    script). Sign-in does not re-check it, so an older account still signs in.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > _MAX_PASSWORD_BYTES:
        return f"Password must be at most {_MAX_PASSWORD_BYTES} bytes."
    if password.startswith(_PLACEHOLDER_PREFIX):
        return "Password is still the .env.example placeholder."
    if len(set(password)) < 5:
        return "Password repeats too few different characters."
    lowered = password.lower()
    if any(lowered in run for run in _KEYBOARD_RUNS) or _is_sequence(lowered):
        return "Password is a keyboard or number sequence."
    letters = "".join(ch for ch in lowered if ch.isalpha())
    if letters and letters in COMMON_PASSWORD_WORDS:
        return "Password is too common or too predictable. Use a longer passphrase."
    if username and len(username) >= 3 and username.lower() in lowered:
        return "Password must not contain the username."
    return None


def validate_new_password(password: str, username: str | None = None) -> None:
    """Raise ``ValueError`` when ``password`` breaks the password rule."""
    problem = password_problem(password, username)
    if problem:
        raise ValueError(problem)


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
    """Return a signed HS256 JWT for ``username``.

    Claims: ``sub``, ``role`` (informational: the role is re-read from the
    database on every request), ``iat``, ``exp``, ``iss`` and a random ``jti``
    that sign-out uses to revoke this one token.
    """
    lifetime = expires_delta or timedelta(minutes=JWT_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "iss": JWT_ISSUER,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on failure.

    Signature, expiry, issuer and the presence of every claim are checked;
    tokens issued before 2.3 (no ``jti`` or ``iss``) are refused, so officers
    sign in again once after the upgrade.
    """
    return jwt.decode(
        token,
        _secret(),
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "iss", "jti"]},
    )


# Checked when the username is unknown, so a wrong username costs the same
# bcrypt time as a wrong password and response timing does not reveal which
# usernames exist.
_TIMING_DUMMY_HASH = pwd_context.hash("foriflow-timing-equaliser-not-a-password")


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Return the user when credentials match, otherwise None.

    A disabled account is returned too: the caller refuses it, with its own
    message, only after the password has been proved.
    """
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(password, _TIMING_DUMMY_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def is_revoked(db: Session, jti: str) -> bool:
    return db.get(RevokedToken, jti) is not None


def revoke_token(db: Session, claims: dict[str, Any], user: User) -> None:
    """Refuse this token from now on (sign-out). Idempotent."""
    jti = str(claims["jti"])
    if db.get(RevokedToken, jti) is None:
        db.add(
            RevokedToken(
                jti=jti,
                user_id=user.id,
                expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc),
            )
        )
    # Entries past their token's expiry protect nothing; drop them.
    db.execute(delete(RevokedToken).where(RevokedToken.expires_at < utcnow()))
    db.flush()


_unauthenticated = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the Bearer token to a live, enabled ``User`` row.

    Refused (401) when the token is missing, malformed, badly signed, expired,
    issued before 2.3, signed out, or names an account that no longer exists
    or has been disabled. Every refusal looks the same to the caller.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthenticated
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise _unauthenticated from None

    username = payload.get("sub")
    jti = payload.get("jti")
    if not username or not isinstance(username, str) or not isinstance(jti, str):
        raise _unauthenticated

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or is_revoked(db, jti):
        raise _unauthenticated
    # Sign-out needs the claims of the token it is revoking.
    request.state.token_claims = payload
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
# Credit decisions: Manual Review outcomes and closing EWS alerts.
require_manager = require_role(UserRole.ADMIN, UserRole.MANAGER)
