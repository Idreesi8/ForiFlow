"""Login (public) and officer-account endpoints (``/me`` any user, ``/users`` admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import JWT_EXPIRE_HOURS
from models.database import User, get_db
from schemas import LoginRequest, TokenResponse, UserCreate, UserResponse
from services.auth_service import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    validate_new_password,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(require_admin)]


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange username and password for a JWT",
)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    """Return an 8-hour Bearer token when the credentials match a seeded user."""
    user = authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token(username=user.username, role=user.role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=int(JWT_EXPIRE_HOURS * 3600),
        username=user.username,
        role=user.role,
    )


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
async def create_user(body: UserCreate, _: Admin, db: DbSession) -> UserResponse:
    """Create an ``analyst`` (default) or ``admin`` account."""
    try:
        validate_new_password(body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from None
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
    db.commit()
    db.refresh(user)
    return UserResponse.model_validate(user)
